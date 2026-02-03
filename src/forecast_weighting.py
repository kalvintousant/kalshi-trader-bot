"""
Dynamic Forecast Weighting

Tracks forecast accuracy by source and city, calculates rolling RMSE,
and weights forecasts by historical accuracy.

Key features:
- Store every forecast vs actual outcome
- Calculate rolling RMSE by source and city
- Weight forecasts inversely proportional to RMSE
- Adapt weights over time as accuracy changes
"""

import sqlite3
import math
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class ForecastTracker:
    """
    Tracks forecast accuracy and calculates optimal weights for each source/city combination.
    """

    def __init__(self, db_path: str = "data/forecasts.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

        # Cache for weights (recalculated periodically)
        self._weights_cache: Dict[Tuple[str, str], float] = {}
        self._weights_cache_time: Optional[datetime] = None
        self._cache_ttl_minutes = 60  # Recalculate weights every hour

    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Forecasts table - stores each forecast
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                city TEXT NOT NULL,
                target_date TEXT NOT NULL,
                source TEXT NOT NULL,
                forecast_temp REAL NOT NULL,
                forecast_low REAL,
                forecast_high REAL,
                hours_before_target REAL,
                UNIQUE(city, target_date, source, timestamp)
            )
        """)

        # Actuals table - stores actual observed temperatures
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS actuals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                target_date TEXT NOT NULL UNIQUE,
                actual_high REAL,
                actual_low REAL,
                recorded_at TEXT NOT NULL
            )
        """)

        # Accuracy table - stores calculated accuracy metrics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accuracy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                source TEXT NOT NULL,
                target_date TEXT NOT NULL,
                forecast_temp REAL NOT NULL,
                actual_temp REAL NOT NULL,
                error REAL NOT NULL,
                abs_error REAL NOT NULL,
                hours_before_target REAL,
                UNIQUE(city, source, target_date)
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_city ON forecasts(city)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_source ON forecasts(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accuracy_city_source ON accuracy(city, source)")

        conn.commit()
        conn.close()

    def store_forecast(self, city: str, target_date: str, source: str,
                       forecast_temp: float, forecast_low: float = None,
                       forecast_high: float = None, hours_before_target: float = None):
        """
        Store a forecast for later accuracy calculation

        Args:
            city: City code (e.g., 'NY', 'CHI', 'MIA')
            target_date: Date being forecast (YYYY-MM-DD)
            source: Forecast source (e.g., 'open_meteo', 'pirate_weather')
            forecast_temp: Forecasted temperature
            forecast_low: Low end of forecast range (optional)
            forecast_high: High end of forecast range (optional)
            hours_before_target: Hours before the target time
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO forecasts
                (timestamp, city, target_date, source, forecast_temp, forecast_low, forecast_high, hours_before_target)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                city,
                target_date,
                source,
                forecast_temp,
                forecast_low,
                forecast_high,
                hours_before_target
            ))
            conn.commit()
        except Exception as e:
            logger.debug(f"Error storing forecast: {e}")
        finally:
            conn.close()

    def store_actual(self, city: str, target_date: str, actual_high: float = None,
                     actual_low: float = None):
        """
        Store actual observed temperature and calculate accuracy for all forecasts

        Args:
            city: City code
            target_date: Date that was observed
            actual_high: Actual high temperature
            actual_low: Actual low temperature
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Store actual
            cursor.execute("""
                INSERT OR REPLACE INTO actuals
                (city, target_date, actual_high, actual_low, recorded_at)
                VALUES (?, ?, ?, ?, ?)
            """, (city, target_date, actual_high, actual_low, datetime.utcnow().isoformat()))

            # Calculate accuracy for all forecasts for this city/date
            cursor.execute("""
                SELECT source, forecast_temp, hours_before_target
                FROM forecasts
                WHERE city = ? AND target_date = ?
            """, (city, target_date))

            forecasts = cursor.fetchall()
            actual_temp = actual_high  # Use high temp for HIGH markets

            for source, forecast_temp, hours_before in forecasts:
                if actual_temp is not None:
                    error = forecast_temp - actual_temp
                    abs_error = abs(error)

                    cursor.execute("""
                        INSERT OR REPLACE INTO accuracy
                        (city, source, target_date, forecast_temp, actual_temp, error, abs_error, hours_before_target)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (city, source, target_date, forecast_temp, actual_temp, error, abs_error, hours_before))

            conn.commit()

            # Invalidate weights cache
            self._weights_cache_time = None

        except Exception as e:
            logger.error(f"Error storing actual: {e}")
        finally:
            conn.close()

    def get_rmse(self, city: str = None, source: str = None,
                  days_lookback: int = 30) -> Dict[Tuple[str, str], float]:
        """
        Calculate RMSE for source/city combinations

        Args:
            city: Filter by city (optional)
            source: Filter by source (optional)
            days_lookback: Number of days to look back

        Returns:
            Dict mapping (city, source) -> RMSE
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff_date = (datetime.now() - timedelta(days=days_lookback)).strftime('%Y-%m-%d')

        query = """
            SELECT city, source,
                   AVG(error) as mean_error,
                   AVG(abs_error) as mae,
                   AVG(error * error) as mse,
                   COUNT(*) as n
            FROM accuracy
            WHERE target_date >= ?
        """
        params = [cutoff_date]

        if city:
            query += " AND city = ?"
            params.append(city)
        if source:
            query += " AND source = ?"
            params.append(source)

        query += " GROUP BY city, source"

        try:
            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = {}
            for row in rows:
                city_name, source_name, mean_error, mae, mse, n = row
                rmse = math.sqrt(mse) if mse else float('inf')
                results[(city_name, source_name)] = {
                    'rmse': rmse,
                    'mae': mae,
                    'bias': mean_error,  # Positive = overforecasts, Negative = underforecasts
                    'n': n
                }

            return results
        finally:
            conn.close()

    def calculate_weights(self, city: str = None, days_lookback: int = 30,
                          min_samples: int = 5) -> Dict[str, float]:
        """
        Calculate optimal weights for each forecast source

        Uses inverse RMSE weighting - more accurate sources get higher weights.

        Args:
            city: City to calculate weights for (None for global)
            days_lookback: Days of history to use
            min_samples: Minimum samples required for a source to be weighted

        Returns:
            Dict mapping source -> weight (weights sum to 1)
        """
        # Check cache
        cache_key = (city, days_lookback)
        if (self._weights_cache_time and
            datetime.now() - self._weights_cache_time < timedelta(minutes=self._cache_ttl_minutes)):
            if cache_key in self._weights_cache:
                return self._weights_cache[cache_key]

        rmse_data = self.get_rmse(city=city, days_lookback=days_lookback)

        if not rmse_data:
            # No data - return equal weights
            return {}

        # Filter sources with enough samples
        valid_sources = {}
        for (c, source), metrics in rmse_data.items():
            if city and c != city:
                continue
            if metrics['n'] >= min_samples and metrics['rmse'] > 0:
                if source not in valid_sources or metrics['rmse'] < valid_sources[source]['rmse']:
                    valid_sources[source] = metrics

        if not valid_sources:
            return {}

        # Calculate inverse RMSE weights
        # Weight = 1/RMSE^2, then normalize
        inv_rmse_sum = sum(1 / (m['rmse'] ** 2) for m in valid_sources.values())

        weights = {}
        for source, metrics in valid_sources.items():
            weight = (1 / (metrics['rmse'] ** 2)) / inv_rmse_sum
            weights[source] = weight

        # Cache results
        self._weights_cache[cache_key] = weights
        self._weights_cache_time = datetime.now()

        return weights

    def get_weighted_forecast(self, forecasts: Dict[str, float], city: str = None) -> Tuple[float, Dict[str, float]]:
        """
        Calculate weighted average forecast using accuracy-based weights

        Args:
            forecasts: Dict mapping source -> forecast_temp
            city: City for city-specific weights (optional)

        Returns:
            (weighted_forecast, weights_used)
        """
        if not forecasts:
            return None, {}

        weights = self.calculate_weights(city=city)

        if not weights:
            # No historical data - use equal weights
            avg = sum(forecasts.values()) / len(forecasts)
            equal_weight = 1 / len(forecasts)
            return avg, {s: equal_weight for s in forecasts}

        # Apply weights only to sources we have data for
        weighted_sum = 0
        weight_sum = 0
        weights_used = {}

        for source, forecast in forecasts.items():
            source_lower = source.lower().replace(' ', '_')

            # Try to match source name
            matched_weight = None
            for w_source, w in weights.items():
                if source_lower in w_source.lower() or w_source.lower() in source_lower:
                    matched_weight = w
                    break

            if matched_weight:
                weighted_sum += forecast * matched_weight
                weight_sum += matched_weight
                weights_used[source] = matched_weight
            else:
                # Source not in history - use minimum weight
                min_weight = min(weights.values()) * 0.5 if weights else 0.1
                weighted_sum += forecast * min_weight
                weight_sum += min_weight
                weights_used[source] = min_weight

        # Normalize
        if weight_sum > 0:
            weighted_forecast = weighted_sum / weight_sum
            weights_used = {s: w / weight_sum for s, w in weights_used.items()}
        else:
            weighted_forecast = sum(forecasts.values()) / len(forecasts)

        return weighted_forecast, weights_used

    def get_bias_adjustment(self, city: str, source: str, days_lookback: int = 30) -> float:
        """
        Get bias adjustment for a source/city combination

        Returns:
            Bias in degrees (subtract from forecast to debias)
        """
        rmse_data = self.get_rmse(city=city, source=source, days_lookback=days_lookback)

        if (city, source) in rmse_data:
            return rmse_data[(city, source)]['bias']

        return 0.0

    def get_accuracy_report(self, days_lookback: int = 30) -> Dict:
        """
        Generate comprehensive accuracy report

        Returns:
            Dictionary with accuracy metrics by source and city
        """
        rmse_data = self.get_rmse(days_lookback=days_lookback)

        # Organize by source
        by_source = defaultdict(list)
        by_city = defaultdict(list)

        for (city, source), metrics in rmse_data.items():
            by_source[source].append({
                'city': city,
                **metrics
            })
            by_city[city].append({
                'source': source,
                **metrics
            })

        # Calculate source-level aggregates
        source_summary = {}
        for source, city_metrics in by_source.items():
            if city_metrics:
                avg_rmse = sum(m['rmse'] for m in city_metrics) / len(city_metrics)
                avg_mae = sum(m['mae'] for m in city_metrics) / len(city_metrics)
                avg_bias = sum(m['bias'] for m in city_metrics) / len(city_metrics)
                total_n = sum(m['n'] for m in city_metrics)

                source_summary[source] = {
                    'avg_rmse': round(avg_rmse, 2),
                    'avg_mae': round(avg_mae, 2),
                    'avg_bias': round(avg_bias, 2),
                    'total_samples': total_n,
                    'cities': len(city_metrics)
                }

        return {
            'by_source': dict(by_source),
            'by_city': dict(by_city),
            'source_summary': source_summary,
            'weights': self.calculate_weights(days_lookback=days_lookback)
        }

    def print_accuracy_report(self, days_lookback: int = 30):
        """Print formatted accuracy report"""
        report = self.get_accuracy_report(days_lookback)

        print(f"\n{'='*70}")
        print(f"  FORECAST ACCURACY REPORT (Last {days_lookback} days)")
        print(f"{'='*70}")

        print(f"\n  SOURCE SUMMARY:")
        print(f"  {'-'*66}")
        print(f"  {'Source':<20} {'RMSE':>8} {'MAE':>8} {'Bias':>8} {'Samples':>8} {'Weight':>8}")
        print(f"  {'-'*66}")

        weights = report.get('weights', {})
        for source, metrics in sorted(report['source_summary'].items(),
                                       key=lambda x: x[1]['avg_rmse']):
            weight = weights.get(source, 0) * 100
            print(f"  {source:<20} {metrics['avg_rmse']:>7.2f}° {metrics['avg_mae']:>7.2f}° "
                  f"{metrics['avg_bias']:>+7.2f}° {metrics['total_samples']:>8} {weight:>7.1f}%")

        print(f"\n  BY CITY:")
        print(f"  {'-'*66}")
        for city, sources in sorted(report['by_city'].items()):
            print(f"\n  {city}:")
            for s in sorted(sources, key=lambda x: x['rmse']):
                print(f"    {s['source']:<18} RMSE: {s['rmse']:.2f}° MAE: {s['mae']:.2f}° "
                      f"Bias: {s['bias']:+.2f}° (n={s['n']})")


# Global instance
_forecast_tracker = None

def get_forecast_tracker() -> ForecastTracker:
    """Get global forecast tracker instance"""
    global _forecast_tracker
    if _forecast_tracker is None:
        _forecast_tracker = ForecastTracker()
    return _forecast_tracker
