"""
BTC Price Data - Real-time BTC price tracking from Binance
For latency arbitrage strategy on Kalshi 15-minute and hourly BTC markets

Contract Rules (CRYPTO15M):
- Kalshi contracts use CF Bitcoin Real-Time Index (BRTI) from CF Benchmarks
- Contract settles on simple average of BRTI for the 60 seconds prior to expiration time
- We use Binance spot price as a proxy for real-time tracking (closely tracks BRTI)
- This enables latency arbitrage by detecting moves before Kalshi odds update
"""
import requests
import time
import bisect
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import deque


class BTCPriceTracker:
    """Tracks real-time BTC price movements from Binance"""
    
    def __init__(self):
        self.binance_api = "https://api.binance.com/api/v3"
        self.price_history = deque(maxlen=100)  # Keep last 100 price points
        self.candle_history = deque(maxlen=20)  # Keep last 20 5-minute candles
        self.last_update = None
        
        # Use session for connection pooling
        self.session = requests.Session()
        
    def get_current_price(self) -> Optional[float]:
        """Get current BTC price from Binance"""
        try:
            url = f"{self.binance_api}/ticker/price"
            params = {'symbol': 'BTCUSDT'}
            response = self.session.get(url, params=params, timeout=2)
            if response.status_code == 200:
                data = response.json()
                price = float(data['price'])
                self.price_history.append({
                    'price': price,
                    'timestamp': datetime.now()
                })
                return price
        except Exception as e:
            print(f"[BTC] Error fetching price: {e}")
        return None
    
    def get_5min_candles(self, limit: int = 20) -> List[Dict]:
        """Get 5-minute candles from Binance"""
        try:
            url = f"{self.binance_api}/klines"
            params = {
                'symbol': 'BTCUSDT',
                'interval': '5m',
                'limit': limit
            }
            response = self.session.get(url, params=params, timeout=2)
            if response.status_code == 200:
                candles = []
                for candle in response.json():
                    candles.append({
                        'open_time': datetime.fromtimestamp(candle[0] / 1000),
                        'open': float(candle[1]),
                        'high': float(candle[2]),
                        'low': float(candle[3]),
                        'close': float(candle[4]),
                        'volume': float(candle[5]),
                        'close_time': datetime.fromtimestamp(candle[6] / 1000)
                    })
                self.candle_history = deque(candles, maxlen=20)
                return candles
        except Exception as e:
            print(f"[BTC] Error fetching candles: {e}")
        return []
    
    def calculate_momentum(self, lookback_periods: int = 3) -> Optional[float]:
        """
        Calculate momentum from recent 5-minute candles
        Returns percentage change over lookback period
        """
        if len(self.candle_history) < lookback_periods + 1:
            return None
        
        candles = list(self.candle_history)
        current_close = candles[-1]['close']
        past_close = candles[-lookback_periods-1]['close']
        
        momentum = ((current_close - past_close) / past_close) * 100
        return momentum
    
    def calculate_volatility(self, lookback_periods: int = 5) -> Optional[float]:
        """
        Calculate recent volatility (standard deviation of returns)
        """
        if len(self.candle_history) < lookback_periods + 1:
            return None
        
        candles = list(self.candle_history)
        returns = []
        
        for i in range(-lookback_periods, 0):
            if i == -lookback_periods:
                continue
            prev_close = candles[i-1]['close']
            curr_close = candles[i]['close']
            ret = (curr_close - prev_close) / prev_close
            returns.append(ret)
        
        if not returns:
            return None
        
        import statistics
        volatility = statistics.stdev(returns) * 100  # Convert to percentage
        return volatility
    
    def detect_significant_move(self, momentum_threshold: float = 0.5, 
                               volatility_threshold: float = 0.3) -> Tuple[bool, str]:
        """
        Detect if there's been a significant BTC move
        Returns: (has_move, direction)
        """
        momentum = self.calculate_momentum()
        volatility = self.calculate_volatility()
        
        if momentum is None or volatility is None:
            return (False, "insufficient_data")
        
        # Check if momentum exceeds threshold
        if abs(momentum) > momentum_threshold and volatility > volatility_threshold:
            direction = "up" if momentum > 0 else "down"
            return (True, direction)
        
        return (False, "no_move")
    
    def get_price_change_period(self, minutes: int = 15) -> Optional[float]:
        """
        Get price change over a specific period (e.g., 15 minutes for 15-min markets)
        Returns percentage change
        Optimized with binary search for better performance
        """
        if len(self.price_history) < 2:
            return None
        
        # Get price from N minutes ago (approximate)
        current_price = self.price_history[-1]['price']
        current_time = self.price_history[-1]['timestamp']
        
        # Find price from approximately N minutes ago
        target_time = current_time - timedelta(minutes=minutes)
        target_timestamp = target_time.timestamp()
        
        # Convert to list for binary search (price_history is deque)
        price_list = list(self.price_history)
        
        # Use binary search to find closest timestamp
        # Create list of timestamps for bisect
        timestamps = [p['timestamp'].timestamp() for p in price_list]
        
        # Find insertion point (closest timestamp)
        idx = bisect.bisect_left(timestamps, target_timestamp)
        
        # Check both sides of insertion point for closest match
        closest_price = None
        min_time_diff = float('inf')
        
        # Check index and index-1
        for check_idx in [idx, idx - 1]:
            if 0 <= check_idx < len(price_list):
                price_point = price_list[check_idx]
                time_diff = abs((price_point['timestamp'] - target_time).total_seconds())
                if time_diff < min_time_diff:
                    min_time_diff = time_diff
                    closest_price = price_point['price']
        
        if closest_price and min_time_diff < 600:  # Within 10 minutes tolerance
            change = ((current_price - closest_price) / closest_price) * 100
            return change
        
        return None
    
    def update(self):
        """Update price and candle data"""
        self.get_current_price()
        self.get_5min_candles()
        self.last_update = datetime.now()
    
    def is_fresh(self, max_age_seconds: int = 30) -> bool:
        """Check if data is fresh"""
        if not self.last_update:
            return False
        age = (datetime.now() - self.last_update).total_seconds()
        return age < max_age_seconds
