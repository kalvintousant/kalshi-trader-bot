"""
City/Season Error Tracker — Per-city, per-season forecast uncertainty floor.

Tracks historical forecast errors by city and season, providing calibrated
min_std values for probability distributions instead of a global 2.5°F floor.

Replaces the hardcoded `min_std = max(2.5, historical_min)` in weather_data.py
with data-driven per-city per-season floors.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from .config import Config

logger = logging.getLogger(__name__)

# Singleton instance
_instance = None


def get_city_error_tracker():
    """Get or create the singleton CityErrorTracker instance."""
    global _instance
    if _instance is None:
        _instance = CityErrorTracker()
    return _instance


class CityErrorTracker:
    """Track forecast errors by city and season for calibrated uncertainty floors."""

    # Conservative fallback std per city per season (°F)
    # Based on typical NWS forecast MAE patterns
    FALLBACK_STD = {
        'NY':  {'winter': 4.0, 'spring': 3.5, 'summer': 2.5, 'fall': 3.5},
        'CHI': {'winter': 4.5, 'spring': 4.0, 'summer': 3.0, 'fall': 3.5},
        'MIA': {'winter': 2.5, 'spring': 2.5, 'summer': 2.0, 'fall': 2.5},
        'AUS': {'winter': 3.5, 'spring': 3.5, 'summer': 2.5, 'fall': 3.0},
        'LAX': {'winter': 3.0, 'spring': 2.5, 'summer': 2.0, 'fall': 3.0},
        'DEN': {'winter': 5.0, 'spring': 4.5, 'summer': 3.5, 'fall': 4.0},
        'PHIL': {'winter': 4.0, 'spring': 3.5, 'summer': 2.5, 'fall': 3.5},
        'DAL': {'winter': 3.5, 'spring': 3.5, 'summer': 2.5, 'fall': 3.0},
        'BOS': {'winter': 4.0, 'spring': 3.5, 'summer': 2.5, 'fall': 3.5},
        'ATL': {'winter': 3.5, 'spring': 3.0, 'summer': 2.5, 'fall': 3.0},
        'HOU': {'winter': 3.0, 'spring': 3.0, 'summer': 2.5, 'fall': 3.0},
        'SEA': {'winter': 3.5, 'spring': 3.0, 'summer': 2.5, 'fall': 3.0},
        'PHX': {'winter': 3.0, 'spring': 3.0, 'summer': 3.0, 'fall': 3.0},
        'MIN': {'winter': 5.0, 'spring': 4.5, 'summer': 3.0, 'fall': 4.0},
        'DC':  {'winter': 3.5, 'spring': 3.5, 'summer': 2.5, 'fall': 3.0},
        'OKC': {'winter': 4.0, 'spring': 4.0, 'summer': 3.0, 'fall': 3.5},
        'SFO': {'winter': 3.0, 'spring': 2.5, 'summer': 2.5, 'fall': 3.0},
    }

    # Default fallback for unknown cities
    DEFAULT_FALLBACK = 3.5

    SEASON_MAP = {
        12: 'winter', 1: 'winter', 2: 'winter',
        3: 'spring', 4: 'spring', 5: 'spring',
        6: 'summer', 7: 'summer', 8: 'summer',
        9: 'fall', 10: 'fall', 11: 'fall',
    }

    MAX_HISTORY = 200  # Per city/season

    def __init__(self, state_path: str = "data/city_errors.json"):
        self.state_file = Path(state_path)
        self.state_file.parent.mkdir(exist_ok=True)
        # Structure: {city: {season: [error1, error2, ...]}}
        self.errors = {}
        self._load_state()

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, 'r') as f:
                self.errors = json.load(f)
            total = sum(len(errs) for city_data in self.errors.values() for errs in city_data.values())
            if total > 0:
                logger.info(f"📊 City error tracker: loaded {total} historical errors across {len(self.errors)} cities")
        except Exception as e:
            logger.warning(f"Could not load city error state: {e}")

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.errors, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save city error state: {e}")

    def record_error(self, city: str, month: int, forecast_error: float):
        """Record a forecast error for a city and month.

        Args:
            city: City code (e.g., 'NY', 'CHI')
            month: Month number (1-12)
            forecast_error: Absolute forecast error in °F
        """
        season = self.SEASON_MAP.get(month, 'winter')

        if city not in self.errors:
            self.errors[city] = {}
        if season not in self.errors[city]:
            self.errors[city][season] = []

        self.errors[city][season].append(round(forecast_error, 2))

        # Trim to max history
        if len(self.errors[city][season]) > self.MAX_HISTORY:
            self.errors[city][season] = self.errors[city][season][-self.MAX_HISTORY:]

        self._save_state()

    def get_min_std(self, city: str, month: int) -> float:
        """Get the minimum std floor for a city and month.

        If enough historical data exists, uses the std of past errors.
        Otherwise falls back to conservative per-city per-season defaults.

        Args:
            city: City code (e.g., 'NY', 'CHI')
            month: Month number (1-12)

        Returns:
            Minimum std in °F (never below 1.5°F)
        """
        season = self.SEASON_MAP.get(month, 'winter')
        min_samples = Config.CITY_SEASON_MIN_SAMPLES

        # Check historical data
        errors = self.errors.get(city, {}).get(season, [])
        if len(errors) >= min_samples:
            historical_std = float(np.std(errors))
            result = max(1.5, historical_std)
            logger.debug(f"City error std for {city}/{season}: {result:.2f}°F (from {len(errors)} samples)")
            return result

        # Fall back to hardcoded defaults
        city_defaults = self.FALLBACK_STD.get(city, {})
        fallback = city_defaults.get(season, self.DEFAULT_FALLBACK)
        logger.debug(f"City error std for {city}/{season}: {fallback:.1f}°F (fallback, only {len(errors)} samples)")
        return fallback

    def get_all_stats(self) -> dict:
        """Return summary stats for all cities/seasons (for dashboard)."""
        stats = {}
        for city, seasons in self.errors.items():
            stats[city] = {}
            for season, errors in seasons.items():
                if errors:
                    stats[city][season] = {
                        'count': len(errors),
                        'mean_error': round(float(np.mean(errors)), 2),
                        'std_error': round(float(np.std(errors)), 2) if len(errors) > 1 else None,
                    }
        return stats
