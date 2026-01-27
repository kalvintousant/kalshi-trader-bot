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
    
    # City coordinates for weather APIs
    CITY_COORDS = {
        'KXHIGHNY': {'lat': 40.7128, 'lon': -74.0060, 'name': 'New York City'},  # Central Park
        'KXHIGHCH': {'lat': 41.8781, 'lon': -87.6298, 'name': 'Chicago'},
        'KXHIGHMI': {'lat': 25.7617, 'lon': -80.1918, 'name': 'Miami'},
        'KXHIGHAU': {'lat': 30.2672, 'lon': -97.7431, 'name': 'Austin'},
    }
    
    def __init__(self):
        # API keys from environment (optional - will use free tiers where possible)
        self.openweather_api_key = os.getenv('OPENWEATHER_API_KEY', '')
        self.tomorrowio_api_key = os.getenv('TOMORROWIO_API_KEY', '')
        self.accuweather_api_key = os.getenv('ACCUWEATHER_API_KEY', '')
        self.weatherbit_api_key = os.getenv('WEATHERBIT_API_KEY', '')
        
        # Cache for forecasts (refresh every hour)
        self.forecast_cache = {}
        self.cache_timestamp = {}
        self.cache_ttl = 3600  # 1 hour in seconds
        
        # Use session for connection pooling
        self.session = requests.Session()
    
    def get_forecast_openweather(self, lat: float, lon: float, date: datetime) -> Optional[float]:
        """Get forecast from OpenWeather API (free tier available)"""
        if not self.openweather_api_key:
            return None
        
        try:
            # OpenWeather provides 5-day forecast
            url = f"https://api.openweathermap.org/data/2.5/forecast"
            params = {
                'lat': lat,
                'lon': lon,
                'appid': self.openweather_api_key,
                'units': 'imperial'
            }
            response = self.session.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                # Find forecast for target date
                target_date_str = date.strftime('%Y-%m-%d')
                for item in data.get('list', []):
                    forecast_date = datetime.fromtimestamp(item['dt']).strftime('%Y-%m-%d')
                    if forecast_date == target_date_str:
                        return item['main']['temp_max']
        except Exception as e:
            print(f"[Weather] OpenWeather API error: {e}")
        return None
    
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
        forecasts = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self.get_forecast_nws, lat, lon, target_date): 'nws',
                executor.submit(self.get_forecast_openweather, lat, lon, target_date): 'openweather',
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
