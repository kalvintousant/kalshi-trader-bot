"""
ML Prediction Layer — Ridge + RandomForest ensemble for temperature prediction.

Blends ML predictions into the statistical mean from weather sources.
Uses scikit-learn only (no xgboost). Trained on historical source forecasts
and actual temperature outcomes.

Feature set (~30 features):
- Per-source temperatures (12 columns, NaN for missing)
- Aggregate stats: mean, std, spread, n_sources
- Temporal: month_sin, month_cos, is_high, hours_until_settlement
- City one-hot encoding

Models: Ridge + RandomForestRegressor with inverse-RMSE weighted voting.
Persisted to data/ml_model.pkl via pickle.
"""

import csv
import logging
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import Config

logger = logging.getLogger(__name__)

# Singleton
_instance = None


def get_ml_predictor():
    """Get or create the singleton MLPredictor."""
    global _instance
    if _instance is None:
        _instance = MLPredictor()
    return _instance


# Known source names for feature columns (order matters for consistency)
SOURCE_COLUMNS = [
    'nws', 'nws_mos',
    'open_meteo_best_match', 'open_meteo_gfs_seamless', 'open_meteo_ecmwf_ifs025',
    'open_meteo_icon_seamless', 'open_meteo_gfs_hrrr', 'open_meteo_gem_seamless',
    'open_meteo_ukmo_seamless',
    'pirate_weather', 'visual_crossing', 'tomorrowio',
]

# Known cities for one-hot encoding
CITY_CODES = [
    'NY', 'CHI', 'MIA', 'AUS', 'LAX', 'DEN', 'PHIL',
    'DAL', 'BOS', 'ATL', 'HOU', 'SEA', 'PHX', 'MIN', 'DC', 'OKC', 'SFO',
]


