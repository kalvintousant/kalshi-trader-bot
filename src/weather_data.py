"""
Weather Data Aggregator - Multi-source forecast collection and probability distribution
Based on the weather trading edge strategy guide

Enhanced with additional data sources:
- Open-Meteo (free, multi-model: GFS, ECMWF, ICON, etc.)
- Pirate Weather (HRRR-based, Dark Sky format)
- Visual Crossing (historical data support)
- NOAA HRRR (3km resolution, hourly updates)
- GEFS Ensemble (31 members for uncertainty quantification)
- ECMWF Open Data (world's most accurate global model)
- NWS MOS (Model Output Statistics - bias-corrected)
"""
import os
import re
import time
import requests
import logging
import struct
import json
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from scipy import stats
from dotenv import load_dotenv
from .config import extract_city_code, Config

load_dotenv()

logger = logging.getLogger(__name__)

# Compile regex patterns once at module level for performance
TEMP_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*°?F', re.IGNORECASE)
THRESHOLD_PATTERN = re.compile(r'(?:above|below|>|<)\s*(\d+(?:\.\d+)?)', re.IGNORECASE)
# Range format: "be 71-72°" or "71-72°" (strip markdown ** before matching)
RANGE_TEMP_PATTERN = re.compile(r'(\d+)-(\d+)\s*°', re.IGNORECASE)


