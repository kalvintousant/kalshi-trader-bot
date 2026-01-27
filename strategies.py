import time
import uuid
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from kalshi_client import KalshiClient
from config import Config
from btc_data import BTCPriceTracker
from weather_data import WeatherDataAggregator, extract_threshold_from_market


class TradingStrategy:
    """Base class for trading strategies"""
    
    def __init__(self, client: KalshiClient):
        self.client = client
        self.name = self.__class__.__name__
    
    def should_trade(self, market: Dict) -> bool:
        """Determine if we should trade this market"""
        raise NotImplementedError
    
    def get_trade_decision(self, market: Dict, orderbook: Dict) -> Optional[Dict]:
        """Get trading decision: {'action': 'buy'/'sell', 'side': 'yes'/'no', 'count': int, 'price': int}"""
        raise NotImplementedError
    
    def execute_trade(self, decision: Dict, market_ticker: str) -> Optional[Dict]:
        """Execute a trade"""
        try:
            order = self.client.create_order(
                ticker=market_ticker,
                action=decision['action'],
                side=decision['side'],
                count=decision['count'],
                order_type='limit',
                yes_price=decision.get('price'),
                no_price=decision.get('price'),
                client_order_id=str(uuid.uuid4())
            )
            
            # Enhanced trade notification
            order_id = order.get('order_id', 'N/A')
            action = decision['action']
            side = decision['side']
            count = decision['count']
            price = decision.get('price', 'N/A')
            
            trade_msg = f"🔄 TRADE EXECUTED: {action.upper()} {count} {side.upper()} @ {price}¢ | Order: {order_id} | Market: {market_ticker}"
            
            # Print to console
            print("="*70)
            print(trade_msg)
            print("="*70)
            
            # Log to file
            self._log_trade(trade_msg, order, decision, market_ticker)
            
            # macOS notification
            self._send_notification(f"Trade Placed: {action.upper()} {side.upper()}", 
                                  f"{count} contract(s) @ {price}¢\nMarket: {market_ticker}")
            
            return order
        except Exception as e:
            error_msg = f"[{self.name}] Error placing order: {e}"
            print(error_msg)
            self._log_trade(error_msg, None, decision, market_ticker)
            return None
    
    def _log_trade(self, message: str, order: Optional[Dict], decision: Dict, market_ticker: str):
        """Log trade to file"""
        try:
            from datetime import datetime
            log_file = "trades.log"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_entry = f"[{timestamp}] {message}\n"
            if order:
                log_entry += f"  Order Details: {order}\n"
            log_entry += f"  Decision: {decision}\n"
            log_entry += "-" * 70 + "\n"
            
            with open(log_file, 'a') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"[{self.name}] Error logging trade: {e}")
    
    def _send_notification(self, title: str, message: str):
        """Send macOS notification"""
        try:
            import subprocess
            # Use osascript to send macOS notification
            script = f'''
            display notification "{message}" with title "{title}"
            '''
            subprocess.run(['osascript', '-e', script], capture_output=True)
        except Exception as e:
            # Silently fail if notifications don't work
            pass