class MLPredictor:
    """ML-based temperature prediction using Ridge + RandomForest ensemble."""

    def __init__(self, model_path: str = "data/ml_model.pkl"):
        self.model_path = Path(model_path)
        self.model_path.parent.mkdir(exist_ok=True)

        self.ridge = None
        self.rf = None
        self.scaler = None
        self.ridge_weight = 0.5
        self.rf_weight = 0.5
        self.ridge_rmse = None
        self.rf_rmse = None
        self.trained = False
        self.last_train_time = None
        self.training_samples = 0

        self._load_model()

    def _load_model(self):
        """Load persisted model from disk."""
        if not self.model_path.exists():
            return
        try:
            with open(self.model_path, 'rb') as f:
                state = pickle.load(f)
            self.ridge = state.get('ridge')
            self.rf = state.get('rf')
            self.scaler = state.get('scaler')
            self.ridge_weight = state.get('ridge_weight', 0.5)
            self.rf_weight = state.get('rf_weight', 0.5)
            self.ridge_rmse = state.get('ridge_rmse')
            self.rf_rmse = state.get('rf_rmse')
            self.trained = state.get('trained', False)
            self.last_train_time = state.get('last_train_time')
            self.training_samples = state.get('training_samples', 0)
            if self.trained:
                logger.info(f"📊 ML model loaded: {self.training_samples} samples, "
                          f"Ridge RMSE={self.ridge_rmse:.2f}°F, RF RMSE={self.rf_rmse:.2f}°F")
        except Exception as e:
            logger.warning(f"Could not load ML model: {e}")

    def _save_model(self):
        """Persist model to disk."""
        try:
            state = {
                'ridge': self.ridge,
                'rf': self.rf,
                'scaler': self.scaler,
                'ridge_weight': self.ridge_weight,
                'rf_weight': self.rf_weight,
                'ridge_rmse': self.ridge_rmse,
                'rf_rmse': self.rf_rmse,
                'trained': self.trained,
                'last_train_time': self.last_train_time,
                'training_samples': self.training_samples,
            }
            with open(self.model_path, 'wb') as f:
                pickle.dump(state, f)
        except Exception as e:
            logger.warning(f"Could not save ML model: {e}")

    def _build_features(self, source_temps: Dict[str, float], city: str, month: int,
                        is_high: bool, hours_until: float) -> np.ndarray:
        """Build feature vector from inputs.

        Args:
            source_temps: {source_name: temperature} dict
            city: City code (e.g., 'NY')
            month: Month number (1-12)
            is_high: True for HIGH markets, False for LOW
            hours_until: Hours until settlement

        Returns:
            1D numpy array of features
        """
        features = []

        # Per-source temperatures (NaN for missing)
        for src in SOURCE_COLUMNS:
            features.append(source_temps.get(src, np.nan))

        # Aggregate stats (ignoring NaN)
        temps = [t for t in source_temps.values() if t is not None]
        if temps:
            features.append(np.mean(temps))                    # mean
            features.append(np.std(temps) if len(temps) > 1 else 0.0)  # std
            features.append(max(temps) - min(temps))           # spread
            features.append(len(temps))                        # n_sources
        else:
            features.extend([np.nan, 0.0, 0.0, 0])

        # Temporal features
        features.append(np.sin(2 * np.pi * month / 12))       # month_sin
        features.append(np.cos(2 * np.pi * month / 12))       # month_cos
        features.append(1.0 if is_high else 0.0)              # is_high
        features.append(max(0.0, hours_until))                 # hours_until

        # City one-hot
        for c in CITY_CODES:
            features.append(1.0 if city == c else 0.0)

        return np.array(features, dtype=np.float64)

    def _load_training_data(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Load training data from source_forecasts.csv + outcomes.

        Returns:
            (X, y) numpy arrays or (None, None) if insufficient data
        """
        from .config import extract_city_code

        # Load outcomes with actual temperatures
        outcomes_file = Path("data/paper_outcomes.csv") if Config.PAPER_TRADING else Path("data/outcomes.csv")
        if not outcomes_file.exists():
            return None, None

        # Build {market_ticker: actual_temp} lookup
        actuals = {}
        try:
            with open(outcomes_file, 'r') as f:
                for row in csv.DictReader(f):
                    ticker = row.get('market_ticker', '')
                    actual = row.get('actual_temp', '')
                    if ticker and actual:
                        try:
                            actuals[ticker] = float(actual)
                        except ValueError:
                            pass
        except Exception:
            return None, None

        if len(actuals) < Config.ML_MIN_TRAINING_SAMPLES:
            logger.debug(f"ML: only {len(actuals)} outcomes with actual_temp, need {Config.ML_MIN_TRAINING_SAMPLES}")
            return None, None

        # Load trades for per-source temps and metadata
        trades_file = Path("data/trades.csv")
        if not trades_file.exists():
            return None, None

        # Build training samples
        X_list = []
        y_list = []

        try:
            with open(trades_file, 'r') as f:
                for row in csv.DictReader(f):
                    ticker = row.get('market_ticker', '')
                    if ticker not in actuals:
                        continue

                    actual_temp = actuals[ticker]

                    # Extract metadata
                    series_ticker = ticker.split('-')[0] if ticker else ''
                    city = extract_city_code(series_ticker)
                    is_high = 'HIGH' in series_ticker

                    # Parse target date for month
                    target_date_str = row.get('target_date', '')
                    month = datetime.now().month
                    if target_date_str:
                        try:
                            td = datetime.strptime(target_date_str, '%Y-%m-%d')
                            month = td.month
                        except ValueError:
                            pass

                    # Build source_temps from mean_forecast (we don't have per-source in trades.csv)
                    # Use mean_forecast as the single available feature
                    mean_forecast = row.get('mean_forecast', '')
                    if not mean_forecast:
                        continue

                    source_temps = {'aggregate_mean': float(mean_forecast)}

                    features = self._build_features(source_temps, city, month, is_high, 12.0)
                    X_list.append(features)
                    y_list.append(actual_temp)
        except Exception as e:
            logger.warning(f"Error loading ML training data: {e}")
            return None, None

        if len(X_list) < Config.ML_MIN_TRAINING_SAMPLES:
            return None, None

        return np.array(X_list), np.array(y_list)

    def train(self) -> bool:
        """Train ML models on historical data.

        Returns:
            True if training succeeded
        """
        try:
            from sklearn.linear_model import Ridge
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.preprocessing import StandardScaler
            from sklearn.impute import SimpleImputer
            from sklearn.model_selection import cross_val_score
            from sklearn.pipeline import Pipeline
        except ImportError:
            logger.warning("scikit-learn not installed — ML predictor disabled")
            return False

        X, y = self._load_training_data()
        if X is None or y is None:
            logger.info(f"ML: insufficient training data")
            return False

        logger.info(f"ML: training on {len(X)} samples...")

        # Build pipelines with imputation (handles NaN from missing sources)
        ridge_pipe = Pipeline([
            ('imputer', SimpleImputer(strategy='mean')),
            ('scaler', StandardScaler()),
            ('model', Ridge(alpha=1.0)),
        ])

        rf_pipe = Pipeline([
            ('imputer', SimpleImputer(strategy='mean')),
            ('model', RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42)),
        ])

        # 5-fold cross-validation
        ridge_scores = cross_val_score(ridge_pipe, X, y, cv=min(5, len(X)), scoring='neg_root_mean_squared_error')
        rf_scores = cross_val_score(rf_pipe, X, y, cv=min(5, len(X)), scoring='neg_root_mean_squared_error')

        ridge_rmse = -ridge_scores.mean()
        rf_rmse = -rf_scores.mean()

        logger.info(f"ML CV results: Ridge RMSE={ridge_rmse:.2f}°F, RF RMSE={rf_rmse:.2f}°F")

        # Reject models with RMSE > threshold
        ridge_ok = ridge_rmse <= Config.ML_MAX_RMSE
        rf_ok = rf_rmse <= Config.ML_MAX_RMSE

        if not ridge_ok and not rf_ok:
            logger.warning(f"ML: both models exceed RMSE threshold ({Config.ML_MAX_RMSE}°F), not using")
            self.trained = False
            self._save_model()
            return False

        # Fit on full data
        if ridge_ok:
            ridge_pipe.fit(X, y)
            self.ridge = ridge_pipe
            self.ridge_rmse = ridge_rmse
        else:
            self.ridge = None
            self.ridge_rmse = None

        if rf_ok:
            rf_pipe.fit(X, y)
            self.rf = rf_pipe
            self.rf_rmse = rf_rmse
        else:
            self.rf = None
            self.rf_rmse = None

        # Inverse-RMSE weighted voting
        if self.ridge and self.rf:
            w_ridge = 1.0 / ridge_rmse
            w_rf = 1.0 / rf_rmse
            total = w_ridge + w_rf
            self.ridge_weight = w_ridge / total
            self.rf_weight = w_rf / total
        elif self.ridge:
            self.ridge_weight = 1.0
            self.rf_weight = 0.0
        else:
            self.ridge_weight = 0.0
            self.rf_weight = 1.0

        self.trained = True
        self.last_train_time = datetime.now().isoformat()
        self.training_samples = len(X)
        self._save_model()

        logger.info(f"ML model trained: {self.training_samples} samples, "
                   f"weights Ridge={self.ridge_weight:.2f} RF={self.rf_weight:.2f}")
        return True

    def predict(self, source_temps: Dict[str, float], city: str, month: int,
                is_high: bool, hours_until: float) -> Optional[float]:
        """Predict temperature using trained ML ensemble.

        Args:
            source_temps: {source_name: temperature} dict
            city: City code
            month: Month number
            is_high: HIGH market?
            hours_until: Hours until settlement

        Returns:
            Predicted temperature in °F, or None if model not available
        """
        if not self.trained:
            return None

        try:
            features = self._build_features(source_temps, city, month, is_high, hours_until)
            X = features.reshape(1, -1)

            predictions = []
            weights = []

            if self.ridge:
                pred = self.ridge.predict(X)[0]
                predictions.append(pred)
                weights.append(self.ridge_weight)

            if self.rf:
                pred = self.rf.predict(X)[0]
                predictions.append(pred)
                weights.append(self.rf_weight)

            if not predictions:
                return None

            # Weighted average
            total_weight = sum(weights)
            result = sum(p * w for p, w in zip(predictions, weights)) / total_weight
            return float(result)

        except Exception as e:
            logger.debug(f"ML prediction error: {e}")
            return None

    def needs_retrain(self) -> bool:
        """Check if model needs retraining (weekly schedule)."""
        if not self.last_train_time:
            return True
        try:
            last = datetime.fromisoformat(self.last_train_time)
            days_since = (datetime.now() - last).days
            return days_since >= Config.ML_RETRAIN_INTERVAL_DAYS
        except (ValueError, TypeError):
            return True

    def get_status(self) -> dict:
        """Return ML model status for dashboard."""
        return {
            'enabled': Config.ML_ENABLED,
            'trained': self.trained,
            'training_samples': self.training_samples,
            'ridge_rmse': round(self.ridge_rmse, 2) if self.ridge_rmse else None,
            'rf_rmse': round(self.rf_rmse, 2) if self.rf_rmse else None,
            'ridge_weight': round(self.ridge_weight, 2),
            'rf_weight': round(self.rf_weight, 2),
            'last_train_time': self.last_train_time,
            'blend_weight': Config.ML_BLEND_WEIGHT,
        }