class WeatherDataAggregator:
    """Aggregates weather forecasts from multiple sources and builds probability distributions"""
    
    # Official NWS measurement locations per contract rules (supports both HIGH and LOW temperature markets)
    # Coordinates match exact NWS weather station locations used for contract settlement
    CITY_COORDS = {
        # New York City - Central Park (NHIGH contract: "Central Park, New York")
        'KXHIGHNY': {'lat': 40.7711, 'lon': -73.9742, 'name': 'Central Park, New York'},
        'KXLOWNY': {'lat': 40.7711, 'lon': -73.9742, 'name': 'Central Park, New York'},
        # Chicago - Midway Airport (CHIHIGH contract: "Chicago Midway, Illinois")
        'KXHIGHCHI': {'lat': 41.7868, 'lon': -87.7522, 'name': 'Chicago Midway Airport'},
        'KXLOWCHI': {'lat': 41.7868, 'lon': -87.7522, 'name': 'Chicago Midway Airport'},
        # Miami - Miami International Airport (MIHIGH contract - likely MIA)
        'KXHIGHMIA': {'lat': 25.7932, 'lon': -80.2906, 'name': 'Miami International Airport'},
        'KXLOWMIA': {'lat': 25.7932, 'lon': -80.2906, 'name': 'Miami International Airport'},
        # Austin - Austin Bergstrom International Airport (AUSHIGH contract: "Austin Bergstrom")
        'KXHIGHAUS': {'lat': 30.1831, 'lon': -97.6799, 'name': 'Austin Bergstrom International Airport'},
        'KXLOWAUS': {'lat': 30.1831, 'lon': -97.6799, 'name': 'Austin Bergstrom International Airport'},
        # Los Angeles - Los Angeles International Airport (LAXHIGH contract - likely LAX)
        'KXHIGHLAX': {'lat': 33.9425, 'lon': -118.4081, 'name': 'Los Angeles International Airport'},
        'KXLOWLAX': {'lat': 33.9425, 'lon': -118.4081, 'name': 'Los Angeles International Airport'},
        # Denver - Denver International Airport (DENHIGH contract - likely DEN)
        'KXHIGHDEN': {'lat': 39.8561, 'lon': -104.6737, 'name': 'Denver International Airport'},
        'KXLOWDEN': {'lat': 39.8561, 'lon': -104.6737, 'name': 'Denver International Airport'},
        # Philadelphia - Philadelphia International Airport
        'KXHIGHPHIL': {'lat': 39.8721, 'lon': -75.2411, 'name': 'Philadelphia International Airport'},
        'KXLOWTPHIL': {'lat': 39.8721, 'lon': -75.2411, 'name': 'Philadelphia International Airport'},
        # Dallas - DFW Airport
        'KXHIGHTDAL': {'lat': 32.8968, 'lon': -97.0380, 'name': 'DFW Airport'},
        # Boston - Boston Logan Airport
        'KXHIGHTBOS': {'lat': 42.3656, 'lon': -71.0096, 'name': 'Boston Logan Airport'},
        # Atlanta - Hartsfield-Jackson Airport
        'KXHIGHTATL': {'lat': 33.6407, 'lon': -84.4277, 'name': 'Hartsfield-Jackson Airport'},
        # Houston - Houston Hobby Airport
        'KXHIGHTHOU': {'lat': 29.6454, 'lon': -95.2789, 'name': 'Houston Hobby Airport'},
        # Seattle - Seattle-Tacoma Airport
        'KXHIGHTSEA': {'lat': 47.4502, 'lon': -122.3088, 'name': 'Seattle-Tacoma Airport'},
        # Phoenix - Phoenix Sky Harbor Airport
        'KXHIGHTPHX': {'lat': 33.4373, 'lon': -112.0078, 'name': 'Phoenix Sky Harbor Airport'},
        # Minneapolis - MSP Airport
        'KXHIGHTMIN': {'lat': 44.8848, 'lon': -93.2223, 'name': 'MSP Airport'},
        # Washington DC - Reagan National Airport
        'KXHIGHTDC': {'lat': 38.8512, 'lon': -77.0402, 'name': 'Reagan National Airport'},
        # Oklahoma City - Will Rogers Airport
        'KXHIGHTOKC': {'lat': 35.3931, 'lon': -97.6007, 'name': 'Will Rogers Airport'},
        # San Francisco - SFO Airport
        'KXHIGHTSFO': {'lat': 37.6213, 'lon': -122.3790, 'name': 'SFO Airport'},
    }
    
    # Official NWS station IDs matching Kalshi CLI settlement sources
    # These are the exact ICAO codes whose Daily Climate Report (CLI) Kalshi uses
    CITY_STATIONS = {
        'NY': 'KNYC',    # Central Park
        'CHI': 'KMDW',   # Chicago Midway (NOT O'Hare)
        'MIA': 'KMIA',   # Miami International
        'AUS': 'KAUS',   # Austin Bergstrom
        'LAX': 'KLAX',   # LAX Airport
        'DEN': 'KDEN',   # Denver International
        'PHIL': 'KPHL',  # Philadelphia International
        'DAL': 'KDFW',   # DFW Airport
        'BOS': 'KBOS',   # Boston Logan
        'ATL': 'KATL',   # Hartsfield-Jackson
        'HOU': 'KHOU',   # Houston Hobby
        'SEA': 'KSEA',   # Seattle-Tacoma
        'PHX': 'KPHX',   # Phoenix Sky Harbor
        'MIN': 'KMSP',   # Minneapolis-St. Paul
        'DC': 'KDCA',    # Reagan National
        'OKC': 'KOKC',   # Will Rogers
        'SFO': 'KSFO',   # SFO Airport
    }

    # IANA timezones for each city (used to determine "local time" for high-of-day cutoff)
    CITY_TIMEZONES = {
        'KXHIGHNY': 'America/New_York', 'KXLOWNY': 'America/New_York',
        'KXHIGHCHI': 'America/Chicago', 'KXLOWCHI': 'America/Chicago',
        'KXHIGHMIA': 'America/New_York', 'KXLOWMIA': 'America/New_York',
        'KXHIGHAUS': 'America/Chicago', 'KXLOWAUS': 'America/Chicago',
        'KXHIGHLAX': 'America/Los_Angeles', 'KXLOWLAX': 'America/Los_Angeles',
        'KXHIGHDEN': 'America/Denver', 'KXLOWDEN': 'America/Denver',
        'KXHIGHPHIL': 'America/New_York', 'KXLOWTPHIL': 'America/New_York',
        'KXHIGHTDAL': 'America/Chicago',
        'KXHIGHTBOS': 'America/New_York',
        'KXHIGHTATL': 'America/New_York',
        'KXHIGHTHOU': 'America/Chicago',
        'KXHIGHTSEA': 'America/Los_Angeles',
        'KXHIGHTPHX': 'America/Phoenix',
        'KXHIGHTMIN': 'America/Chicago',
        'KXHIGHTDC': 'America/New_York',
        'KXHIGHTOKC': 'America/Chicago',
        'KXHIGHTSFO': 'America/Los_Angeles',
    }
    
    # Local hour (24h) after which we assume the high of the day has occurred (longshot value is minimal)
    LONGSHOT_HIGH_CUTOFF_HOUR = 16  # 4 PM local (high typically occurs 2-5 PM)
    # Local hour (24h) after which we assume the low of the day has occurred (longshot value is minimal)
    LONGSHOT_LOW_CUTOFF_HOUR = 8  # 8 AM local (low typically occurs 4-7 AM); overridden from Config in __init__
    
    def __init__(self):
        # API keys from environment (optional - will use free tiers where possible)
        # OpenWeather removed per user request
        self.tomorrowio_api_key = os.getenv('TOMORROWIO_API_KEY', '')
        self.accuweather_api_key = os.getenv('ACCUWEATHER_API_KEY', '')
        self.weatherbit_api_key = os.getenv('WEATHERBIT_API_KEY', '')

        # New data source API keys
        self.pirate_weather_api_key = os.getenv('PIRATE_WEATHER_API_KEY', '')
        self.visual_crossing_api_key = os.getenv('VISUAL_CROSSING_API_KEY', '')

        # Source enable/disable flags (for testing NOAA-only mode)
        self.enable_nws = os.getenv('ENABLE_NWS', 'true').lower() == 'true'
        self.enable_nws_mos = os.getenv('ENABLE_NWS_MOS', 'true').lower() == 'true'
        self.enable_open_meteo = os.getenv('ENABLE_OPEN_METEO', 'true').lower() == 'true'
        self.enable_pirate_weather = os.getenv('ENABLE_PIRATE_WEATHER', 'true').lower() == 'true'
        self.enable_visual_crossing = os.getenv('ENABLE_VISUAL_CROSSING', 'true').lower() == 'true'
        self.enable_tomorrowio = os.getenv('ENABLE_TOMORROWIO', 'true').lower() == 'true'
        self.enable_forecast_logging = os.getenv('ENABLE_FORECAST_LOGGING', 'true').lower() == 'true'

        # Log enabled sources on init
        enabled_sources = []
        if self.enable_nws: enabled_sources.append('NWS')
        if self.enable_nws_mos: enabled_sources.append('NWS_MOS')
        if self.enable_open_meteo: enabled_sources.append('Open-Meteo')
        if self.enable_pirate_weather and self.pirate_weather_api_key: enabled_sources.append('Pirate Weather')
        if self.enable_visual_crossing and self.visual_crossing_api_key: enabled_sources.append('Visual Crossing')
        if self.enable_tomorrowio and self.tomorrowio_api_key: enabled_sources.append('Tomorrow.io')
        self._enabled_sources = enabled_sources
        logger.info(f"🌡️ Weather sources enabled: {', '.join(enabled_sources) if enabled_sources else 'NONE'}")

        # Cache for forecasts (from Config)
        # Based on AUSHIGH contract rules: daily markets, forecasts update 2-4x/day
        # Cache TTL balances freshness with API rate limits
        self.forecast_cache = {}
        self.cache_timestamp = {}
        self.cache_ttl = Config.FORECAST_CACHE_TTL
        # Use configurable cutoff for today's low markets (default 8 AM local)
        self.LONGSHOT_LOW_CUTOFF_HOUR = getattr(Config, 'LONGSHOT_LOW_CUTOFF_HOUR', self.LONGSHOT_LOW_CUTOFF_HOUR)

        # Forecast metadata cache (stores source and timestamp for each forecast)
        self.forecast_metadata = {}  # {cache_key: [(corrected_temp, source, timestamp, raw_temp), ...]}
        
        # File to log individual source forecasts for later analysis
        self.forecasts_log_file = Path("data/source_forecasts.csv")
        self._init_forecasts_log()

        # Ensemble data cache (stores full ensemble for uncertainty calculation)
        self.ensemble_cache = {}  # {cache_key: {'forecasts': [...], 'std': float, 'timestamp': datetime}}

        # NWS station cache — permanent per session (stations don't change)
        self._nws_station_cache = {}  # {series_ticker: station_id_url}
        # NWS observation cache — 5min TTL (NWS updates ~hourly)
        self._nws_obs_cache = {}  # {(series_ticker, 'high'/'low'): (result, timestamp)}
        self._nws_obs_cache_ttl = 300  # 5 minutes

        # Per-source 429 backoff: skip sources that are rate-limited
        # {source_name: datetime when we can retry}
        self._source_backoff = {}
        self._source_backoff_duration = 3600  # 1 hour backoff on 429

        # Source reliability weights (based on historical accuracy)
        # NWS gets extra weight because Kalshi settles on the NWS CLI report
        nws_w = Config.NWS_SOURCE_WEIGHT
        self.source_weights = {
            'nws': nws_w,            # Kalshi settles on NWS CLI — highest weight
            'nws_mos': nws_w,        # MOS is bias-corrected NWS, equally authoritative
            'tomorrowio': 0.9,       # Very reliable commercial source
            'open_meteo_best': 0.95, # Open-Meteo best match (auto-selects best model)
            'open_meteo_gfs': 0.85,  # GFS model via Open-Meteo
            'open_meteo_ecmwf': 0.95,# ECMWF model via Open-Meteo (best global model)
            'open_meteo_icon': 0.85, # ICON model via Open-Meteo
            'open_meteo_gfs_hrrr': 0.95, # GFS+HRRR blend - best short-range US model
            'open_meteo_gem_seamless': 0.85, # Canadian GEM - independent global model
            'open_meteo_ukmo_seamless': 0.85, # UK Met Office - independent global model
            'pirate_weather': 0.9,   # HRRR-based, excellent for short-term US forecasts
            'visual_crossing': 0.85, # Good aggregated source
            'weatherbit': 0.8,       # Good but less reliable
            'hrrr': 0.95,            # NOAA HRRR - best short-term US model
            'gefs_mean': 0.85,       # GEFS ensemble mean
            'ecmwf_open': 0.95,      # ECMWF open data
        }

        # Model-specific bias correction (learned from historical errors)
        # Format: {source: {city_base: {month: bias_correction}}}
        # Positive bias = model runs hot, negative = model runs cold
        self.model_bias = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

        # Seed LAX warm bias from observed forecast errors (coastal marine layer)
        for source in self.source_weights:
            self.model_bias[source]['LAX'][1] = 2.0  # January
            self.model_bias[source]['LAX'][2] = 2.0  # February

        # Historical forecast error tracking
        # Format: {series_ticker: {month: [errors...]}}
        self.forecast_error_history = defaultdict(lambda: defaultdict(list))

        # Per-model error tracking for bias correction
        # Format: {source: {series_ticker: {month: [(predicted, actual), ...]}}}
        self.model_error_history = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

        # Use session for connection pooling
        self.session = requests.Session()

        # Load persisted learned state (biases, errors)
        self._load_learned_state()
    
    def _init_forecasts_log(self):
        """Initialize source_forecasts.csv if it doesn't exist"""
        if not self.forecasts_log_file.exists():
            self.forecasts_log_file.parent.mkdir(exist_ok=True)
            with open(self.forecasts_log_file, 'w', newline='') as f:
                import csv
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'series_ticker', 'target_date', 'source',
                    'forecast_temp', 'market_type', 'hours_until_settlement', 'city'
                ])

    def _is_source_backed_off(self, source: str) -> bool:
        """Check if a source is in 429 backoff period."""
        retry_after = self._source_backoff.get(source)
        if retry_after and datetime.now() < retry_after:
            return True
        # Clear expired backoff
        if retry_after:
            del self._source_backoff[source]
        return False

    def _set_source_backoff(self, source: str) -> None:
        """Put a source into backoff after a 429 response."""
        retry_at = datetime.now() + timedelta(seconds=self._source_backoff_duration)
        if source not in self._source_backoff:
            logger.warning(f"{source} rate limited (429), backing off for {self._source_backoff_duration // 60} min")
        self._source_backoff[source] = retry_at

    def _log_source_forecast(self, series_ticker: str, target_date: datetime,
                            source: str, forecast_temp: float):
        """Log individual source forecast to CSV for later accuracy analysis"""
        if not self.enable_forecast_logging:
            return

        try:
            import csv
            market_type = 'low' if 'LOW' in series_ticker else 'high'

            # Extract city from series ticker (e.g., KXHIGHNY -> NY)
            city = extract_city_code(series_ticker)

            # Calculate hours until settlement (roughly 11 PM local for daily markets)
            # Use a simple estimate - actual settlement time varies by city
            settlement_time = datetime.combine(target_date.date(), datetime.max.time().replace(hour=23, minute=0))
            hours_until = max(0, (settlement_time - datetime.now()).total_seconds() / 3600)

            with open(self.forecasts_log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    series_ticker,
                    target_date.date().isoformat(),
                    source,
                    f"{forecast_temp:.2f}",
                    market_type,
                    f"{hours_until:.1f}",
                    city
                ])
        except Exception as e:
            logger.debug(f"Error logging source forecast: {e}")
    
    def get_forecast_tomorrowio(self, lat: float, lon: float, date: datetime, series_ticker: str = '') -> Optional[Tuple[float, str, datetime]]:
        """Get forecast from Tomorrow.io API - returns (temp, source, timestamp) for HIGH/LOW markets"""
        if not self.tomorrowio_api_key:
            return None
        if self._is_source_backed_off('tomorrowio'):
            return None

        try:
            # Request both temperatureMax and temperatureMin
            is_low_market = 'LOW' in series_ticker
            temp_field = 'temperatureMin' if is_low_market else 'temperatureMax'

            url = f"https://api.tomorrow.io/v4/timelines"
            params = {
                'location': f"{lat},{lon}",
                'fields': temp_field,
                'timesteps': 'daily',
                'apikey': self.tomorrowio_api_key
            }
            response = self.session.get(url, params=params, timeout=5)
            if response.status_code == 429:
                self._set_source_backoff('tomorrowio')
                return None
            if response.status_code != 200:
                logger.warning(f"Tomorrow.io API returned {response.status_code} for {series_ticker}")
                return None

            data = response.json()
            # Parse response for target date
            target_date_str = date.strftime('%Y-%m-%d')
            for timeline in data.get('data', {}).get('timelines', []):
                for point in timeline.get('intervals', []):
                    point_date = point['startTime'][:10]
                    if point_date == target_date_str:
                        temp = point['values'].get(temp_field)
                        if temp is not None:
                            # Return temp, source, and current timestamp
                            return (temp, 'tomorrowio', datetime.now())
        except Exception as e:
            logger.debug(f"Tomorrow.io API error: {e}")
        return None
    
    def get_forecast_nws(self, lat: float, lon: float, date: datetime, series_ticker: str = '') -> Optional[Tuple[float, str, datetime]]:
        """Get forecast from National Weather Service (free, no API key needed) - returns (temp, source, timestamp) for HIGH/LOW markets"""
        try:
            is_low_market = 'LOW' in series_ticker
            
            # NWS requires grid coordinates first
            grid_url = f"https://api.weather.gov/points/{lat},{lon}"
            response = self.session.get(grid_url, timeout=5, headers={'User-Agent': 'KalshiBot/1.0'})
            if response.status_code == 200:
                grid_data = response.json()
                forecast_url = grid_data.get('properties', {}).get('forecast')
                if not forecast_url:
                    return None
                forecast_response = self.session.get(forecast_url, timeout=5, headers={'User-Agent': 'KalshiBot/1.0'})
                if forecast_response.status_code == 200:
                    forecast_data = forecast_response.json()
                    target_date_str = date.strftime('%Y-%m-%d')
                    for period in forecast_data.get('properties', {}).get('periods', []):
                        period_date = datetime.fromisoformat(period['startTime'].replace('Z', '+00:00')).date()
                        # For LOW markets: use nighttime period (has low temp)
                        # For HIGH markets: use daytime period (has high temp)
                        is_correct_period = (not period['isDaytime']) if is_low_market else period['isDaytime']
                        if period_date == date.date() and is_correct_period:
                            # Extract temp from forecast
                            temp = period.get('temperature')
                            if temp is not None:
                                # Return temp, source, and current timestamp
                                return (temp, 'nws', datetime.now())
        except Exception as e:
            logger.debug(f"NWS API error: {e}")
        return None
    
    def get_forecast_weatherbit(self, lat: float, lon: float, date: datetime, series_ticker: str = '') -> Optional[Tuple[float, str, datetime]]:
        """Get forecast from Weatherbit API - returns (temp, source, timestamp) for HIGH/LOW markets"""
        if not self.weatherbit_api_key:
            return None
        
        try:
            # Weatherbit provides 16-day forecast
            url = "https://api.weatherbit.io/v2.0/forecast/daily"
            params = {
                'lat': lat,
                'lon': lon,
                'key': self.weatherbit_api_key,
                'units': 'I'  # Imperial (Fahrenheit)
            }
            response = self.session.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                target_date_str = date.strftime('%Y-%m-%d')
                for day in data.get('data', []):
                    forecast_date = day.get('valid_date', '')
                    if forecast_date == target_date_str:
                        # Return max temp for HIGH markets, min temp for LOW markets
                        if 'LOW' in series_ticker:
                            temp = day.get('min_temp')  # Minimum temperature for LOW markets
                        else:
                            temp = day.get('max_temp')  # Maximum temperature for HIGH markets
                        if temp is not None:
                            # Return temp, source, and current timestamp
                            return (temp, 'weatherbit', datetime.now())
        except Exception as e:
            logger.debug(f"Weatherbit API error: {e}")
        return None

    # ==================== NEW DATA SOURCES ====================

    def get_forecast_open_meteo(self, lat: float, lon: float, date: datetime, series_ticker: str = '',
                                model: str = 'best_match') -> Optional[Tuple[float, str, datetime]]:
        """
        Get forecast from Open-Meteo API (100% free, no API key required)
        Supports multiple weather models: best_match, gfs_seamless, ecmwf_ifs025, icon_seamless

        Free tier: 10,000 requests/day
        Returns (temp, source, timestamp) for HIGH/LOW markets
        """
        try:
            is_low_market = 'LOW' in series_ticker
            temp_field = 'temperature_2m_min' if is_low_market else 'temperature_2m_max'

            # Open-Meteo supports multiple models in one request
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                'latitude': lat,
                'longitude': lon,
                'daily': f'{temp_field}',
                'temperature_unit': 'fahrenheit',
                'timezone': 'auto',
                'forecast_days': 7
            }

            # Add specific model if not using best_match
            if model != 'best_match':
                params['models'] = model

            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                target_date_str = date.strftime('%Y-%m-%d')
                daily_data = data.get('daily', {})
                dates = daily_data.get('time', [])
                temps = daily_data.get(temp_field, [])

                for i, forecast_date in enumerate(dates):
                    if forecast_date == target_date_str and i < len(temps):
                        temp = temps[i]
                        if temp is not None:
                            source_name = f'open_meteo_{model}' if model != 'best_match' else 'open_meteo_best'
                            return (temp, source_name, datetime.now())
        except Exception as e:
            logger.debug(f"Open-Meteo API error (model={model}): {e}")
        return None

    def get_forecast_open_meteo_multi(self, lat: float, lon: float, date: datetime,
                                      series_ticker: str = '') -> List[Tuple[float, str, datetime]]:
        """
        Get forecasts from multiple Open-Meteo models in a single request
        Returns list of (temp, source, timestamp) tuples for ensemble building
        """
        results = []
        try:
            is_low_market = 'LOW' in series_ticker
            temp_field = 'temperature_2m_min' if is_low_market else 'temperature_2m_max'

            # Request multiple models at once for efficiency
            url = "https://api.open-meteo.com/v1/forecast"
            models = ['gfs_seamless', 'ecmwf_ifs025', 'icon_seamless', 'gem_seamless', 'jma_seamless']
            params = {
                'latitude': lat,
                'longitude': lon,
                'daily': temp_field,
                'temperature_unit': 'fahrenheit',
                'timezone': 'auto',
                'forecast_days': 7,
                'models': ','.join(models)
            }

            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                target_date_str = date.strftime('%Y-%m-%d')

                # When multiple models are requested, data is structured differently
                # Each model gets its own section
                for model in models:
                    model_key = f'daily_{model}' if f'daily_{model}' in data else 'daily'
                    daily_data = data.get(model_key, data.get('daily', {}))

                    if daily_data:
                        dates = daily_data.get('time', [])
                        temps = daily_data.get(temp_field, [])

                        for i, forecast_date in enumerate(dates):
                            if forecast_date == target_date_str and i < len(temps):
                                temp = temps[i]
                                if temp is not None:
                                    results.append((temp, f'open_meteo_{model}', datetime.now()))
                                break
        except Exception as e:
            logger.debug(f"Open-Meteo multi-model API error: {e}")

        return results

    def get_forecast_pirate_weather(self, lat: float, lon: float, date: datetime,
                                    series_ticker: str = '') -> Optional[Tuple[float, str, datetime]]:
        """
        Get forecast from Pirate Weather API (HRRR-based, Dark Sky format)
        Free tier: 10,000 requests/month (~333/day)
        Excellent for short-term US forecasts due to HRRR model usage

        Returns (temp, source, timestamp) for HIGH/LOW markets
        """
        if not self.pirate_weather_api_key:
            return None
        if self._is_source_backed_off('pirate_weather'):
            return None

        try:
            is_low_market = 'LOW' in series_ticker

            # Pirate Weather uses Dark Sky API format
            url = f"https://api.pirateweather.net/forecast/{self.pirate_weather_api_key}/{lat},{lon}"
            params = {
                'exclude': 'currently,minutely,hourly,alerts',
                'units': 'us'  # Fahrenheit
            }

            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 429:
                self._set_source_backoff('pirate_weather')
                return None
            if response.status_code != 200:
                logger.warning(f"Pirate Weather API returned {response.status_code} for {series_ticker}")
                return None

            data = response.json()
            target_date_str = date.strftime('%Y-%m-%d')

            for day in data.get('daily', {}).get('data', []):
                # Pirate Weather uses Unix timestamps
                day_date = datetime.fromtimestamp(day['time']).strftime('%Y-%m-%d')
                if day_date == target_date_str:
                    if is_low_market:
                        temp = day.get('temperatureMin') or day.get('temperatureLow')
                    else:
                        temp = day.get('temperatureMax') or day.get('temperatureHigh')

                    if temp is not None:
                        return (temp, 'pirate_weather', datetime.now())
        except Exception as e:
            logger.debug(f"Pirate Weather API error: {e}")
        return None

    def get_forecast_visual_crossing(self, lat: float, lon: float, date: datetime,
                                     series_ticker: str = '') -> Optional[Tuple[float, str, datetime]]:
        """
        Get forecast from Visual Crossing API
        Free tier: 1,000 records/day
        Good for both forecasts and historical data

        Returns (temp, source, timestamp) for HIGH/LOW markets
        """
        if not self.visual_crossing_api_key:
            return None
        if self._is_source_backed_off('visual_crossing'):
            return None

        try:
            is_low_market = 'LOW' in series_ticker
            target_date_str = date.strftime('%Y-%m-%d')

            url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{lat},{lon}/{target_date_str}"
            params = {
                'key': self.visual_crossing_api_key,
                'unitGroup': 'us',  # Fahrenheit
                'include': 'days',
                'elements': 'datetime,tempmax,tempmin'
            }

            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 429:
                self._set_source_backoff('visual_crossing')
                return None
            if response.status_code != 200:
                logger.warning(f"Visual Crossing API returned {response.status_code} for {series_ticker}")
                return None

            data = response.json()
            for day in data.get('days', []):
                if day.get('datetime') == target_date_str:
                    if is_low_market:
                        temp = day.get('tempmin')
                    else:
                        temp = day.get('tempmax')

                    if temp is not None:
                        return (temp, 'visual_crossing', datetime.now())
        except Exception as e:
            logger.debug(f"Visual Crossing API error: {e}")
        return None

    def get_forecast_nws_mos(self, lat: float, lon: float, date: datetime,
                            series_ticker: str = '') -> Optional[Tuple[float, str, datetime]]:
        """
        Get MOS (Model Output Statistics) forecast from NWS
        MOS data is bias-corrected and statistically post-processed
        Free, no API key required

        Returns (temp, source, timestamp) for HIGH/LOW markets
        """
        try:
            is_low_market = 'LOW' in series_ticker

            # First, get the nearest forecast office and station
            points_url = f"https://api.weather.gov/points/{lat},{lon}"
            response = self.session.get(points_url, timeout=5, headers={'User-Agent': 'KalshiBot/1.0'})

            if response.status_code != 200:
                return None

            points_data = response.json()
            props = points_data.get('properties', {})
            grid_id = props.get('gridId')
            grid_x = props.get('gridX')
            grid_y = props.get('gridY')

            if not all([grid_id, grid_x, grid_y]):
                return None

            # Get gridpoint forecast (includes MOS-like data in quantitative values)
            gridpoint_url = f"https://api.weather.gov/gridpoints/{grid_id}/{grid_x},{grid_y}"
            gridpoint_response = self.session.get(gridpoint_url, timeout=10, headers={'User-Agent': 'KalshiBot/1.0'})

            if gridpoint_response.status_code == 200:
                grid_data = gridpoint_response.json()
                props = grid_data.get('properties', {})

                # Get min/max temperature forecasts
                if is_low_market:
                    temp_data = props.get('minTemperature', {})
                else:
                    temp_data = props.get('maxTemperature', {})

                values = temp_data.get('values', [])
                target_date_str = date.strftime('%Y-%m-%d')

                for value in values:
                    valid_time = value.get('validTime', '')
                    if target_date_str in valid_time:
                        temp_c = value.get('value')
                        if temp_c is not None:
                            # Convert Celsius to Fahrenheit
                            temp_f = (temp_c * 9/5) + 32
                            return (temp_f, 'nws_mos', datetime.now())
        except Exception as e:
            logger.debug(f"NWS MOS API error: {e}")
        return None

    def get_forecast_gefs_ensemble(self, lat: float, lon: float, date: datetime,
                                   series_ticker: str = '') -> List[Tuple[float, str, datetime]]:
        """
        Get GEFS (Global Ensemble Forecast System) ensemble forecasts
        GEFS provides 31 ensemble members (1 control + 30 perturbations)
        This gives real uncertainty quantification instead of synthetic estimates

        Uses Open-Meteo's GEFS endpoint for easier access (avoids GRIB parsing)
        Free, no API key required

        Returns list of (temp, source, timestamp) tuples for all ensemble members
        """
        results = []
        try:
            is_low_market = 'LOW' in series_ticker
            temp_field = 'temperature_2m_min' if is_low_market else 'temperature_2m_max'

            # Open-Meteo provides GEFS ensemble data
            url = "https://ensemble-api.open-meteo.com/v1/ensemble"
            params = {
                'latitude': lat,
                'longitude': lon,
                'daily': temp_field,
                'temperature_unit': 'fahrenheit',
                'timezone': 'auto',
                'forecast_days': 7,
                'models': 'gfs_seamless'  # GFS ensemble
            }

            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                target_date_str = date.strftime('%Y-%m-%d')
                daily_data = data.get('daily', {})
                dates = daily_data.get('time', [])

                # Ensemble data comes as arrays for each member
                # Format: temperature_2m_max_member01, temperature_2m_max_member02, etc.
                for key, values in daily_data.items():
                    if temp_field in key and 'member' in key:
                        member_num = key.split('member')[-1] if 'member' in key else '00'
                        for i, forecast_date in enumerate(dates):
                            if forecast_date == target_date_str and i < len(values):
                                temp = values[i]
                                if temp is not None:
                                    results.append((temp, f'gefs_member{member_num}', datetime.now()))
                                break

                # Also get the ensemble mean if available
                mean_key = temp_field
                if mean_key in daily_data:
                    for i, forecast_date in enumerate(dates):
                        if forecast_date == target_date_str:
                            temps = daily_data[mean_key]
                            if i < len(temps) and temps[i] is not None:
                                results.append((temps[i], 'gefs_mean', datetime.now()))
                            break

        except Exception as e:
            logger.debug(f"GEFS Ensemble API error: {e}")

        return results

    def get_forecast_ecmwf_ensemble(self, lat: float, lon: float, date: datetime,
                                    series_ticker: str = '') -> List[Tuple[float, str, datetime]]:
        """
        Get ECMWF IFS ensemble forecasts via Open-Meteo
        ECMWF provides 51 ensemble members (1 control + 50 perturbations)
        This is the world's most accurate global model

        Returns list of (temp, source, timestamp) tuples for all ensemble members
        """
        results = []
        try:
            is_low_market = 'LOW' in series_ticker
            temp_field = 'temperature_2m_min' if is_low_market else 'temperature_2m_max'

            url = "https://ensemble-api.open-meteo.com/v1/ensemble"
            params = {
                'latitude': lat,
                'longitude': lon,
                'daily': temp_field,
                'temperature_unit': 'fahrenheit',
                'timezone': 'auto',
                'forecast_days': 7,
                'models': 'ecmwf_ifs025'  # ECMWF ensemble
            }

            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                target_date_str = date.strftime('%Y-%m-%d')
                daily_data = data.get('daily', {})
                dates = daily_data.get('time', [])

                # Ensemble data comes as arrays for each member
                for key, values in daily_data.items():
                    if temp_field in key:
                        if 'member' in key:
                            member_num = key.split('member')[-1]
                            source_name = f'ecmwf_member{member_num}'
                        else:
                            source_name = 'ecmwf_mean'

                        for i, forecast_date in enumerate(dates):
                            if forecast_date == target_date_str and i < len(values):
                                temp = values[i]
                                if temp is not None:
                                    results.append((temp, source_name, datetime.now()))
                                break

        except Exception as e:
            logger.debug(f"ECMWF Ensemble API error: {e}")

        return results

    def get_ensemble_spread(self, lat: float, lon: float, date: datetime,
                           series_ticker: str = '') -> Optional[Dict]:
        """
        Get ensemble spread data from multiple ensemble systems
        This provides real uncertainty quantification instead of synthetic estimates

        Returns dict with:
        - 'mean': ensemble mean temperature
        - 'std': ensemble standard deviation (real uncertainty)
        - 'min': minimum ensemble member
        - 'max': maximum ensemble member
        - 'n_members': number of ensemble members
        - 'source': primary ensemble source used
        """
        cache_key = f"ensemble_{series_ticker}_{date.strftime('%Y-%m-%d')}"

        # Check cache first
        if cache_key in self.ensemble_cache:
            cached = self.ensemble_cache[cache_key]
            if (datetime.now() - cached['timestamp']).total_seconds() < self.cache_ttl:
                return cached

        all_ensemble_temps = []

        # Fetch GEFS and ECMWF ensembles in parallel (each has 15s timeout)
        with ThreadPoolExecutor(max_workers=2) as executor:
            gefs_future = executor.submit(self.get_forecast_gefs_ensemble, lat, lon, date, series_ticker)
            ecmwf_future = executor.submit(self.get_forecast_ecmwf_ensemble, lat, lon, date, series_ticker)

            try:
                gefs_results = gefs_future.result(timeout=20)
            except Exception as e:
                logger.debug(f"GEFS ensemble fetch failed: {e}")
                gefs_results = []

            try:
                ecmwf_results = ecmwf_future.result(timeout=20)
            except Exception as e:
                logger.debug(f"ECMWF ensemble fetch failed: {e}")
                ecmwf_results = []

        gefs_temps = [temp for temp, source, _ in gefs_results if 'member' in source]
        if gefs_temps:
            all_ensemble_temps.extend(gefs_temps)
            logger.debug(f"GEFS ensemble: {len(gefs_temps)} members, mean={np.mean(gefs_temps):.1f}°F, std={np.std(gefs_temps):.1f}°F")

        ecmwf_temps = [temp for temp, source, _ in ecmwf_results if 'member' in source]
        if ecmwf_temps:
            all_ensemble_temps.extend(ecmwf_temps)
            logger.debug(f"ECMWF ensemble: {len(ecmwf_temps)} members, mean={np.mean(ecmwf_temps):.1f}°F, std={np.std(ecmwf_temps):.1f}°F")

        if not all_ensemble_temps:
            return None

        result = {
            'mean': np.mean(all_ensemble_temps),
            'std': np.std(all_ensemble_temps),
            'min': np.min(all_ensemble_temps),
            'max': np.max(all_ensemble_temps),
            'n_members': len(all_ensemble_temps),
            'source': 'gefs+ecmwf' if (gefs_temps and ecmwf_temps) else ('gefs' if gefs_temps else 'ecmwf'),
            'timestamp': datetime.now(),
            'forecasts': all_ensemble_temps
        }

        # Cache the result
        self.ensemble_cache[cache_key] = result
        logger.debug(f"Ensemble spread for {series_ticker}: mean={result['mean']:.1f}°F, std={result['std']:.1f}°F ({result['n_members']} members)")

        return result

    def apply_bias_correction(self, temp: float, source: str, series_ticker: str, month: int) -> float:
        """
        Apply model-specific bias correction based on historical errors

        Args:
            temp: Raw forecast temperature
            source: Model/source name
            series_ticker: City ticker
            month: Target month (1-12)

        Returns:
            Bias-corrected temperature
        """
        city_base = extract_city_code(series_ticker)

        # Enforce minimum sample count before applying bias
        history = self.model_error_history[source][city_base][month]
        if len(history) < Config.MIN_SAMPLES_FOR_BIAS:
            return temp

        bias = self.model_bias[source][city_base][month]
        if bias != 0:
            # Cap bias to prevent catastrophic overcorrection
            max_bias = Config.MAX_BIAS_CORRECTION_F
            capped_bias = max(-max_bias, min(max_bias, bias))
            corrected = temp - capped_bias
            if abs(bias) > max_bias:
                logger.debug(f"Bias capped for {source}/{city_base}/month{month}: raw bias={bias:.1f}°F -> capped={capped_bias:.1f}°F")
            logger.debug(f"Bias correction for {source}/{city_base}/month{month}: {temp:.1f}°F -> {corrected:.1f}°F (bias={capped_bias:.1f}°F)")
            return corrected
        return temp

    def update_model_bias(self, source: str, series_ticker: str, target_date: datetime,
                         predicted_temp: float, actual_temp: float):
        """
        Update model-specific bias tracking after market settlement
        Call this to learn model-specific biases over time

        Args:
            source: Model/source name
            series_ticker: City ticker
            target_date: Date of the forecast
            predicted_temp: What the model predicted
            actual_temp: What actually happened
        """
        city_base = extract_city_code(series_ticker)
        month = target_date.month
        error = predicted_temp - actual_temp  # Positive = model ran hot

        # Store in history (keep last 50 per model/city/month)
        history = self.model_error_history[source][city_base][month]
        history.append((predicted_temp, actual_temp))
        if len(history) > 50:
            history.pop(0)

        # Update bias estimate (rolling mean of errors)
        errors = [p - a for p, a in history]
        new_bias = np.mean(errors) if errors else 0
        self.model_bias[source][city_base][month] = new_bias

        logger.debug(f"Updated bias for {source}/{city_base}/month{month}: {new_bias:.2f}°F (n={len(history)})")

    def detect_outliers(self, forecasts: List[float]) -> List[float]:
        """
        Detect and filter outliers using IQR method
        Returns list of valid forecasts with outliers removed
        """
        if len(forecasts) < 3:
            return forecasts  # Need at least 3 to detect outliers
        
        forecasts_array = np.array(forecasts)
        Q1, Q3 = np.percentile(forecasts_array, [25, 75])
        IQR = Q3 - Q1
        
        if IQR == 0:
            return forecasts  # All forecasts are the same
        
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        valid_forecasts = [f for f in forecasts if lower_bound <= f <= upper_bound]
        
        if len(valid_forecasts) < len(forecasts):
            outliers = [f for f in forecasts if f not in valid_forecasts]
            logger.warning(f"Detected {len(forecasts) - len(valid_forecasts)} outlier(s): {outliers}")
        
        return valid_forecasts if valid_forecasts else forecasts  # Keep all if filtering removes everything
    
    def get_enabled_sources(self) -> list:
        """Return list of enabled weather source names."""
        return self._enabled_sources

    def _get_nws_station_id(self, series_ticker: str) -> Optional[str]:
        """Resolve NWS observation station ID for a series ticker.
        Uses hardcoded CITY_STATIONS mapping (matches Kalshi CLI settlement) with
        dynamic API fallback. Cached permanently per session."""
        if series_ticker in self._nws_station_cache:
            return self._nws_station_cache[series_ticker]

        if series_ticker not in self.CITY_COORDS:
            return None

        # Use hardcoded station ID if available (matches Kalshi settlement)
        city_code = extract_city_code(series_ticker)
        if city_code in self.CITY_STATIONS:
            icao = self.CITY_STATIONS[city_code]
            station_url = f"https://api.weather.gov/stations/{icao}"
            self._nws_station_cache[series_ticker] = station_url
            logger.debug(f"Using hardcoded station {icao} for {series_ticker}")
            return station_url

        # Fallback: dynamic lookup for unknown cities
        city = self.CITY_COORDS[series_ticker]
        lat, lon = city['lat'], city['lon']

        try:
            points_url = f"https://api.weather.gov/points/{lat},{lon}"
            resp = requests.get(points_url, headers={'User-Agent': 'KalshiTradingBot/1.0'}, timeout=10)
            if resp.status_code != 200:
                logger.debug(f"NWS points API failed for {series_ticker}: {resp.status_code}")
                return None

            obs_stations_url = resp.json().get('properties', {}).get('observationStations')
            if not obs_stations_url:
                return None

            stations_resp = requests.get(obs_stations_url, headers={'User-Agent': 'KalshiTradingBot/1.0'}, timeout=10)
            if stations_resp.status_code != 200:
                return None

            features = stations_resp.json().get('features', [])
            if not features:
                return None

            station_id = features[0]['id']
            self._nws_station_cache[series_ticker] = station_id
            return station_id
        except Exception as e:
            logger.debug(f"Error resolving NWS station for {series_ticker}: {e}")
            return None

    def get_todays_observed_high(self, series_ticker: str) -> Optional[Tuple[float, datetime]]:
        """
        Get today's observed high temperature from NWS station observations.
        Returns (high_temp_f, timestamp) or None if unavailable.

        This is critical for avoiding trades on already-determined outcomes.
        Cached for 5 minutes (NWS updates ~hourly). Station ID cached permanently.
        """
        if series_ticker not in self.CITY_COORDS or series_ticker not in self.CITY_TIMEZONES:
            return None

        tz = ZoneInfo(self.CITY_TIMEZONES[series_ticker])
        today_local = datetime.now(tz).date()

        # Check observation cache (5min TTL, keyed by date to prevent cross-midnight contamination)
        cache_key = (series_ticker, 'high', str(today_local))
        if cache_key in self._nws_obs_cache:
            cached_result, cached_time = self._nws_obs_cache[cache_key]
            if (time.time() - cached_time) < self._nws_obs_cache_ttl:
                return cached_result

        try:
            station_id = self._get_nws_station_id(series_ticker)
            if not station_id:
                return None

            obs_url = f"{station_id}/observations"
            obs_resp = requests.get(obs_url, headers={'User-Agent': 'KalshiTradingBot/1.0'}, timeout=10)

            if obs_resp.status_code != 200:
                logger.debug(f"NWS observations API failed: {obs_resp.status_code}")
                return None

            observations = obs_resp.json().get('features', [])
            if not observations:
                logger.debug(f"No observations available for {series_ticker}")
                return None

            today_temps = []

            for obs in observations:
                props = obs.get('properties')
                if not props:
                    continue
                timestamp_str = props.get('timestamp')
                if not timestamp_str:
                    continue
                timestamp_utc = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                timestamp_local = timestamp_utc.astimezone(tz)
                if timestamp_local.date() != today_local:
                    continue
                temp_c = props.get('temperature', {}).get('value')
                if temp_c is None:
                    continue
                temp_f = (temp_c * 9/5) + 32
                today_temps.append((temp_f, timestamp_local))

            if not today_temps:
                logger.debug(f"No observations for today ({today_local}) found for {series_ticker}")
                self._nws_obs_cache[cache_key] = (None, time.time())
                return None

            max_temp, max_time = max(today_temps, key=lambda x: x[0])
            result = (max_temp, max_time)
            self._nws_obs_cache[cache_key] = (result, time.time())
            logger.debug(f"Today's observed high for {series_ticker}: {max_temp:.1f}°F (at {max_time.strftime('%H:%M %Z')})")
            return result

        except Exception as e:
            logger.debug(f"Error getting today's observed high for {series_ticker}: {e}")
            return None
    
    def get_observed_high_for_date(self, series_ticker: str, target_date) -> Optional[Tuple[float, datetime]]:
        """
        Get observed high temperature from NWS for a specific date (local time for that city).
        target_date: date or datetime. Returns (high_temp_f, timestamp) or None.
        """
        if series_ticker not in self.CITY_COORDS or series_ticker not in self.CITY_TIMEZONES:
            return None
        tz = ZoneInfo(self.CITY_TIMEZONES[series_ticker])
        target_local = target_date.date() if hasattr(target_date, 'date') else target_date
        try:
            station_id = self._get_nws_station_id(series_ticker)
            if not station_id:
                return None
            obs_url = f"{station_id}/observations"
            obs_resp = requests.get(obs_url, headers={'User-Agent': 'KalshiTradingBot/1.0'}, timeout=10)
            if obs_resp.status_code != 200:
                return None
            observations = obs_resp.json().get('features', [])
            temps = []
            for obs in observations:
                props = obs.get('properties', {})
                ts_str = props.get('timestamp')
                if not ts_str:
                    continue
                ts_utc = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                ts_local = ts_utc.astimezone(tz)
                if ts_local.date() != target_local:
                    continue
                temp_c = props.get('temperature', {}).get('value')
                if temp_c is None:
                    continue
                temp_f = (temp_c * 9/5) + 32
                temps.append((temp_f, ts_local))
            if not temps:
                return None
            max_temp, max_time = max(temps, key=lambda x: x[0])
            return (max_temp, max_time)
        except Exception as e:
            logger.debug(f"Error getting observed high for {series_ticker} on {target_local}: {e}")
            return None

    def get_observed_low_for_date(self, series_ticker: str, target_date) -> Optional[Tuple[float, datetime]]:
        """
        Get observed low temperature from NWS for a specific date (local time for that city).
        target_date: date or datetime. Returns (low_temp_f, timestamp) or None.
        """
        if series_ticker not in self.CITY_COORDS or series_ticker not in self.CITY_TIMEZONES:
            return None
        tz = ZoneInfo(self.CITY_TIMEZONES[series_ticker])
        target_local = target_date.date() if hasattr(target_date, 'date') else target_date
        try:
            station_id = self._get_nws_station_id(series_ticker)
            if not station_id:
                return None
            obs_url = f"{station_id}/observations"
            obs_resp = requests.get(obs_url, headers={'User-Agent': 'KalshiTradingBot/1.0'}, timeout=10)
            if obs_resp.status_code != 200:
                return None
            observations = obs_resp.json().get('features', [])
            temps = []
            for obs in observations:
                props = obs.get('properties', {})
                ts_str = props.get('timestamp')
                if not ts_str:
                    continue
                ts_utc = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                ts_local = ts_utc.astimezone(tz)
                if ts_local.date() != target_local:
                    continue
                temp_c = props.get('temperature', {}).get('value')
                if temp_c is None:
                    continue
                temp_f = (temp_c * 9/5) + 32
                temps.append((temp_f, ts_local))
            if not temps:
                return None
            min_temp, min_time = min(temps, key=lambda x: x[0])
            return (min_temp, min_time)
        except Exception as e:
            logger.debug(f"Error getting observed low for {series_ticker} on {target_local}: {e}")
            return None
    
    def get_todays_observed_low(self, series_ticker: str) -> Optional[Tuple[float, datetime]]:
        """
        Get today's observed low temperature from NWS station observations.
        Returns (low_temp_f, timestamp) or None if unavailable.

        Cached for 5 minutes (NWS updates ~hourly). Station ID cached permanently.
        """
        if series_ticker not in self.CITY_COORDS or series_ticker not in self.CITY_TIMEZONES:
            return None

        tz = ZoneInfo(self.CITY_TIMEZONES[series_ticker])
        today_local = datetime.now(tz).date()

        # Check observation cache (5min TTL, keyed by date to prevent cross-midnight contamination)
        cache_key = (series_ticker, 'low', str(today_local))
        if cache_key in self._nws_obs_cache:
            cached_result, cached_time = self._nws_obs_cache[cache_key]
            if (time.time() - cached_time) < self._nws_obs_cache_ttl:
                return cached_result

        try:
            station_id = self._get_nws_station_id(series_ticker)
            if not station_id:
                return None

            obs_url = f"{station_id}/observations"
            obs_resp = requests.get(obs_url, headers={'User-Agent': 'KalshiTradingBot/1.0'}, timeout=10)

            if obs_resp.status_code != 200:
                logger.debug(f"NWS observations API failed: {obs_resp.status_code}")
                return None

            observations = obs_resp.json().get('features', [])
            if not observations:
                logger.debug(f"No observations available for {series_ticker}")
                return None

            today_temps = []

            for obs in observations:
                props = obs.get('properties')
                if not props:
                    continue
                timestamp_str = props.get('timestamp')
                if not timestamp_str:
                    continue
                timestamp_utc = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                timestamp_local = timestamp_utc.astimezone(tz)
                if timestamp_local.date() != today_local:
                    continue
                temp_c = props.get('temperature', {}).get('value')
                if temp_c is None:
                    continue
                temp_f = (temp_c * 9/5) + 32
                today_temps.append((temp_f, timestamp_local))

            if not today_temps:
                logger.debug(f"No observations for today ({today_local}) found for {series_ticker}")
                self._nws_obs_cache[cache_key] = (None, time.time())
                return None

            min_temp, min_time = min(today_temps, key=lambda x: x[0])
            result = (min_temp, min_time)
            self._nws_obs_cache[cache_key] = (result, time.time())
            logger.debug(f"Today's observed low for {series_ticker}: {min_temp:.1f}°F (at {min_time.strftime('%H:%M %Z')})")
            return result

        except Exception as e:
            logger.debug(f"Error getting today's observed low for {series_ticker}: {e}")
            return None
    
    def is_likely_past_extreme_of_day(
        self,
        series_ticker: str,
        target_date: datetime,
        observed_extreme: Optional[float] = None,
        forecasted_extreme: Optional[float] = None,
    ) -> bool:
        """
        Return True if the extreme (high or low) of the day has likely already occurred.
        Used to skip longshot trades when uncertainty has collapsed.
        
        For HIGH markets: Longshot value is in the morning when the high hasn't happened yet;
        after ~4 PM local or when observed high ≈ forecasted high, skip longshots.
        
        For LOW markets: Low typically occurs early morning (4-7 AM). After ~8 AM local or
        when observed low ≈ forecasted low, skip longshots.
        """
        if series_ticker not in self.CITY_TIMEZONES:
            return False
        # Use city's local date, not system time — at midnight ET, western cities
        # are still on the previous day
        tz = ZoneInfo(self.CITY_TIMEZONES[series_ticker])
        local_today = datetime.now(tz).date()
        if target_date.date() != local_today:
            return False  # Not today in the city's timezone: extreme hasn't happened yet
        
        # Determine if this is a HIGH or LOW market
        is_high_market = series_ticker.startswith('KXHIGH')
        is_low_market = series_ticker.startswith('KXLOW')
        
        if not (is_high_market or is_low_market):
            return False
        
        try:
            tz = ZoneInfo(self.CITY_TIMEZONES[series_ticker])
            local_now = datetime.now(tz)
            local_hour = local_now.hour + local_now.minute / 60.0
            
            if is_high_market:
                # HIGH markets: cutoff after 4 PM local
                if local_hour >= self.LONGSHOT_HIGH_CUTOFF_HOUR:
                    logger.debug(f"Past high-of-day cutoff for {series_ticker}: local time {local_hour:.1f}h >= {self.LONGSHOT_HIGH_CUTOFF_HOUR}")
                    return True
                # Also check if observed high is close to forecasted high
                if observed_extreme is not None and forecasted_extreme is not None:
                    if observed_extreme >= forecasted_extreme - 2.0:
                        logger.debug(f"Observed high {observed_extreme:.1f}°F within 2°F of forecast {forecasted_extreme:.1f}°F for {series_ticker} — likely past high")
                        return True
            
            elif is_low_market:
                # LOW markets: cutoff after 8 AM local (low typically happens 4-7 AM)
                if local_hour >= self.LONGSHOT_LOW_CUTOFF_HOUR:
                    logger.debug(f"Past low-of-day cutoff for {series_ticker}: local time {local_hour:.1f}h >= {self.LONGSHOT_LOW_CUTOFF_HOUR}")
                    return True
                # Also check if observed low is close to forecasted low
                if observed_extreme is not None and forecasted_extreme is not None:
                    if observed_extreme <= forecasted_extreme + 2.0:
                        logger.debug(f"Observed low {observed_extreme:.1f}°F within 2°F of forecast {forecasted_extreme:.1f}°F for {series_ticker} — likely past low")
                        return True
            
            return False
        except Exception as e:
            logger.debug(f"Error in is_likely_past_extreme_of_day for {series_ticker}: {e}")
            return False
    
    def get_all_forecasts(self, series_ticker: str, target_date: datetime) -> List[float]:
        """
        Collect forecasts from all available sources with caching, parallel execution,
        outlier detection, source weighting, age weighting, and bias correction.

        Enhanced to include:
        - NWS (National Weather Service)
        - NWS MOS (Model Output Statistics - bias corrected)
        - Tomorrow.io
        - Open-Meteo (multi-model: GFS, ECMWF, ICON, GEM, JMA)
        - Pirate Weather (HRRR-based)
        - Visual Crossing
        - Weatherbit (fallback only)
        """
        if series_ticker not in self.CITY_COORDS:
            return []

        # Check cache first
        cache_key = f"{series_ticker}_{target_date.strftime('%Y-%m-%d')}"
        if cache_key in self.forecast_cache:
            cache_time = self.cache_timestamp.get(cache_key)
            if cache_time and (datetime.now() - cache_time).total_seconds() < self.cache_ttl:
                return self.forecast_cache[cache_key]

        city = self.CITY_COORDS[series_ticker]
        lat, lon = city['lat'], city['lon']

        # Log market type for debugging LOW vs HIGH
        is_low_market = 'LOW' in series_ticker
        market_type = "LOW (min temp)" if is_low_market else "HIGH (max temp)"
        logger.debug(f"Fetching {market_type} forecasts for {series_ticker} on {target_date.strftime('%Y-%m-%d')}")

        # Fetch forecasts in parallel for better performance
        forecast_data = []  # List of (temp, source, timestamp) tuples

        # Define all forecast sources to fetch in parallel
        # Sources are conditionally enabled via environment variables
        # NOAA-only mode: set ENABLE_OPEN_METEO=false, ENABLE_PIRATE_WEATHER=false, etc.

        with ThreadPoolExecutor(max_workers=8) as executor:
            tier1_futures = {}

            # NOAA sources (NWS and NWS MOS) - most reliable, matches Kalshi settlement
            if self.enable_nws:
                tier1_futures[executor.submit(
                    self.get_forecast_nws, lat, lon, target_date, series_ticker
                )] = 'nws'

            if self.enable_nws_mos:
                tier1_futures[executor.submit(
                    self.get_forecast_nws_mos, lat, lon, target_date, series_ticker
                )] = 'nws_mos'

            # Tomorrow.io (if enabled and API key available)
            if self.enable_tomorrowio and self.tomorrowio_api_key:
                tier1_futures[executor.submit(
                    self.get_forecast_tomorrowio, lat, lon, target_date, series_ticker
                )] = 'tomorrowio'

            # Open-Meteo models (if enabled)
            if self.enable_open_meteo:
                tier1_futures[executor.submit(
                    self.get_forecast_open_meteo, lat, lon, target_date, series_ticker, 'best_match'
                )] = 'open_meteo_best'
                tier1_futures[executor.submit(
                    self.get_forecast_open_meteo, lat, lon, target_date, series_ticker, 'gfs_seamless'
                )] = 'open_meteo_gfs'
                tier1_futures[executor.submit(
                    self.get_forecast_open_meteo, lat, lon, target_date, series_ticker, 'ecmwf_ifs025'
                )] = 'open_meteo_ecmwf'
                tier1_futures[executor.submit(
                    self.get_forecast_open_meteo, lat, lon, target_date, series_ticker, 'icon_seamless'
                )] = 'open_meteo_icon'
                tier1_futures[executor.submit(
                    self.get_forecast_open_meteo, lat, lon, target_date, series_ticker, 'gfs_hrrr'
                )] = 'open_meteo_hrrr'
                tier1_futures[executor.submit(
                    self.get_forecast_open_meteo, lat, lon, target_date, series_ticker, 'gem_seamless'
                )] = 'open_meteo_gem'
                tier1_futures[executor.submit(
                    self.get_forecast_open_meteo, lat, lon, target_date, series_ticker, 'ukmo_seamless'
                )] = 'open_meteo_ukmo'

            # Pirate Weather (if enabled and API key available)
            if self.enable_pirate_weather and self.pirate_weather_api_key:
                tier1_futures[executor.submit(
                    self.get_forecast_pirate_weather, lat, lon, target_date, series_ticker
                )] = 'pirate_weather'

            # Visual Crossing (if enabled and API key available)
            if self.enable_visual_crossing and self.visual_crossing_api_key:
                tier1_futures[executor.submit(
                    self.get_forecast_visual_crossing, lat, lon, target_date, series_ticker
                )] = 'visual_crossing'

            for future in as_completed(tier1_futures):
                try:
                    result = future.result()
                    if result is not None:
                        temp, source, timestamp = result
                        # Log the raw forecast for later analysis
                        self._log_source_forecast(series_ticker, target_date, source, temp)
                        # Store in ForecastTracker for accuracy-weighted means
                        try:
                            from .forecast_weighting import get_forecast_tracker
                            tracker = get_forecast_tracker()
                            city_code = extract_city_code(series_ticker)
                            tracker.store_forecast(city_code, target_date.strftime('%Y-%m-%d'), source, temp)
                        except Exception:
                            pass
                        # Apply bias correction (store raw temp for bias learning)
                        corrected_temp = self.apply_bias_correction(temp, source, series_ticker, target_date.month)
                        forecast_data.append((corrected_temp, source, timestamp, temp))
                        weight = self.source_weights.get(source, 0.8)
                        logger.debug(f"  {source}: {corrected_temp:.1f}°F (raw={temp:.1f}°F, weight={weight:.2f})")
                except Exception as e:
                    source = tier1_futures[future]
                    logger.debug(f"Error fetching from {source}: {e}")

        # Only use Weatherbit if we have very few forecasts (emergency fallback)
        # Weatherbit free tier: 50 requests/day - must be very conservative
        if len(forecast_data) < 2 and self.weatherbit_api_key:
            try:
                weatherbit_result = self.get_forecast_weatherbit(lat, lon, target_date, series_ticker)
                if weatherbit_result is not None:
                    temp, source, timestamp = weatherbit_result
                    self._log_source_forecast(series_ticker, target_date, source, temp)
                    try:
                        from .forecast_weighting import get_forecast_tracker
                        tracker = get_forecast_tracker()
                        city_code = extract_city_code(series_ticker)
                        tracker.store_forecast(city_code, target_date.strftime('%Y-%m-%d'), source, temp)
                    except Exception:
                        pass
                    corrected_temp = self.apply_bias_correction(temp, source, series_ticker, target_date.month)
                    forecast_data.append((corrected_temp, source, timestamp, temp))
                    logger.debug(f"Using Weatherbit fallback for {series_ticker}")
            except Exception as e:
                logger.debug(f"Error fetching from weatherbit (fallback): {e}")

        if not forecast_data:
            logger.warning(f"No forecasts available for {city['name']}, using fallback")
            return []

        # Log all sources that responded
        sources = [source for _, source, _, *_ in forecast_data]
        logger.debug(f"Collected {len(forecast_data)} forecasts from: {', '.join(sources)}")

        # Extract temperatures for outlier detection
        raw_forecasts = [temp for temp, _, _, *_ in forecast_data]

        # Detect and filter outliers
        valid_indices = []
        if len(raw_forecasts) >= 3:
            valid_forecasts = self.detect_outliers(raw_forecasts)
            valid_indices = [i for i, temp in enumerate(raw_forecasts) if temp in valid_forecasts]
        else:
            valid_indices = list(range(len(forecast_data)))

        # Apply source weighting and age weighting
        now = datetime.now()
        weighted_forecasts = []
        total_weight = 0.0

        for idx in valid_indices:
            temp, source, forecast_time = forecast_data[idx][0], forecast_data[idx][1], forecast_data[idx][2]

            # Source reliability weight
            source_weight = self.source_weights.get(source, 0.8)

            # Forecast age weight (exponential decay with 6-hour half-life)
            age_hours = (now - forecast_time).total_seconds() / 3600.0
            age_weight = np.exp(-age_hours / 6.0)  # 6-hour half-life

            # Combined weight
            combined_weight = source_weight * age_weight

            weighted_forecasts.append((temp, combined_weight, source))
            total_weight += combined_weight

        # Deduplicate correlated sources — Open-Meteo models sharing upstream
        # data (e.g. best_match ≈ gfs_seamless) inflate source count without
        # adding independent information.  Keep the higher-weighted duplicate.
        OPEN_METEO_PREFIX = 'open_meteo_'
        deduped = []
        seen_temps = []  # (temp, weight, source) of already-kept Open-Meteo entries
        for temp, weight, source in weighted_forecasts:
            if source.startswith(OPEN_METEO_PREFIX):
                # Check if another Open-Meteo source already has a near-identical temp
                is_dup = False
                for i, (st, sw, ss) in enumerate(seen_temps):
                    if abs(temp - st) < 0.3:  # Within 0.3°F = effectively same model output
                        is_dup = True
                        if weight > sw:
                            # Replace with higher-weighted duplicate
                            seen_temps[i] = (temp, weight, source)
                            deduped = [(t, w, s) if s != ss else (temp, weight, source)
                                       for t, w, s in deduped]
                        break
                if not is_dup:
                    seen_temps.append((temp, weight, source))
                    deduped.append((temp, weight, source))
            else:
                deduped.append((temp, weight, source))

        if len(deduped) < len(weighted_forecasts):
            removed = len(weighted_forecasts) - len(deduped)
            logger.debug(f"Deduped {removed} correlated Open-Meteo source(s) for {series_ticker}")
        weighted_forecasts = deduped
        total_weight = sum(w for _, w, _ in weighted_forecasts)

        # Calculate weighted average
        if total_weight > 0:
            weighted_mean = sum(temp * weight for temp, weight, _ in weighted_forecasts) / total_weight

            # Try accuracy-weighted mean from ForecastTracker (uses historical RMSE)
            try:
                from .forecast_weighting import get_forecast_tracker
                tracker = get_forecast_tracker()
                city_code = extract_city_code(series_ticker)
                source_dict = {source: temp for temp, _, source in weighted_forecasts}
                tracker_mean, tracker_weights = tracker.get_weighted_forecast(source_dict, city=city_code)
                if tracker_mean is not None and tracker_weights:
                    logger.debug(f"📊 Accuracy-weighted mean: {tracker_mean:.1f}°F (vs static: {weighted_mean:.1f}°F)")
                    weighted_mean = tracker_mean
            except Exception:
                pass

            # Return raw bias-corrected forecasts — do NOT blend toward the mean.
            # The weighted mean is used for the distribution center, but individual
            # forecasts must retain their original spread so np.std() reflects
            # actual forecast disagreement (not artificially compressed values).
            adjusted_forecasts = [temp for temp, weight, source in weighted_forecasts]

            # Store metadata for later use (include source names for num_sources)
            self.forecast_metadata[cache_key] = forecast_data
            # Store accuracy-weighted mean for use in build_probability_distribution
            self.forecast_metadata[cache_key + '_weighted_mean'] = weighted_mean

            # Cache the adjusted forecasts
            self.forecast_cache[cache_key] = adjusted_forecasts
            self.cache_timestamp[cache_key] = datetime.now()

            # Log summary
            logger.debug(f"Forecast for {series_ticker} ({target_date.strftime('%Y-%m-%d')}): "
                        f"mean={weighted_mean:.1f}°F, range=[{min(raw_forecasts):.1f}, {max(raw_forecasts):.1f}]°F, "
                        f"sources={len(forecast_data)}")

            return adjusted_forecasts

        return []
    
    def get_historical_forecast_error(self, series_ticker: str, month: int) -> float:
        """
        Get historical forecast error (std) for a city and month
        Returns default value if no history available
        """
        if series_ticker in self.forecast_error_history:
            month_errors = self.forecast_error_history[series_ticker].get(month, [])
            if month_errors:
                return np.mean(month_errors)
        # Default forecast error: 3.5°F (matches real NWS MAE of ~2.5-3.5°F)
        return 3.5
    
    def build_probability_distribution(self, forecasts: List[float],
                                     temperature_ranges: List[Tuple[float, float]],
                                     series_ticker: str = '',
                                     target_date: Optional[datetime] = None,
                                     is_range_market: bool = False) -> Dict[Tuple[float, float], float]:
        """
        Build probability distribution over temperature ranges from forecasts
        Uses ensemble-based uncertainty when available, falling back to synthetic estimates

        Enhanced to use GEFS/ECMWF ensemble spread for real uncertainty quantification
        instead of synthetic time-based estimates.

        Args:
            forecasts: List of temperature forecasts from different sources
            temperature_ranges: List of (min, max) temperature range tuples
            series_ticker: City ticker for historical error lookup
            target_date: Target date for time-based uncertainty adjustment

        Returns:
            Dictionary mapping (min, max) ranges to probabilities
        """
        if not forecasts:
            return {}

        # Calculate mean and std of forecasts
        # Prefer accuracy-weighted mean from get_all_forecasts() if available
        wm_key = f"{series_ticker}_{target_date.strftime('%Y-%m-%d')}_weighted_mean" if series_ticker and target_date else None
        if wm_key and self.forecast_metadata.get(wm_key) is not None:
            mean_temp = self.forecast_metadata[wm_key]
        else:
            mean_temp = np.mean(forecasts)

        # Blend ML prediction into mean if enabled and trained
        if Config.ML_ENABLED and series_ticker and target_date:
            try:
                from .ml_predictor import get_ml_predictor
                ml = get_ml_predictor()
                city_code = extract_city_code(series_ticker)
                is_high = series_ticker.startswith('KXHIGH')
                hours_until = max(0, (target_date - datetime.now()).total_seconds() / 3600.0)
                source_temps = {'aggregate_mean': float(mean_temp)}
                ml_pred = ml.predict(source_temps, city_code, target_date.month, is_high, hours_until)
                if ml_pred is not None:
                    stat_mean = mean_temp
                    blend_w = Config.ML_BLEND_WEIGHT
                    mean_temp = (1 - blend_w) * stat_mean + blend_w * ml_pred
                    logger.debug(f"ML blend: stat={stat_mean:.1f}, ml={ml_pred:.1f}, blended={mean_temp:.1f}")
            except Exception:
                pass

        # Try to get ensemble-based uncertainty (GEFS + ECMWF)
        ensemble_std = None
        if series_ticker and target_date and series_ticker in self.CITY_COORDS:
            city = self.CITY_COORDS[series_ticker]
            lat, lon = city['lat'], city['lon']
            ensemble_data = self.get_ensemble_spread(lat, lon, target_date, series_ticker)
            if ensemble_data and ensemble_data.get('n_members', 0) >= 10:
                # Use ensemble standard deviation as primary uncertainty measure
                ensemble_std = ensemble_data['std']
                # Also use ensemble mean if it's close to our multi-source mean
                ensemble_mean = ensemble_data['mean']
                if abs(ensemble_mean - mean_temp) < 3.0:  # Within 3°F
                    # Blend means (60% multi-source, 40% ensemble)
                    mean_temp = 0.6 * mean_temp + 0.4 * ensemble_mean
                logger.debug(f"  Ensemble: std={ensemble_std:.1f}°F ({ensemble_data['n_members']} members from {ensemble_data['source']})")

        # Dynamic standard deviation calculation
        if ensemble_std is not None:
            # Ensemble-based uncertainty (preferred)
            std_temp = ensemble_std

            # Blend with multi-source spread if available
            if len(forecasts) > 1:
                source_std = np.std(forecasts)
                # Weight ensemble std higher (70%) but incorporate source spread (30%)
                std_temp = 0.7 * ensemble_std + 0.3 * source_std

            # Add small time-based uncertainty for longer horizons
            if target_date:
                days_until = max(0, (target_date - datetime.now()).days)
                # Smaller time penalty when we have ensemble data
                time_uncertainty = days_until * 0.2  # 0.2°F per day
                std_temp = np.sqrt(std_temp**2 + time_uncertainty**2)

        elif len(forecasts) > 1:
            # Fallback: Use actual std from forecast spread (synthetic uncertainty)
            std_temp = np.std(forecasts)

            # Add base uncertainty based on forecast horizon
            if target_date:
                total_hours = max(0, (target_date - datetime.now()).total_seconds() / 3600.0)
                # Base uncertainty increases with time: +0.5°F per 24h (linear)
                base_uncertainty = 1.0 + (total_hours * 0.5 / 24.0)
                std_temp = max(std_temp, base_uncertainty)

            # Incorporate historical forecast error if available
            if series_ticker and target_date:
                historical_error = self.get_historical_forecast_error(series_ticker, target_date.month)
                # Blend actual std with historical error (weighted average)
                std_temp = 0.5 * std_temp + 0.5 * historical_error
        else:
            # Only one forecast - use historical error or default
            if series_ticker and target_date:
                std_temp = self.get_historical_forecast_error(series_ticker, target_date.month)
            else:
                std_temp = 3.5  # Default std — matches real NWS MAE of ~2.5-3.5°F

        # Ensure minimum std for stability
        # Real forecast uncertainty is typically 2-4°F even for next-day forecasts
        if is_range_market:
            # Range markets need wider distribution — 2°F bin with tight std gives unrealistic probs
            min_std = getattr(Config, 'RANGE_MIN_STD_FLOOR', 3.0)
        elif Config.CITY_SEASON_STD_ENABLED and series_ticker and target_date:
            # Per-city, per-season floor from historical error tracking
            try:
                from .city_error_tracker import get_city_error_tracker
                city_code = extract_city_code(series_ticker)
                min_std = get_city_error_tracker().get_min_std(city_code, target_date.month)
            except Exception:
                min_std = max(2.5, self.get_historical_forecast_error(series_ticker, target_date.month))
        else:
            # City-specific floor from actual forecast track record
            if series_ticker and target_date:
                historical_min = self.get_historical_forecast_error(series_ticker, target_date.month)
            else:
                historical_min = 3.5
            # Never go below 2.5°F even with ensemble (NWS MAE for next-day is ~2.5°F)
            min_std = max(2.5, historical_min)
        std_temp = max(std_temp, min_std)

        # Log the uncertainty source and value
        uncertainty_source = 'ensemble' if ensemble_std is not None else 'synthetic'
        logger.debug(f"Probability distribution for {series_ticker}: mean={mean_temp:.1f}°F, "
                    f"std={std_temp:.2f}°F (source: {uncertainty_source})")

        # Build probability distribution using normal distribution
        # This models uncertainty around the mean forecast
        distribution = {}
        total_prob = 0

        for temp_min, temp_max in temperature_ranges:
            # Probability that temperature falls in this range
            # Using cumulative distribution function
            prob = stats.norm.cdf(temp_max, mean_temp, std_temp) - stats.norm.cdf(temp_min, mean_temp, std_temp)
            distribution[(temp_min, temp_max)] = max(0, prob)  # Ensure non-negative
            total_prob += prob

        # Normalize probabilities to sum to 1
        if total_prob > 0:
            for key in distribution:
                distribution[key] /= total_prob

        return distribution
    
    def update_forecast_error(self, series_ticker: str, target_date: datetime, actual_temp: float, predicted_temp: float):
        """
        Update historical forecast error tracking
        Call this after market settles to learn from accuracy
        """
        error = abs(actual_temp - predicted_temp)
        month = target_date.month

        # Store error in history (keep last 100 errors per city/month)
        errors = self.forecast_error_history[series_ticker][month]
        errors.append(error)
        if len(errors) > 100:
            errors.pop(0)  # Keep only most recent 100

        logger.debug(f"📊 Updated forecast error for {series_ticker} (month {month}): {error:.2f}°F")

    def update_all_model_biases(self, series_ticker: str, target_date: datetime, actual_temp: float):
        """
        Update bias tracking for all models that contributed to a forecast
        Call this after market settles with the actual observed temperature

        This looks up the cached forecast metadata to find which sources
        contributed and updates their individual bias estimates.
        """
        cache_key = f"{series_ticker}_{target_date.strftime('%Y-%m-%d')}"

        if cache_key not in self.forecast_metadata:
            logger.debug(f"No forecast metadata found for {cache_key}, skipping bias update")
            return

        forecast_data = self.forecast_metadata[cache_key]
        updated_sources = []

        for entry in forecast_data:
            # Use raw (uncorrected) temp for bias learning to avoid feedback loop
            raw_temp = entry[3] if len(entry) > 3 else entry[0]
            source = entry[1]
            self.update_model_bias(source, series_ticker, target_date, raw_temp, actual_temp)
            updated_sources.append(source)

        logger.debug(f"📊 Updated bias for {len(updated_sources)} models: {', '.join(updated_sources)}")

        # Save learned state after updating biases
        self._save_learned_state()

    def _save_learned_state(self):
        """
        Save learned state (model biases, forecast errors) to JSON for persistence across restarts.
        Called automatically after update_all_model_biases().
        """
        try:
            if not getattr(Config, 'PERSIST_LEARNING', True):
                return

            state = {
                'model_bias': {},
                'forecast_errors': {},
                'model_error_history': {},
                'saved_at': datetime.now().isoformat()
            }

            # Convert nested defaultdicts to regular dicts
            for source, city_data in self.model_bias.items():
                state['model_bias'][source] = {}
                for city, month_data in city_data.items():
                    state['model_bias'][source][city] = dict(month_data)

            for ticker, month_data in self.forecast_error_history.items():
                state['forecast_errors'][ticker] = dict(month_data)

            # Save model error history (for bias calculation)
            for source, ticker_data in self.model_error_history.items():
                state['model_error_history'][source] = {}
                for ticker, month_data in ticker_data.items():
                    state['model_error_history'][source][ticker] = {}
                    for month, history in month_data.items():
                        # Keep only last 20 entries per month to limit file size
                        state['model_error_history'][source][ticker][str(month)] = history[-20:]

            state_file = Path('data/learned_state.json')
            state_file.parent.mkdir(exist_ok=True)

            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)

            logger.debug(f"Saved learned state to {state_file}")

        except Exception as e:
            logger.warning(f"Could not save learned state: {e}")

    def _load_learned_state(self):
        """
        Load learned state from JSON on initialization.
        Restores model biases and forecast error history from previous sessions.
        """
        try:
            if not getattr(Config, 'PERSIST_LEARNING', True):
                logger.info("Learning persistence disabled, starting fresh")
                return

            state_file = Path('data/learned_state.json')
            if not state_file.exists():
                logger.info("No learned state file found, starting fresh")
                return

            with open(state_file, 'r') as f:
                state = json.load(f)

            # Restore model biases
            for source, city_data in state.get('model_bias', {}).items():
                for city, month_data in city_data.items():
                    for month, bias in month_data.items():
                        self.model_bias[source][city][int(month)] = bias

            # Restore forecast error history
            for ticker, month_data in state.get('forecast_errors', {}).items():
                for month, errors in month_data.items():
                    self.forecast_error_history[ticker][int(month)] = errors

            # Restore model error history
            for source, ticker_data in state.get('model_error_history', {}).items():
                for ticker, month_data in ticker_data.items():
                    for month, history in month_data.items():
                        # History is list of [predicted, actual] pairs
                        self.model_error_history[source][ticker][int(month)] = [
                            tuple(pair) for pair in history
                        ]

            saved_at = state.get('saved_at', 'unknown')
            bias_count = sum(
                sum(len(m) for m in c.values())
                for c in state.get('model_bias', {}).values()
            )
            logger.info(f"📂 Loaded learned state (saved at {saved_at}): {bias_count} bias corrections")

        except Exception as e:
            logger.warning(f"Could not load learned state: {e}")

    def is_source_reliable(self, source: str, city: str, min_samples: int = 10) -> bool:
        """
        Check if a forecast source has acceptable RMSE for this city.

        Uses historical prediction vs actual data to calculate RMSE.
        If RMSE exceeds MAX_SOURCE_RMSE, the source is considered unreliable.

        Args:
            source: Model/source name (e.g., 'nws', 'open_meteo_gfs')
            city: City code (e.g., 'NY', 'CHI')
            min_samples: Minimum samples required for evaluation

        Returns:
            True if source is reliable (or insufficient data), False if unreliable
        """
        try:
            max_rmse = getattr(Config, 'MAX_SOURCE_RMSE', 4.0)

            # Check all months for this source/city
            total_samples = 0
            sum_squared_errors = 0.0

            for month in range(1, 13):
                history = self.model_error_history[source][city].get(month, [])
                for predicted, actual in history:
                    error = predicted - actual
                    sum_squared_errors += error ** 2
                    total_samples += 1

            if total_samples < min_samples:
                return True  # Not enough data, trust the source

            rmse = np.sqrt(sum_squared_errors / total_samples)

            if rmse > max_rmse:
                logger.debug(f"Source {source} unreliable for {city}: RMSE={rmse:.2f}°F > {max_rmse}°F")
                return False

            return True

        except Exception as e:
            logger.debug(f"Error checking source reliability: {e}")
            return True  # Default to trusting the source

    def get_market_probability(self, market: Dict, threshold: float,
                              probability_dist: Dict[Tuple[float, float], float]) -> float:
        """
        Calculate probability that temperature will be above/below threshold
        based on the probability distribution
        
        Args:
            market: Market data from Kalshi
            threshold: Temperature threshold for the market
            probability_dist: Probability distribution over temperature ranges
        
        Returns:
            Probability (0-1) that the condition is true
        """
        # Parse market title to extract threshold
        # Kalshi weather markets typically have format like "Above 75°F" or "Below 70°F"
        market_title = market.get('title', '').lower()
        
        # Determine if we're looking for "above" or "below"
        is_above = 'above' in market_title or '>' in market_title
        is_below = 'below' in market_title or '<' in market_title
        
        if not (is_above or is_below):
            # If we can't determine, use threshold from parameter
            is_above = True  # Default assumption
        
        # Sum probabilities for ranges that satisfy the condition
        total_prob = 0.0
        for (temp_min, temp_max), prob in probability_dist.items():
            if is_above:
                # For "above threshold", count ranges where min >= threshold
                if temp_min >= threshold:
                    total_prob += prob
                elif temp_max > threshold:
                    # Partial overlap - add proportional probability
                    if temp_max > temp_min:
                        overlap = (temp_max - threshold) / (temp_max - temp_min)
                        total_prob += prob * overlap
                    else:
                        # Zero-width bin at threshold boundary — assign half probability
                        total_prob += prob * 0.5
            else:
                # For "below threshold", count ranges where max <= threshold
                if temp_max <= threshold:
                    total_prob += prob
                elif temp_min < threshold:
                    # Partial overlap
                    if temp_max > temp_min:
                        overlap = (threshold - temp_min) / (temp_max - temp_min)
                        total_prob += prob * overlap
                    else:
                        # Zero-width bin at threshold boundary — assign half probability
                        total_prob += prob * 0.5
        
        return total_prob
    
    def calculate_edge(self, our_probability: float, market_price_cents: int) -> float:
        """
        Calculate edge: (Our Probability - Market Price) × 100
        
        Args:
            our_probability: Our calculated probability (0-1)
            market_price_cents: Market price in cents (0-100)
        
        Returns:
            Edge percentage (positive = edge, negative = no edge)
        """
        market_probability = market_price_cents / 100.0
        edge = (our_probability - market_probability) * 100
        return edge
    
    def calculate_ev(self, win_prob: float, payout: float, loss_prob: float, stake: float, 
                     include_fees: bool = True, fee_rate: float = 0.05) -> float:
        """
        Calculate Expected Value with optional transaction fees
        
        Args:
            win_prob: Probability of winning (0-1)
            payout: Payout if we win (in dollars)
            loss_prob: Probability of losing (0-1)
            stake: Amount staked (in dollars)
            include_fees: Whether to include Kalshi fees (5% on winnings)
            fee_rate: Fee rate (default 0.05 = 5%)
        
        Returns:
            Expected value in dollars
        """
        if include_fees:
            # Kalshi fees: ~5% on winning trades, ~0% on losing trades
            # If we win: payout - stake - (payout * fee_rate)
            # If we lose: -stake (no fee on losses)
            ev = (win_prob * (payout - stake - payout * fee_rate)) - (loss_prob * stake)
        else:
            # Original formula without fees
            ev = (win_prob * payout) - (loss_prob * stake)
        return ev
    
    def calculate_confidence_interval(self, forecasts: List[float], threshold: float,
                                    n_samples: int = 1000, is_above: bool = True,
                                    min_std: float = 2.0) -> Tuple[float, Tuple[float, float]]:
        """
        Calculate probability with confidence interval using bootstrap sampling

        Args:
            forecasts: List of temperature forecasts
            threshold: Temperature threshold
            n_samples: Number of bootstrap samples
            is_above: True for "above threshold", False for "below threshold"
            min_std: Minimum standard deviation floor (matches no-ensemble uncertainty floor)

        Returns:
            (mean_probability, (ci_lower, ci_upper)) where CI is 95% confidence interval
        """
        if not forecasts or len(forecasts) < 2:
            return 0.5, (0.0, 1.0)  # No confidence with insufficient data
        
        probs = []
        mean_forecast = np.mean(forecasts)
        std_forecast = max(np.std(forecasts), min_std) if len(forecasts) > 1 else min_std

        for _ in range(n_samples):
            # Resample forecasts with replacement
            sample = np.random.choice(forecasts, size=len(forecasts), replace=True)
            sample_mean = np.mean(sample)
            sample_std = max(np.std(sample), min_std) if len(sample) > 1 else std_forecast

            # Calculate probability for this sample
            if is_above:
                # Probability that temp > threshold
                prob = 1.0 - stats.norm.cdf(threshold, sample_mean, sample_std)
            else:
                # Probability that temp < threshold
                prob = stats.norm.cdf(threshold, sample_mean, sample_std)
            # Cap: no weather forecast is 100% or 0% certain
            prob = max(0.01, min(0.99, prob))
            probs.append(prob)
        
        # Calculate mean and 95% confidence interval
        mean_prob = np.mean(probs)
        ci_lower = np.percentile(probs, 2.5)
        ci_upper = np.percentile(probs, 97.5)
        
        return mean_prob, (ci_lower, ci_upper)
    
    def estimate_fill_price(self, orderbook: Dict, side: str, quantity: int) -> float:
        """
        Estimate average fill price for given quantity based on orderbook depth
        
        Args:
            orderbook: Orderbook data from Kalshi
            side: 'yes' or 'no'
            quantity: Number of contracts to fill
        
        Returns:
            Estimated average fill price in cents
        
        Note: Kalshi orderbook arrays are sorted ASCENDING (lowest to highest).
        To buy, we need to pay the ASK price, which is calculated as:
        - YES ask = 100 - NO bid (highest NO bid)
        - NO ask = 100 - YES bid (highest YES bid)
        """
        # Get opposite side to calculate ask price
        opposite_side = 'no' if side == 'yes' else 'yes'
        opposite_orders = orderbook.get('orderbook', {}).get(opposite_side, [])
        
        if not opposite_orders:
            # Fallback: use market price
            return 50  # Default to 50¢ if no orderbook data
        
        # Best ask = 100 - best opposite bid
        # Arrays are ascending, so best bid (highest) is last element [-1]
        best_opposite_bid = opposite_orders[-1][0]  # Highest bid
        best_ask = 100 - best_opposite_bid
        
        # For small quantities, we'll likely fill at best ask
        # For larger quantities, estimate slippage based on orderbook depth
        if quantity <= 5:
            return best_ask
        
        # Estimate slippage: check if there's enough depth at best ask
        same_side_orders = orderbook.get('orderbook', {}).get(side, [])
        if not same_side_orders:
            return best_ask
        
        # Calculate total available at best ask and nearby prices
        # Since we're buying, we need to pay ask prices (calculated from opposite bids)
        # For simplicity, assume we fill at best ask for small orders
        # For larger orders, add small slippage estimate
        slippage_estimate = max(0, (quantity - 5) * 0.1)  # 0.1¢ per contract beyond 5
        estimated_price = min(best_ask + slippage_estimate, 100)
        
        return estimated_price
    
    def kelly_fraction(self, win_prob: float, payout_ratio: float, fractional: float = 0.5) -> float:
        """
        Calculate Kelly Criterion fraction for optimal position sizing
        
        Args:
            win_prob: Probability of winning (0-1)
            payout_ratio: Payout / Stake ratio
            fractional: Fraction of full Kelly to use (0.5 = half Kelly, safer)
        
        Returns:
            Fraction of bankroll to bet (0-1), capped at 25% for safety
        """
        if payout_ratio <= 0:
            return 0.0
        
        loss_prob = 1.0 - win_prob
        # Kelly formula: f = (p * b - q) / b
        # where p = win_prob, q = loss_prob, b = payout_ratio
        full_kelly = (win_prob * payout_ratio - loss_prob) / payout_ratio
        
        # Use fractional Kelly and cap at 25% of bankroll for safety
        fractional_kelly = fractional * max(0, full_kelly)
        return min(fractional_kelly, 0.25)  # Cap at 25%
    
    def calculate_confidence_score(self, edge: float, ci_width: float, num_forecasts: int, 
                                   ev: float, is_longshot: bool = False) -> float:
        """
        Calculate a confidence score (0-1) for position sizing.
        Higher score = higher confidence = larger position.
        
        Args:
            edge: Edge percentage (e.g., 15.0 for 15%)
            ci_width: Width of confidence interval (e.g., 0.2 for 20% width)
            num_forecasts: Number of forecast sources agreeing
            ev: Expected value in dollars
            is_longshot: Whether this is a longshot trade
            
        Returns:
            Confidence score between 0 and 1
        """
        # Start with base confidence from edge (normalized to 0-1)
        # Edge of 30% = 0.6 confidence, 60% = 1.0
        edge_score = min(1.0, edge / 50.0)
        
        # CI width penalty: narrower CI = higher confidence
        # CI width of 0.1 = 1.0, 0.4 = 0.5
        ci_score = max(0.2, 1.0 - (ci_width * 2.0))
        
        # Number of forecasts: more sources = higher confidence
        # 1 source = 0.5, 2 = 0.7, 3+ = 1.0
        forecast_score = min(1.0, 0.3 + (num_forecasts * 0.2))
        
        # EV contribution: higher EV = higher confidence
        # $0.50+ EV = 1.0, $0.01 = 0.2
        ev_score = min(1.0, 0.2 + (ev * 1.6))
        
        # Combine scores with weights
        if is_longshot:
            # Longshots: emphasize edge and EV more (riskier, need strong signals)
            confidence = (edge_score * 0.4) + (ci_score * 0.2) + (forecast_score * 0.2) + (ev_score * 0.2)
        else:
            # Conservative: balanced weights
            confidence = (edge_score * 0.3) + (ci_score * 0.3) + (forecast_score * 0.2) + (ev_score * 0.2)
        
        return min(1.0, max(0.1, confidence))  # Clamp between 0.1 and 1.0


# Helper function to extract temperature threshold from market title
def extract_threshold_from_market(market: Dict) -> Optional[Union[float, Tuple[float, float]]]:
    """
    Extract temperature threshold from Kalshi market title.
    Returns:
        - float: single threshold for "above X°" / "below X°" markets
        - (low, high): tuple for "be X-Y°" range markets (e.g. 71-72°)
    """
    title = market.get('title', '')
    # Strip markdown bold so "**high temp in LA**" doesn't break number matching
    title_clean = re.sub(r'\*\*[^*]*\*\*', '', title)

    # Try range format first: "71-72°" or "be 71-72°"
    match = RANGE_TEMP_PATTERN.search(title_clean)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low <= high:
            return (float(low), float(high))

    # Try single number followed by °F or F
    match = TEMP_PATTERN.search(title_clean)
    if match:
        return float(match.group(1))

    # Try "above X" or "below X"
    match = THRESHOLD_PATTERN.search(title_clean)
    if match:
        return float(match.group(1))

    return None
