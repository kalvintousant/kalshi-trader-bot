"""
Weather Data Aggregator - Multi-source forecast collection and probability distribution
Based on the weather trading edge strategy guide
"""
import os
import re
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from scipy import stats
from dotenv import load_dotenv

load_dotenv()

# Compile regex patterns once at module level for performance
TEMP_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*°?F', re.IGNORECASE)
THRESHOLD_PATTERN = re.compile(r'(?:above|below|>|<)\s*(\d+(?:\.\d+)?)', re.IGNORECASE)


class WeatherDataAggregator:
    """Aggregates weather forecasts from multiple sources and builds probability distributions"""
    
    # Official NWS measurement locations per contract rules (supports both HIGH and LOW temperature markets)
    # Coordinates match exact NWS weather station locations used for contract settlement
    CITY_COORDS = {
        # New York City - Central Park (NHIGH contract: "Central Park, New York")
        'KXHIGHNY': {'lat': 40.7711, 'lon': -73.9742, 'name': 'Central Park, New York'},
        'KXLOWNY': {'lat': 40.7711, 'lon': -73.9742, 'name': 'Central Park, New York'},
        # Chicago - Midway Airport (CHIHIGH contract: "Chicago Midway, Illinois")
        'KXHIGHCH': {'lat': 41.7868, 'lon': -87.7522, 'name': 'Chicago Midway Airport'},
        'KXLOWCH': {'lat': 41.7868, 'lon': -87.7522, 'name': 'Chicago Midway Airport'},
        # Miami - Miami International Airport (MIHIGH contract - likely MIA)
        'KXHIGHMI': {'lat': 25.7932, 'lon': -80.2906, 'name': 'Miami International Airport'},
        'KXLOWMI': {'lat': 25.7932, 'lon': -80.2906, 'name': 'Miami International Airport'},
        # Austin - Austin Bergstrom International Airport (AUSHIGH contract: "Austin Bergstrom")
        'KXHIGHAUS': {'lat': 30.1831, 'lon': -97.6799, 'name': 'Austin Bergstrom International Airport'},
        'KXLOWAUS': {'lat': 30.1831, 'lon': -97.6799, 'name': 'Austin Bergstrom International Airport'},
        # Los Angeles - Los Angeles International Airport (LAXHIGH contract - likely LAX)
        'KXHIGHLAX': {'lat': 33.9425, 'lon': -118.4081, 'name': 'Los Angeles International Airport'},
        'KXLOWLAX': {'lat': 33.9425, 'lon': -118.4081, 'name': 'Los Angeles International Airport'},
    }
    
    def __init__(self):
        # API keys from environment (optional - will use free tiers where possible)
        # OpenWeather removed per user request
        self.tomorrowio_api_key = os.getenv('TOMORROWIO_API_KEY', '')
        self.accuweather_api_key = os.getenv('ACCUWEATHER_API_KEY', '')
        self.weatherbit_api_key = os.getenv('WEATHERBIT_API_KEY', '')
        
        # Cache for forecasts (refresh every 30 minutes)
        # Based on AUSHIGH contract rules: daily markets, forecasts update 2-4x/day
        # 30 min cache balances freshness with API rate limits
        self.forecast_cache = {}
        self.cache_timestamp = {}
        self.cache_ttl = 1800  # 30 minutes in seconds (forecasts update hourly at most)
        
        # Use session for connection pooling
        self.session = requests.Session()
    
    def get_forecast_tomorrowio(self, lat: float, lon: float, date: datetime) -> Optional[float]:
        """Get forecast from Tomorrow.io API"""
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
                            return point['values'].get('temperatureMax')
        except Exception as e:
            print(f"[Weather] Tomorrow.io API error: {e}")
        return None
    
    def get_forecast_nws(self, lat: float, lon: float, date: datetime) -> Optional[float]:
        """Get forecast from National Weather Service (free, no API key needed)"""
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
                            return period.get('temperature')
        except Exception as e:
            print(f"[Weather] NWS API error: {e}")
        return None
    
    def get_forecast_weatherbit(self, lat: float, lon: float, date: datetime, series_ticker: str = '') -> Optional[float]:
        """Get forecast from Weatherbit API - returns max temp for HIGH markets, min temp for LOW markets"""
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
                            return day.get('min_temp')  # Minimum temperature for LOW markets
                        else:
                            return day.get('max_temp')  # Maximum temperature for HIGH markets
        except Exception as e:
            print(f"[Weather] Weatherbit API error: {e}")
        return None
    
    def get_all_forecasts(self, series_ticker: str, target_date: datetime) -> List[float]:
        """
        Collect forecasts from all available sources with caching and parallel execution
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
        forecasts = []
        
        # First, try NWS and Tomorrow.io (both have higher free tier limits)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self.get_forecast_nws, lat, lon, target_date): 'nws',
                executor.submit(self.get_forecast_tomorrowio, lat, lon, target_date): 'tomorrowio'
            }
            
            for future in as_completed(futures):
                try:
                    temp = future.result()
                    if temp is not None:
                        forecasts.append(temp)
                except Exception as e:
                    source = futures[future]
                    print(f"[Weather] Error fetching from {source}: {e}")
        
        # Only use Weatherbit if we have ZERO forecasts (emergency fallback only)
        # This keeps Weatherbit usage minimal to stay within 50 requests/day free tier
        # Weatherbit free tier: 50 requests/day - must be very conservative
        if len(forecasts) == 0 and self.weatherbit_api_key:
            try:
                weatherbit_temp = self.get_forecast_weatherbit(lat, lon, target_date, series_ticker)
                if weatherbit_temp is not None:
                    forecasts.append(weatherbit_temp)
                    print(f"[Weather] Using Weatherbit fallback for {series_ticker} (NWS/Tomorrow.io unavailable)")
            except Exception as e:
                print(f"[Weather] Error fetching from weatherbit (fallback): {e}")
        
        # Cache the results
        if forecasts:
            self.forecast_cache[cache_key] = forecasts
            self.cache_timestamp[cache_key] = datetime.now()
        
        # If we have no forecasts, use a simple fallback based on historical averages
        if not forecasts:
            print(f"[Weather] No forecasts available for {city['name']}, using fallback")
            # Could add historical average or other fallback here
        
        return forecasts
    
    def build_probability_distribution(self, forecasts: List[float], 
                                     temperature_ranges: List[Tuple[float, float]]) -> Dict[Tuple[float, float], float]:
        """
        Build probability distribution over temperature ranges from forecasts
        
        Args:
            forecasts: List of temperature forecasts from different sources
            temperature_ranges: List of (min, max) temperature range tuples
        
        Returns:
            Dictionary mapping (min, max) ranges to probabilities
        """
        if not forecasts:
            return {}
        
        # Calculate mean and std of forecasts
        mean_temp = np.mean(forecasts)
        std_temp = np.std(forecasts) if len(forecasts) > 1 else 2.0  # Default std if only one forecast
        
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
    
    def calculate_ev(self, win_prob: float, payout: float, loss_prob: float, stake: float) -> float:
        """
        Calculate Expected Value: (Win Prob × Payout) - (Loss Prob × Stake)
        
        Args:
            win_prob: Probability of winning (0-1)
            payout: Payout if we win (in dollars)
            loss_prob: Probability of losing (0-1)
            stake: Amount staked (in dollars)
        
        Returns:
            Expected value in dollars
        """
        ev = (win_prob * payout) - (loss_prob * stake)
        return ev


# Helper function to extract temperature threshold from market title
def extract_threshold_from_market(market: Dict) -> Optional[float]:
    """Extract temperature threshold from Kalshi market title"""
    title = market.get('title', '')
    
    # Try to find number followed by °F or F
    match = TEMP_PATTERN.search(title)
    if match:
        return float(match.group(1))
    
    # Try to find "above X" or "below X"
    match = THRESHOLD_PATTERN.search(title)
    if match:
        return float(match.group(1))
    
    return None
