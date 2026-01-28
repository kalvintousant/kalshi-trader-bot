"""
Weather Data Aggregator - Multi-source forecast collection and probability distribution
Based on the weather trading edge strategy guide
"""
import os
import re
import requests
import logging
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from scipy import stats
from dotenv import load_dotenv

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
    }
    
    def __init__(self):
        # API keys from environment (optional - will use free tiers where possible)
        # OpenWeather removed per user request
        self.tomorrowio_api_key = os.getenv('TOMORROWIO_API_KEY', '')
        self.accuweather_api_key = os.getenv('ACCUWEATHER_API_KEY', '')
        self.weatherbit_api_key = os.getenv('WEATHERBIT_API_KEY', '')
        
        # Cache for forecasts (from Config)
        # Based on AUSHIGH contract rules: daily markets, forecasts update 2-4x/day
        # Cache TTL balances freshness with API rate limits
        self.forecast_cache = {}
        self.cache_timestamp = {}
        from .config import Config
        self.cache_ttl = Config.FORECAST_CACHE_TTL
        
        # Forecast metadata cache (stores source and timestamp for each forecast)
        self.forecast_metadata = {}  # {cache_key: [(temp, source, timestamp), ...]}
        
        # Source reliability weights (based on historical accuracy)
        # NWS is most reliable (government source), others slightly lower
        self.source_weights = {
            'nws': 1.0,        # Most reliable (government source)
            'tomorrowio': 0.9, # Very reliable
            'weatherbit': 0.8  # Good but less reliable
        }
        
        # Historical forecast error tracking
        # Format: {series_ticker: {month: [errors...]}}
        self.forecast_error_history = defaultdict(lambda: defaultdict(list))
        
        # Use session for connection pooling
        self.session = requests.Session()
    
    def get_forecast_tomorrowio(self, lat: float, lon: float, date: datetime) -> Optional[Tuple[float, str, datetime]]:
        """Get forecast from Tomorrow.io API - returns (temp, source, timestamp)"""
        if not self.tomorrowio_api_key:
            return None
        
        try:
            url = f"https://api.tomorrow.io/v4/timelines"
            params = {
                'location': f"{lat},{lon}",
                'fields': 'temperatureMax',
                'timesteps': 'daily',
                'apikey': self.tomorrowio_api_key
            }
            response = self.session.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                # Parse response for target date
                target_date_str = date.strftime('%Y-%m-%d')
                for timeline in data.get('data', {}).get('timelines', []):
                    for point in timeline.get('intervals', []):
                        point_date = point['startTime'][:10]
                        if point_date == target_date_str:
                            temp = point['values'].get('temperatureMax')
                            if temp is not None:
                                # Return temp, source, and current timestamp
                                return (temp, 'tomorrowio', datetime.now())
        except Exception as e:
            logger.debug(f"Tomorrow.io API error: {e}")
        return None
    
    def get_forecast_nws(self, lat: float, lon: float, date: datetime) -> Optional[Tuple[float, str, datetime]]:
        """Get forecast from National Weather Service (free, no API key needed) - returns (temp, source, timestamp)"""
        try:
            # NWS requires grid coordinates first
            grid_url = f"https://api.weather.gov/points/{lat},{lon}"
            response = self.session.get(grid_url, timeout=5, headers={'User-Agent': 'KalshiBot/1.0'})
            if response.status_code == 200:
                grid_data = response.json()
                forecast_url = grid_data['properties']['forecast']
                forecast_response = self.session.get(forecast_url, timeout=5, headers={'User-Agent': 'KalshiBot/1.0'})
                if forecast_response.status_code == 200:
                    forecast_data = forecast_response.json()
                    target_date_str = date.strftime('%Y-%m-%d')
                    for period in forecast_data.get('properties', {}).get('periods', []):
                        period_date = datetime.fromisoformat(period['startTime'].replace('Z', '+00:00')).date()
                        if period_date == date.date() and period['isDaytime']:
                            # Extract max temp from forecast text or use temp
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
    
    def get_all_forecasts(self, series_ticker: str, target_date: datetime) -> List[float]:
        """
        Collect forecasts from all available sources with caching, parallel execution,
        outlier detection, source weighting, and age weighting
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
        
        # Fetch forecasts in parallel for better performance
        # Using NWS, Tomorrow.io, and Weatherbit (OpenWeather removed)
        # Weatherbit is used as fallback only to stay within free tier (50 requests/day)
        forecast_data = []  # List of (temp, source, timestamp) tuples
        
        # First, try NWS and Tomorrow.io (both have higher free tier limits)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self.get_forecast_nws, lat, lon, target_date): 'nws',
                executor.submit(self.get_forecast_tomorrowio, lat, lon, target_date): 'tomorrowio'
            }
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result is not None:
                        forecast_data.append(result)
                except Exception as e:
                    source = futures[future]
                    print(f"[Weather] Error fetching from {source}: {e}")
        
        # Only use Weatherbit if we have ZERO forecasts (emergency fallback only)
        # This keeps Weatherbit usage minimal to stay within 50 requests/day free tier
        # Weatherbit free tier: 50 requests/day - must be very conservative
        if len(forecast_data) == 0 and self.weatherbit_api_key:
            try:
                weatherbit_result = self.get_forecast_weatherbit(lat, lon, target_date, series_ticker)
                if weatherbit_result is not None:
                    forecast_data.append(weatherbit_result)
                    logger.info(f"Using Weatherbit fallback for {series_ticker} (NWS/Tomorrow.io unavailable)")
            except Exception as e:
                logger.debug(f"Error fetching from weatherbit (fallback): {e}")
        
        if not forecast_data:
            logger.warning(f"No forecasts available for {city['name']}, using fallback")
            return []
        
        # Extract temperatures for outlier detection
        raw_forecasts = [temp for temp, _, _ in forecast_data]
        
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
            temp, source, forecast_time = forecast_data[idx]
            
            # Source reliability weight
            source_weight = self.source_weights.get(source, 0.8)
            
            # Forecast age weight (exponential decay with 6-hour half-life)
            age_hours = (now - forecast_time).total_seconds() / 3600.0
            age_weight = np.exp(-age_hours / 6.0)  # 6-hour half-life
            
            # Combined weight
            combined_weight = source_weight * age_weight
            
            weighted_forecasts.append((temp, combined_weight))
            total_weight += combined_weight
        
        # Calculate weighted average
        if total_weight > 0:
            weighted_mean = sum(temp * weight for temp, weight in weighted_forecasts) / total_weight
            
            # For probability distribution, we need individual forecasts
            # Use weighted mean as primary, but keep individual forecasts for std calculation
            # Adjust forecasts to be closer to weighted mean based on their weights
            adjusted_forecasts = []
            for temp, weight in weighted_forecasts:
                # Blend original forecast with weighted mean based on source reliability
                adjusted = temp * (weight / total_weight) + weighted_mean * (1 - weight / total_weight)
                adjusted_forecasts.append(adjusted)
            
            # Store metadata for later use
            self.forecast_metadata[cache_key] = forecast_data
            
            # Cache the adjusted forecasts
            self.forecast_cache[cache_key] = adjusted_forecasts
            self.cache_timestamp[cache_key] = datetime.now()
            
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
        # Default forecast error: 2.0°F (conservative estimate)
        return 2.0
    
    def build_probability_distribution(self, forecasts: List[float], 
                                     temperature_ranges: List[Tuple[float, float]],
                                     series_ticker: str = '',
                                     target_date: Optional[datetime] = None) -> Dict[Tuple[float, float], float]:
        """
        Build probability distribution over temperature ranges from forecasts
        Uses dynamic standard deviation based on forecast agreement and historical data
        
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
        mean_temp = np.mean(forecasts)
        
        # Dynamic standard deviation calculation
        if len(forecasts) > 1:
            # Use actual std from forecast spread
            std_temp = np.std(forecasts)
            
            # Add base uncertainty based on forecast horizon
            if target_date:
                days_until = (target_date - datetime.now()).days
                hours_until = (target_date - datetime.now()).total_seconds() / 3600.0
                # Base uncertainty increases with time: +0.5°F per day, +0.1°F per hour
                base_uncertainty = 1.0 + (days_until * 0.5) + max(0, (hours_until - days_until * 24) * 0.1)
                std_temp = max(std_temp, base_uncertainty)
            
            # Incorporate historical forecast error if available
            if series_ticker and target_date:
                historical_error = self.get_historical_forecast_error(series_ticker, target_date.month)
                # Blend actual std with historical error (weighted average)
                std_temp = 0.7 * std_temp + 0.3 * historical_error
        else:
            # Only one forecast - use historical error or default
            if series_ticker and target_date:
                std_temp = self.get_historical_forecast_error(series_ticker, target_date.month)
            else:
                std_temp = 2.0  # Default std if no historical data
        
        # Ensure minimum std for stability
        std_temp = max(std_temp, 1.0)
        
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
        
        logger.info(f"📊 Updated forecast error for {series_ticker} (month {month}): {error:.2f}°F")
    
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
                    overlap = (temp_max - threshold) / (temp_max - temp_min)
                    total_prob += prob * overlap
            else:
                # For "below threshold", count ranges where max <= threshold
                if temp_max <= threshold:
                    total_prob += prob
                elif temp_min < threshold:
                    # Partial overlap
                    overlap = (threshold - temp_min) / (temp_max - temp_min)
                    total_prob += prob * overlap
        
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
                                    n_samples: int = 1000, is_above: bool = True) -> Tuple[float, Tuple[float, float]]:
        """
        Calculate probability with confidence interval using bootstrap sampling
        
        Args:
            forecasts: List of temperature forecasts
            threshold: Temperature threshold
            n_samples: Number of bootstrap samples
            is_above: True for "above threshold", False for "below threshold"
        
        Returns:
            (mean_probability, (ci_lower, ci_upper)) where CI is 95% confidence interval
        """
        if not forecasts or len(forecasts) < 2:
            return 0.5, (0.0, 1.0)  # No confidence with insufficient data
        
        probs = []
        mean_forecast = np.mean(forecasts)
        std_forecast = np.std(forecasts) if len(forecasts) > 1 else 2.0
        
        for _ in range(n_samples):
            # Resample forecasts with replacement
            sample = np.random.choice(forecasts, size=len(forecasts), replace=True)
            sample_mean = np.mean(sample)
            sample_std = np.std(sample) if len(sample) > 1 else std_forecast
            
            # Calculate probability for this sample
            if is_above:
                # Probability that temp > threshold
                prob = 1.0 - stats.norm.cdf(threshold, sample_mean, sample_std)
            else:
                # Probability that temp < threshold
                prob = stats.norm.cdf(threshold, sample_mean, sample_std)
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