class BTCHourlyStrategy(TradingStrategy):
    """
    Latency Arbitrage Strategy for Hourly BTC markets
    Tracks real-time BTC moves from Binance and trades during lag window when Kalshi pricing hasn't caught up.
    
    Contract Rules Compliance:
    - Uses CF Bitcoin Real-Time Index (BRTI) equivalent (Binance spot price as proxy)
    - Tracks price movements over 1-hour periods to match hourly market expiration
    - Respects expiration times and last trading dates per contract rules
    """
    
    def __init__(self, client: KalshiClient, btc_tracker: Optional[BTCPriceTracker] = None):
        super().__init__(client)
        self.max_position_size = Config.MAX_POSITION_SIZE
        
        # Use provided BTC tracker or create new one (shared instance from bot)
        self.btc_tracker = btc_tracker or BTCPriceTracker()
        
        # Strategy parameters
        self.momentum_threshold = 0.3  # Minimum momentum % to trigger trade (0.3%)
        self.volatility_threshold = 0.2  # Minimum volatility % to ensure real move
        self.mispricing_threshold = 3  # Minimum price difference (cents) between Binance move and Kalshi pricing
        
        # Track active positions for exit logic
        self.active_positions = {}  # {market_ticker: {'side': 'yes'/'no', 'entry_price': int, 'entry_time': datetime}}
        
        # Update BTC data on init if we created the tracker
        if btc_tracker is None:
            self.btc_tracker.update()
    
    def should_trade(self, market: Dict) -> bool:
        """
        Check if this is an hourly BTC market we should trade
        
        Contract Rules Compliance:
        - Only trades markets with status='open' (respects Last Trading Date/Time)
        - Kalshi API filters out expired markets automatically
        - Minimum volume check ensures liquidity
        """
        series_ticker = market.get('series_ticker', '')
        if series_ticker != Config.BTC_HOURLY_SERIES:
            return False
        
        # Contract Rule: Respect Last Trading Date/Time - only trade open markets
        if market.get('status') != 'open':
            return False
        
        # Check if market has sufficient volume (liquidity requirement)
        if market.get('volume', 0) < 5:
            return False
        
        return True
    
    def get_trade_decision(self, market: Dict, orderbook: Dict) -> Optional[Dict]:
        """
        Latency arbitrage strategy:
        1. Read real-time BTC moves from Binance
        2. Check Kalshi's delayed pricing
        3. Enter during lag window if there's desynchronization
        4. Exit once pricing catches up
        """
        try:
            market_ticker = market.get('ticker', '')
            
            # Note: BTC data should be updated at bot level, not here for performance
            # This check is just a safety fallback
            if not self.btc_tracker.is_fresh(max_age_seconds=30):
                self.btc_tracker.update()
            
            # Check if we have an active position to exit
            if market_ticker in self.active_positions:
                return self._check_exit(market, orderbook, market_ticker)
            
            # Detect significant BTC move
            has_move, direction = self.btc_tracker.detect_significant_move(
                momentum_threshold=self.momentum_threshold,
                volatility_threshold=self.volatility_threshold
            )
            
            if not has_move:
                return None
            
            # Get current BTC price change over 1 hour (for hourly markets)
            # Contract uses BRTI average for minute prior to expiration - we track hourly moves
            btc_change_1h = self.btc_tracker.get_price_change_period(minutes=60)
            
            if btc_change_1h is None:
                return None
            
            # Get Kalshi market pricing
            yes_price = market.get('yes_price', 50)
            no_price = market.get('no_price', 50)
            
            yes_bids = orderbook.get('orderbook', {}).get('yes', [])
            no_bids = orderbook.get('orderbook', {}).get('no', [])
            
            if not yes_bids or not no_bids:
                return None
            
            best_yes_bid = yes_bids[0][0] if yes_bids else yes_price
            best_no_bid = no_bids[0][0] if no_bids else no_price
            
            # Calculate expected Kalshi price based on BTC move
            # If BTC is up, YES should be higher priced
            # If BTC is down, NO should be higher priced
            
            # Convert BTC change to expected probability
            # Positive change = higher probability of YES
            # Negative change = higher probability of NO
            # Contract uses BRTI (we use Binance as proxy) - 1% hourly move = 10% prob change
            expected_yes_prob = 50 + (btc_change_1h * 10)  # Scale: 1% BTC move = 10% prob change
            expected_yes_prob = max(1, min(99, expected_yes_prob))  # Clamp to 1-99
            
            # Compare expected price to actual Kalshi price
            price_mispricing = abs(expected_yes_prob - best_yes_bid)
            
            # Trade logic: If BTC pumped and YES is underpriced, buy YES
            # If BTC dumped and NO is underpriced, buy NO
            if direction == "up" and btc_change_1h > 0:
                # BTC pumped, check if YES is mispriced
                if expected_yes_prob > best_yes_bid + self.mispricing_threshold:
                    print(f"[BTCStrategy] BTC PUMP detected: {btc_change_1h:.2f}% move (1h), YES expected {expected_yes_prob:.1f}¢, market {best_yes_bid}¢, mispricing {price_mispricing:.1f}¢")
                    # Record position for exit logic
                    self.active_positions[market_ticker] = {
                        'side': 'yes',
                        'entry_price': best_yes_bid + 1,
                        'entry_time': datetime.now(),
                        'expected_prob': expected_yes_prob
                    }
                    return {
                        'action': 'buy',
                        'side': 'yes',
                        'count': min(1, self.max_position_size),
                        'price': best_yes_bid + 1,
                        'btc_move': btc_change_1h,
                        'mispricing': price_mispricing
                    }
            
            elif direction == "down" and btc_change_1h < 0:
                # BTC dumped, check if NO is mispriced
                expected_no_prob = 100 - expected_yes_prob
                if expected_no_prob > best_no_bid + self.mispricing_threshold:
                    print(f"[BTCStrategy] BTC DUMP detected: {btc_change_1h:.2f}% move (1h), NO expected {expected_no_prob:.1f}¢, market {best_no_bid}¢, mispricing {price_mispricing:.1f}¢")
                    # Record position for exit logic
                    self.active_positions[market_ticker] = {
                        'side': 'no',
                        'entry_price': best_no_bid + 1,
                        'entry_time': datetime.now(),
                        'expected_prob': expected_no_prob
                    }
                    return {
                        'action': 'buy',
                        'side': 'no',
                        'count': min(1, self.max_position_size),
                        'price': best_no_bid + 1,
                        'btc_move': btc_change_1h,
                        'mispricing': price_mispricing
                    }
            
            return None
            
        except Exception as e:
            print(f"[BTCHourlyStrategy] Error in get_trade_decision: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _check_exit(self, market: Dict, orderbook: Dict, market_ticker: str) -> Optional[Dict]:
        """
        Check if we should exit an active position
        Exit when pricing catches up (mispricing closes)
        """
        try:
            position = self.active_positions[market_ticker]
            side = position['side']
            entry_price = position['entry_price']
            entry_time = position['entry_time']
            
            # Check if enough time has passed (at least 30 seconds)
            if (datetime.now() - entry_time).total_seconds() < 30:
                return None  # Too soon to exit
            
            # Get current market prices
            yes_price = market.get('yes_price', 50)
            no_price = market.get('no_price', 50)
            
            yes_bids = orderbook.get('orderbook', {}).get('yes', [])
            no_bids = orderbook.get('orderbook', {}).get('no', [])
            
            if not yes_bids or not no_bids:
                return None
            
            current_yes = yes_bids[0][0] if yes_bids else yes_price
            current_no = no_bids[0][0] if no_bids else no_price
            
            # Check if pricing has caught up (mispricing closed)
            if side == 'yes':
                current_price = current_yes
                # Exit if price moved towards expected (caught up) or we're profitable
                if current_price >= position['expected_prob'] - 2 or current_price > entry_price + 2:
                    print(f"[BTCHourlyStrategy] Exiting YES position: entry {entry_price}¢, current {current_price}¢, expected {position['expected_prob']:.1f}¢")
                    del self.active_positions[market_ticker]
                    return {
                        'action': 'sell',
                        'side': 'yes',
                        'count': 1,
                        'price': current_yes - 1  # Slightly below best bid to exit quickly
                    }
            
            elif side == 'no':
                current_price = current_no
                # Exit if price moved towards expected (caught up) or we're profitable
                if current_price >= position['expected_prob'] - 2 or current_price > entry_price + 2:
                    print(f"[BTCHourlyStrategy] Exiting NO position: entry {entry_price}¢, current {current_price}¢, expected {position['expected_prob']:.1f}¢")
                    del self.active_positions[market_ticker]
                    return {
                        'action': 'sell',
                        'side': 'no',
                        'count': 1,
                        'price': current_no - 1
                    }
            
            return None
            
        except Exception as e:
            print(f"[BTCHourlyStrategy] Error in _check_exit: {e}")
            return None


class BTC15MinStrategy(TradingStrategy):
    """
    Latency Arbitrage Strategy for 15-minute BTC markets (KXBTC15M)
    Tracks real-time BTC moves from Binance and trades during lag window when Kalshi pricing hasn't caught up.
    
    This strategy is optimized for the "Bitcoin price up or down in next 15 mins" markets.
    Uses 15-minute price change calculations for faster reaction to BTC movements.
    """
    
    def __init__(self, client: KalshiClient, btc_tracker: Optional[BTCPriceTracker] = None):
        super().__init__(client)
        self.max_position_size = Config.MAX_POSITION_SIZE
        
        # Use provided BTC tracker or create new one (shared instance from bot)
        self.btc_tracker = btc_tracker or BTCPriceTracker()
        
        # Strategy parameters (tuned for 15-minute markets - more sensitive)
        self.momentum_threshold = 0.2  # Lower threshold for 15-min moves (0.2%)
        self.volatility_threshold = 0.15  # Lower volatility threshold (0.15%)
        self.mispricing_threshold = 2  # Lower mispricing threshold (2 cents) for faster reaction
        
        # Track active positions for exit logic
        self.active_positions = {}  # {market_ticker: {'side': 'yes'/'no', 'entry_price': int, 'entry_time': datetime}}
        
        # Update BTC data on init if we created the tracker
        if btc_tracker is None:
            self.btc_tracker.update()
    
    def should_trade(self, market: Dict) -> bool:
        """
        Check if this is a 15-minute BTC market we should trade
        
        Contract Rules Compliance:
        - Only trades markets with status='open' (respects Last Trading Date/Time)
        - Kalshi API filters out expired markets automatically
        - Minimum volume check ensures liquidity
        """
        series_ticker = market.get('series_ticker', '')
        if series_ticker != Config.BTC_15M_SERIES:
            return False
        
        # Contract Rule: Respect Last Trading Date/Time - only trade open markets
        if market.get('status') != 'open':
            return False
        
        # Check if market has sufficient volume (liquidity requirement)
        if market.get('volume', 0) < 5:
            return False
        
        return True
    
    def get_trade_decision(self, market: Dict, orderbook: Dict) -> Optional[Dict]:
        """
        Latency arbitrage strategy for 15-minute markets:
        1. Read real-time BTC moves from Binance (5-minute candles)
        2. Check Kalshi's delayed pricing
        3. Enter during lag window if there's desynchronization
        4. Exit once pricing catches up
        """
        try:
            market_ticker = market.get('ticker', '')
            
            # Note: BTC data should be updated at bot level, not here for performance
            # This check is just a safety fallback
            if not self.btc_tracker.is_fresh(max_age_seconds=15):  # More frequent updates for 15-min
                self.btc_tracker.update()
            
            # Check if we have an active position to exit
            if market_ticker in self.active_positions:
                return self._check_exit(market, orderbook, market_ticker)
            
            # Detect significant BTC move
            has_move, direction = self.btc_tracker.detect_significant_move(
                momentum_threshold=self.momentum_threshold,
                volatility_threshold=self.volatility_threshold
            )
            
            if not has_move:
                return None
            
            # Get current BTC price change over 15 minutes (for 15-min markets)
            # Contract uses BRTI average for minute prior to expiration - we track 15-min moves
            btc_change_15m = self.btc_tracker.get_price_change_period(minutes=15)
            
            if btc_change_15m is None:
                return None
            
            # Get Kalshi market pricing
            yes_price = market.get('yes_price', 50)
            no_price = market.get('no_price', 50)
            
            yes_bids = orderbook.get('orderbook', {}).get('yes', [])
            no_bids = orderbook.get('orderbook', {}).get('no', [])
            
            if not yes_bids or not no_bids:
                return None
            
            best_yes_bid = yes_bids[0][0] if yes_bids else yes_price
            best_no_bid = no_bids[0][0] if no_bids else no_price
            
            # Calculate expected Kalshi price based on BTC move
            # If BTC is up, YES should be higher priced
            # If BTC is down, NO should be higher priced
            
            # Convert BTC change to expected probability
            # Positive change = higher probability of YES
            # Negative change = higher probability of NO
            # For 15-min markets, moves are smaller so we scale differently
            expected_yes_prob = 50 + (btc_change_15m * 15)  # Scale: 1% BTC move = 15% prob change (more sensitive)
            expected_yes_prob = max(1, min(99, expected_yes_prob))  # Clamp to 1-99
            
            # Compare expected price to actual Kalshi price
            price_mispricing = abs(expected_yes_prob - best_yes_bid)
            
            # Trade logic: If BTC pumped and YES is underpriced, buy YES
            # If BTC dumped and NO is underpriced, buy NO
            if direction == "up" and btc_change_15m > 0:
                # BTC pumped, check if YES is mispriced
                if expected_yes_prob > best_yes_bid + self.mispricing_threshold:
                    print(f"[BTC15MinStrategy] BTC PUMP detected: {btc_change_15m:.2f}% move (15m), YES expected {expected_yes_prob:.1f}¢, market {best_yes_bid}¢, mispricing {price_mispricing:.1f}¢")
                    # Record position for exit logic
                    self.active_positions[market_ticker] = {
                        'side': 'yes',
                        'entry_price': best_yes_bid + 1,
                        'entry_time': datetime.now(),
                        'expected_prob': expected_yes_prob
                    }
                    return {
                        'action': 'buy',
                        'side': 'yes',
                        'count': min(1, self.max_position_size),
                        'price': best_yes_bid + 1,
                        'btc_move': btc_change_15m,
                        'mispricing': price_mispricing
                    }
            
            elif direction == "down" and btc_change_15m < 0:
                # BTC dumped, check if NO is mispriced
                expected_no_prob = 100 - expected_yes_prob
                if expected_no_prob > best_no_bid + self.mispricing_threshold:
                    print(f"[BTC15MinStrategy] BTC DUMP detected: {btc_change_15m:.2f}% move (15m), NO expected {expected_no_prob:.1f}¢, market {best_no_bid}¢, mispricing {price_mispricing:.1f}¢")
                    # Record position for exit logic
                    self.active_positions[market_ticker] = {
                        'side': 'no',
                        'entry_price': best_no_bid + 1,
                        'entry_time': datetime.now(),
                        'expected_prob': expected_no_prob
                    }
                    return {
                        'action': 'buy',
                        'side': 'no',
                        'count': min(1, self.max_position_size),
                        'price': best_no_bid + 1,
                        'btc_move': btc_change_15m,
                        'mispricing': price_mispricing
                    }
            
            return None
            
        except Exception as e:
            print(f"[BTC15MinStrategy] Error in get_trade_decision: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _check_exit(self, market: Dict, orderbook: Dict, market_ticker: str) -> Optional[Dict]:
        """
        Check if we should exit an active position
        Exit when pricing catches up (mispricing closes)
        For 15-min markets, exits are faster (15 seconds minimum hold)
        """
        try:
            position = self.active_positions[market_ticker]
            side = position['side']
            entry_price = position['entry_price']
            entry_time = position['entry_time']
            
            # Check if enough time has passed (at least 15 seconds for 15-min markets)
            if (datetime.now() - entry_time).total_seconds() < 15:
                return None  # Too soon to exit
            
            # Get current market prices
            yes_price = market.get('yes_price', 50)
            no_price = market.get('no_price', 50)
            
            yes_bids = orderbook.get('orderbook', {}).get('yes', [])
            no_bids = orderbook.get('orderbook', {}).get('no', [])
            
            if not yes_bids or not no_bids:
                return None
            
            current_yes = yes_bids[0][0] if yes_bids else yes_price
            current_no = no_bids[0][0] if no_bids else no_price
            
            # Check if pricing has caught up (mispricing closed)
            if side == 'yes':
                current_price = current_yes
                # Exit if price moved towards expected (caught up) or we're profitable
                if current_price >= position['expected_prob'] - 2 or current_price > entry_price + 2:
                    print(f"[BTC15MinStrategy] Exiting YES position: entry {entry_price}¢, current {current_price}¢, expected {position['expected_prob']:.1f}¢")
                    del self.active_positions[market_ticker]
                    return {
                        'action': 'sell',
                        'side': 'yes',
                        'count': 1,
                        'price': current_yes - 1  # Slightly below best bid to exit quickly
                    }
            
            elif side == 'no':
                current_price = current_no
                # Exit if price moved towards expected (caught up) or we're profitable
                if current_price >= position['expected_prob'] - 2 or current_price > entry_price + 2:
                    print(f"[BTC15MinStrategy] Exiting NO position: entry {entry_price}¢, current {current_price}¢, expected {position['expected_prob']:.1f}¢")
                    del self.active_positions[market_ticker]
                    return {
                        'action': 'sell',
                        'side': 'no',
                        'count': 1,
                        'price': current_no - 1
                    }
            
            return None
            
        except Exception as e:
            print(f"[BTC15MinStrategy] Error in _check_exit: {e}")
            return None


class WeatherDailyStrategy(TradingStrategy):
    """
    Advanced weather trading strategy using multi-source forecasts, probability distributions, and Edge/EV calculations
    Based on the weather trading edge guide
    """
    
    def __init__(self, client: KalshiClient):
        super().__init__(client)
        self.max_position_size = Config.MAX_POSITION_SIZE
        self.min_edge_threshold = 5.0  # Minimum edge % to trade (5% default)
        self.min_ev_threshold = 0.001  # Minimum EV in dollars to trade
        
        # Weather data aggregator (shared instance)
        self.weather_agg = WeatherDataAggregator()
        self.extract_threshold = extract_threshold_from_market
        
        # Cache for probability distributions (keyed by series_ticker + date)
        self.prob_cache = {}
    
    def should_trade(self, market: Dict) -> bool:
        """Check if this is a weather market we should trade"""
        series_ticker = market.get('series_ticker', '')
        if series_ticker not in Config.WEATHER_SERIES:
            return False
        
        if market.get('status') != 'open':
            return False
        
        # Check if market has sufficient volume
        if market.get('volume', 0) < 5:
            return False
        
        return True
    
    def get_trade_decision(self, market: Dict, orderbook: Dict) -> Optional[Dict]:
        """
        Advanced weather trading strategy:
        1. Collect multi-source forecasts
        2. Build probability distribution over temperature ranges
        3. Calculate edge and EV
        4. Trade when edge > threshold
        """
        try:
            series_ticker = market.get('series_ticker', '')
            
            # Extract target date from market (usually tomorrow or today)
            # Kalshi weather markets are typically for the next day
            target_date = datetime.now() + timedelta(days=1)
            
            # Extract temperature threshold from market title
            threshold = self.extract_threshold(market)
            if not threshold:
                # Can't determine threshold, skip
                return None
            
            # Get forecasts from all available sources
            forecasts = self.weather_agg.get_all_forecasts(series_ticker, target_date)
            
            if not forecasts:
                # No forecasts available, skip
                return None
            
            # Build temperature ranges (2-degree brackets as mentioned in guide)
            # Kalshi weather markets typically have 6 brackets
            # We'll create a fine-grained distribution first, then map to brackets
            mean_forecast = sum(forecasts) / len(forecasts)
            std_forecast = (sum((x - mean_forecast)**2 for x in forecasts) / len(forecasts))**0.5 if len(forecasts) > 1 else 2.0
            
            # Create temperature ranges around the forecast (2-degree brackets)
            temp_ranges = []
            base_temp = int(mean_forecast) - 10  # Start 10 degrees below
            for i in range(20):  # 20 brackets of 2 degrees each = 40 degree range
                temp_ranges.append((base_temp + i * 2, base_temp + (i + 1) * 2))
            
            # Build probability distribution
            prob_dist = self.weather_agg.build_probability_distribution(forecasts, temp_ranges)
            
            if not prob_dist:
                return None
            
            # Calculate our probability for this market
            # Determine if market is "above" or "below" threshold
            market_title = market.get('title', '').lower()
            is_above_market = 'above' in market_title or '>' in market_title
            
            # Calculate probability based on distribution
            our_prob = 0.0
            for (temp_min, temp_max), prob in prob_dist.items():
                if is_above_market:
                    if temp_min >= threshold:
                        our_prob += prob
                    elif temp_max > threshold:
                        # Partial overlap
                        overlap = (temp_max - threshold) / (temp_max - temp_min) if (temp_max - temp_min) > 0 else 0
                        our_prob += prob * overlap
                else:  # below market
                    if temp_max <= threshold:
                        our_prob += prob
                    elif temp_min < threshold:
                        # Partial overlap
                        overlap = (threshold - temp_min) / (temp_max - temp_min) if (temp_max - temp_min) > 0 else 0
                        our_prob += prob * overlap
            
            # Get market prices (reuse from earlier calculation if available)
            # Get orderbook data
            yes_bids = orderbook.get('orderbook', {}).get('yes', [])
            no_bids = orderbook.get('orderbook', {}).get('no', [])
            
            if not yes_bids or not no_bids:
                return None
            
            # Use market prices as fallback, but prefer orderbook
            yes_price = market.get('yes_price', 50)
            no_price = market.get('no_price', 50)
            best_yes_bid = yes_bids[0][0] if yes_bids else yes_price
            best_no_bid = no_bids[0][0] if no_bids else no_price
            
            # Calculate edge for YES side
            yes_edge = self.weather_agg.calculate_edge(our_prob, int(best_yes_bid))
            
            # Calculate edge for NO side (inverse probability)
            no_prob = 1.0 - our_prob
            no_edge = self.weather_agg.calculate_edge(no_prob, int(best_no_bid))
            
            # Calculate EV for both sides
            # For YES: if we win, we get $1 per contract, if we lose we lose the price we paid
            yes_stake = best_yes_bid / 100.0  # Convert cents to dollars
            yes_payout = 1.0  # $1 per contract if YES wins
            yes_ev = self.weather_agg.calculate_ev(our_prob, yes_payout, no_prob, yes_stake)
            
            # For NO: if we win, we get $1 per contract, if we lose we lose the price we paid
            no_stake = best_no_bid / 100.0
            no_payout = 1.0
            no_ev = self.weather_agg.calculate_ev(no_prob, no_payout, our_prob, no_stake)
            
            # Trade on the side with positive edge and EV
            if yes_edge >= self.min_edge_threshold and yes_ev >= self.min_ev_threshold:
                print(f"[WeatherStrategy] YES Edge: {yes_edge:.2f}%, EV: ${yes_ev:.4f}, Our Prob: {our_prob:.2%}, Market: {best_yes_bid}¢")
                return {
                    'action': 'buy',
                    'side': 'yes',
                    'count': min(1, self.max_position_size),
                    'price': best_yes_bid + 1,  # Slightly above best bid
                    'edge': yes_edge,
                    'ev': yes_ev
                }
            elif no_edge >= self.min_edge_threshold and no_ev >= self.min_ev_threshold:
                print(f"[WeatherStrategy] NO Edge: {no_edge:.2f}%, EV: ${no_ev:.4f}, Our Prob: {no_prob:.2%}, Market: {best_no_bid}¢")
                return {
                    'action': 'buy',
                    'side': 'no',
                    'count': min(1, self.max_position_size),
                    'price': best_no_bid + 1,
                    'edge': no_edge,
                    'ev': no_ev
                }
            
            return None
            
        except Exception as e:
            print(f"[WeatherStrategy] Error in get_trade_decision: {e}")
            import traceback
            traceback.print_exc()
            return None


class StrategyManager:
    """Manages multiple trading strategies"""
    
    def __init__(self, client: KalshiClient, btc_tracker: Optional[BTCPriceTracker] = None):
        self.client = client
        self.strategies = []
        
        # Share BTC tracker across strategies for efficiency
        if 'btc_15m' in Config.ENABLED_STRATEGIES:
            self.strategies.append(BTC15MinStrategy(client, btc_tracker=btc_tracker))
        if 'btc_hourly' in Config.ENABLED_STRATEGIES:
            self.strategies.append(BTCHourlyStrategy(client, btc_tracker=btc_tracker))
        
        if 'weather_daily' in Config.ENABLED_STRATEGIES:
            self.strategies.append(WeatherDailyStrategy(client))
    
    def evaluate_market(self, market: Dict) -> List[Dict]:
        """Evaluate a market with all strategies and return trade decisions"""
        decisions = []
        
        # Only fetch orderbook once per market, share across strategies
        orderbook = None
        orderbook_fetched = False
        
        for strategy in self.strategies:
            if strategy.should_trade(market):
                try:
                    # Fetch orderbook only once per market (with caching)
                    if not orderbook_fetched:
                        orderbook = self.client.get_market_orderbook(market['ticker'], use_cache=True)
                        orderbook_fetched = True
                    
                    decision = strategy.get_trade_decision(market, orderbook)
                    
                    if decision:
                        decision['strategy'] = strategy.name
                        decision['market_ticker'] = market['ticker']
                        decisions.append(decision)
                except Exception as e:
                    print(f"Error evaluating market {market['ticker']} with {strategy.name}: {e}")
        
        return decisions
