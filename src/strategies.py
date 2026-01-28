import time
import uuid
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from .kalshi_client import KalshiClient
from .config import Config
from .weather_data import WeatherDataAggregator, extract_threshold_from_market

logger = logging.getLogger(__name__)


class TradingStrategy:
    """Base class for trading strategies"""
    
    def __init__(self, client: KalshiClient):
        # Don't call super() - this is the base class
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
            # Set price for the side we're trading (YES or NO)
            price = decision.get('price', 0)
            if decision['side'] == 'yes':
                yes_price = price
                no_price = None
            else:
                yes_price = None
                no_price = price
            
            order = self.client.create_order(
                ticker=market_ticker,
                action=decision['action'],
                side=decision['side'],
                count=decision['count'],
                order_type='limit',
                yes_price=yes_price,
                no_price=no_price,
                client_order_id=str(uuid.uuid4())
            )
            
            # Enhanced trade notification
            order_id = order.get('order_id', 'N/A')
            action = decision['action']
            side = decision['side']
            count = decision['count']
            price = decision.get('price', 'N/A')
            
            trade_msg = f"🔄 TRADE EXECUTED: {action.upper()} {count} {side.upper()} @ {price}¢ | Order: {order_id} | Market: {market_ticker}"
            
            # Log to console and file
            logger.info("="*70)
            logger.info(trade_msg)
            logger.info("="*70)
            
            # Log to file
            self._log_trade(trade_msg, order, decision, market_ticker)
            
            # Don't send notification on order placement - only when order fills
            # Notification will be sent when order status changes to 'filled'
            
            return order
        except Exception as e:
            error_msg = f"Error placing order: {e}"
            logger.error(error_msg, exc_info=True)
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
            logger.error(f"Error logging trade: {e}")
    
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


# BTC strategies removed - focusing on weather markets only
# (Removed ~550 lines of commented BTC code for cleaner codebase)

class WeatherDailyStrategy(TradingStrategy):
    """
    Advanced weather trading strategy using multi-source forecasts, probability distributions, and Edge/EV calculations
    Based on the weather trading edge guide
    """
    
    def __init__(self, client: KalshiClient):
        super().__init__(client)
        self.max_position_size = Config.MAX_POSITION_SIZE
        
        # Conservative strategy parameters (from Config)
        self.min_edge_threshold = Config.MIN_EDGE_THRESHOLD
        self.min_ev_threshold = Config.MIN_EV_THRESHOLD
        
        # Longshot strategy parameters (from Config)
        self.longshot_enabled = Config.LONGSHOT_ENABLED
        self.longshot_max_price = Config.LONGSHOT_MAX_PRICE
        self.longshot_min_edge = Config.LONGSHOT_MIN_EDGE
        self.longshot_min_prob = Config.LONGSHOT_MIN_PROB
        self.longshot_position_multiplier = Config.LONGSHOT_POSITION_MULTIPLIER
        
        # Weather data aggregator (shared instance)
        self.weather_agg = WeatherDataAggregator()
        self.extract_threshold = extract_threshold_from_market
        
        # Cache for probability distributions (keyed by series_ticker + date)
        self.prob_cache = {}
        
        # Track active positions for exit logic
        self.active_positions: Dict[str, Dict] = {}  # {market_ticker: position_info}
    
    def _extract_market_date(self, market: Dict) -> Optional[datetime]:
        """Extract the target date from market ticker or title"""
        ticker = market.get('ticker', '')
        title = market.get('title', '')
        
        # Method 1: Parse from ticker (e.g., KXHIGHNY-26JAN28-T26 -> 26JAN28)
        # Format is YYMMMDD: 26JAN28 = Year 2026, Month JAN, Day 28 = Jan 28, 2026
        if '-' in ticker:
            parts = ticker.split('-')
            if len(parts) >= 2:
                date_str = parts[1]  # e.g., "26JAN28"
                try:
                    if len(date_str) >= 7:  # YYMMMDD = 7 chars
                        year_str = date_str[:2]  # "26"
                        month_str = date_str[2:5].upper()  # "JAN"
                        day_str = date_str[5:]  # "28"
                        
                        # Map month abbreviations
                        month_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                                   'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
                        
                        if month_str in month_map:
                            year = 2000 + int(year_str)  # "26" -> 2026
                            month = month_map[month_str]
                            day = int(day_str)
                            target = datetime(year, month, day)
                            return target
                except (ValueError, KeyError, IndexError):
                    pass
        
        # Method 2: Parse from title (e.g., "on Jan 28, 2026")
        import re
        date_patterns = [
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})',  # "Jan 28, 2026"
            r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})',  # "01/28/2026" or "01-28-2026"
        ]
        
        month_map = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
        
        for pattern in date_patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                try:
                    if 'Jan|Feb' in pattern:  # First pattern
                        month_name, day, year = match.groups()
                        month = month_map[month_name.lower()]
                        return datetime(int(year), month, int(day))
                    else:  # Second pattern
                        parts = match.groups()
                        if len(parts) == 3:
                            # Could be MM/DD/YYYY or DD/MM/YYYY - try both
                            try:
                                month, day, year = map(int, parts)
                                # Try MM/DD/YYYY first (US format)
                                return datetime(year, month, day)
                            except ValueError:
                                pass
                except (ValueError, KeyError):
                    continue
        
        # Method 3: Check if title says "today" or "tomorrow"
        title_lower = title.lower()
        today = datetime.now()
        if 'today' in title_lower:
            return today
        elif 'tomorrow' in title_lower:
            return today + timedelta(days=1)
        
        # Fallback: assume tomorrow (original behavior)
        logger.warning(f"Could not parse date from market, defaulting to tomorrow")
        return today + timedelta(days=1)
    
    def should_trade(self, market: Dict) -> bool:
        """Check if this is a weather market we should trade"""
        # Try multiple ways to get series ticker (Kalshi API may vary)
        series_ticker = market.get('series_ticker') or market.get('series_ticker_symbol') or ''
        
        # Also check if ticker starts with weather series prefix
        ticker = market.get('ticker', '')
        is_weather = False
        if series_ticker in Config.WEATHER_SERIES:
            is_weather = True
        elif any(ticker.startswith(prefix) for prefix in ['KXHIGH', 'KXLOW']):
            is_weather = True
        
        if not is_weather:
            return False
        
        # Status can be 'open' or 'active' (both mean tradeable)
        status = market.get('status', '').lower()
        if status not in ['open', 'active']:
            return False
        
        # Check if market has sufficient volume (liquidity requirement)
        if market.get('volume', 0) < Config.MIN_MARKET_VOLUME:
            return False
        
        return True
    
    def get_trade_decision(self, market: Dict, orderbook: Dict) -> Optional[Dict]:
        """
        Advanced weather trading strategy:
        1. Collect multi-source forecasts
        2. Build probability distribution over temperature ranges
        3. Calculate edge and EV
        4. Trade when edge > threshold
        
        Also checks for existing positions and handles exit logic.
        """
        try:
            market_ticker = market.get('ticker', '')
            
            # Check if we have an active position to exit
            if market_ticker in self.active_positions:
                exit_decision = self._check_exit(market, orderbook, market_ticker)
                if exit_decision:
                    return exit_decision
            # Get series ticker - try multiple fields, fallback to ticker prefix
            series_ticker = market.get('series_ticker') or market.get('series_ticker_symbol') or ''
            ticker = market.get('ticker', '')
            
            # If series_ticker is empty, extract from ticker (e.g., KXHIGHNY-26JAN28-T26 -> KXHIGHNY)
            if not series_ticker and ticker:
                for weather_series in Config.WEATHER_SERIES:
                    if ticker.startswith(weather_series):
                        series_ticker = weather_series
                        break
            
            if not series_ticker:
                logger.warning(f"Could not determine series for market: {ticker}")
                return None
            
            # Extract target date from market ticker or title
            # Ticker format: KXHIGHNY-26JAN28-T26 (date is 26JAN28 = Jan 28, 2026)
            # Title format: "Will the **high temp in NYC** be >26° on Jan 28, 2026?"
            target_date = self._extract_market_date(market)
            if not target_date:
                logger.warning(f"Could not extract date from market: {ticker}")
                return None
            
            # Verify date is reasonable (not too far in past/future)
            today = datetime.now().date()
            market_date = target_date.date()
            days_diff = (market_date - today).days
            
            max_days = Config.MAX_MARKET_DATE_DAYS
            if days_diff < -1 or days_diff > max_days:  # Allow -1 (yesterday) to max_days
                logger.warning(f"Market date {market_date} is too far from today ({days_diff} days), skipping")
                return None
            
            # Extract temperature threshold from market title
            threshold = self.extract_threshold(market)
            if not threshold:
                # Can't determine threshold, skip
                logger.warning(f"Could not extract threshold from market: {market.get('title', 'unknown')}")
                return None
            
            # Get forecasts from all available sources
            forecasts = self.weather_agg.get_all_forecasts(series_ticker, target_date)
            
            if not forecasts:
                # No forecasts available, skip
                logger.warning(f"No forecasts for {series_ticker} on {target_date.strftime('%Y-%m-%d')}")
                return None
            
            # Build temperature ranges (2-degree brackets as mentioned in guide)
            # Kalshi weather markets typically have 6 brackets
            # We'll create a fine-grained distribution first, then map to brackets
            mean_forecast = sum(forecasts) / len(forecasts)
            
            # Create temperature ranges around the forecast (2-degree brackets)
            temp_ranges = []
            base_temp = int(mean_forecast) - 10  # Start 10 degrees below
            for i in range(20):  # 20 brackets of 2 degrees each = 40 degree range
                temp_ranges.append((base_temp + i * 2, base_temp + (i + 1) * 2))
            
            # Build probability distribution with dynamic std and historical data
            prob_dist = self.weather_agg.build_probability_distribution(
                forecasts, temp_ranges, series_ticker, target_date
            )
            
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
            # Kalshi orderbook format: [[price, quantity], ...] sorted by price ASCENDING
            # First entries [0] = lowest bids (buyers paying least)
            # Last entries [-1] = highest bids (buyers paying most) = best bid
            # For asks: YES ask = 100 - NO bid, NO ask = 100 - YES bid
            yes_orders = orderbook.get('orderbook', {}).get('yes', [])
            no_orders = orderbook.get('orderbook', {}).get('no', [])
            
            if not yes_orders or not no_orders:
                return None
            
            # Use market prices as fallback
            yes_market_price = market.get('yes_price', 50)
            no_market_price = market.get('no_price', 50)
            
            # For BUYING: we need to pay the ASK price (what sellers want)
            # ASK = lowest price someone will sell at = last entry in sorted orderbook
            # BID = highest price someone will buy at = first entry in sorted orderbook
            best_yes_ask = yes_orders[-1][0] if len(yes_orders) > 0 else yes_market_price  # Lowest YES ask
            best_no_ask = no_orders[-1][0] if len(no_orders) > 0 else no_market_price    # Lowest NO ask
            
            # Also get bids for reference (what other buyers are paying)
            # Arrays are sorted ASCENDING, so best bid (highest) is LAST element [-1]
            best_yes_bid = yes_orders[-1][0] if yes_orders else yes_market_price
            best_no_bid = no_orders[-1][0] if no_orders else no_market_price
            
            # Calculate edge for YES side using ASK price (what we'd actually pay)
            yes_edge = self.weather_agg.calculate_edge(our_prob, int(best_yes_ask))
            
            # Calculate edge for NO side (inverse probability) using ASK price
            no_prob = 1.0 - our_prob
            no_edge = self.weather_agg.calculate_edge(no_prob, int(best_no_ask))
            
            # Calculate confidence intervals for probability estimates
            # For "above" markets, YES = temp > threshold
            # For "below" markets, YES = temp < threshold
            prob_ci_yes, (ci_lower_yes, ci_upper_yes) = self.weather_agg.calculate_confidence_interval(
                forecasts, threshold, is_above=is_above_market
            )
            prob_ci_no = 1.0 - prob_ci_yes
            ci_lower_no = 1.0 - ci_upper_yes
            ci_upper_no = 1.0 - ci_lower_yes
            
            # Estimate fill prices based on orderbook depth (for position sizing)
            estimated_yes_price = self.weather_agg.estimate_fill_price(orderbook, 'yes', 
                                                                       self.max_position_size * 5)
            estimated_no_price = self.weather_agg.estimate_fill_price(orderbook, 'no', 
                                                                      self.max_position_size * 5)
            
            # Use estimated fill price if significantly different from best ask
            # (indicates we might experience slippage)
            yes_price_for_ev = estimated_yes_price if abs(estimated_yes_price - best_yes_ask) > 2 else best_yes_ask
            no_price_for_ev = estimated_no_price if abs(estimated_no_price - best_no_ask) > 2 else best_no_ask
            
            # Calculate EV for both sides using estimated fill prices and INCLUDING FEES
            # For YES: if we win, we get $1 per contract, if we lose we lose what we paid
            yes_stake = yes_price_for_ev / 100.0  # Convert cents to dollars
            yes_payout = 1.0  # $1 per contract if YES wins
            yes_ev = self.weather_agg.calculate_ev(our_prob, yes_payout, no_prob, yes_stake, 
                                                   include_fees=True, fee_rate=0.05)
            
            # For NO: if we win, we get $1 per contract, if we lose we lose what we paid
            no_stake = no_price_for_ev / 100.0
            no_payout = 1.0
            no_ev = self.weather_agg.calculate_ev(no_prob, no_payout, our_prob, no_stake,
                                                  include_fees=True, fee_rate=0.05)
            
            # DUAL STRATEGY: Check both conservative and longshot modes
            
            # LONGSHOT MODE: Hunt for extreme mispricings (0.1-10% odds with massive edges)
            # Inspired by successful Polymarket bot: buy cheap certainty
            if self.longshot_enabled:
                # Check YES side for longshot opportunity
                # Use ASK price to check if it's cheap enough
                if (best_yes_ask <= self.longshot_max_price and 
                    our_prob >= (self.longshot_min_prob / 100.0) and 
                    yes_edge >= self.longshot_min_edge):
                    
                    # Calculate position size using Kelly Criterion (if high confidence) or fixed multiplier
                    # Check confidence: only use Kelly if CI doesn't overlap with market price
                    use_kelly = (ci_lower_yes > best_yes_ask / 100.0 or ci_upper_yes < best_yes_ask / 100.0)
                    
                    if use_kelly and len(forecasts) >= 2:
                        # Use Kelly Criterion for optimal position sizing
                        payout_ratio = 1.0 / (best_yes_ask / 100.0)  # Payout / Stake
                        kelly_fraction = self.weather_agg.kelly_fraction(our_prob, payout_ratio, fractional=0.5)
                        # Get portfolio value for Kelly calculation
                        portfolio = self.client.get_portfolio()
                        portfolio_value = (portfolio.get('balance', 0) + portfolio.get('portfolio_value', 0)) / 100.0
                        kelly_position = int(kelly_fraction * portfolio_value / (best_yes_ask / 100.0))
                        base_position = min(kelly_position, self.max_position_size * 5)
                    else:
                        # Use fixed multiplier for longshot
                        base_position = min(self.max_position_size * self.longshot_position_multiplier, 
                                           self.max_position_size * 5)  # Cap at 5x
                    
                    # Cap by contract count (25 contracts)
                    contract_cap = Config.MAX_CONTRACTS_PER_MARKET
                    # Cap by dollar amount ($3.00 = 300 cents)
                    dollar_cap_contracts = int(Config.MAX_DOLLARS_PER_MARKET * 100 / best_yes_ask) if best_yes_ask > 0 else contract_cap
                    position_size = min(base_position, contract_cap, dollar_cap_contracts)
                    
                    confidence_str = f"CI: [{ci_lower_yes:.1%}, {ci_upper_yes:.1%}]" if use_kelly else ""
                    logger.info(f"🎯 LONGSHOT YES: Ask {best_yes_ask}¢ (cheap!), Our Prob: {our_prob:.1%} {confidence_str}, Edge: {yes_edge:.1f}%, EV: ${yes_ev:.4f} (with fees)")
                    logger.info(f"💰 Asymmetric play: Risk ${best_yes_ask/100 * position_size:.2f} for ${1.00 * position_size:.2f} payout ({(100/best_yes_ask):.1f}x)")
                    
                    # Record position for exit logic
                    self.active_positions[market_ticker] = {
                        'side': 'yes',
                        'entry_price': best_yes_ask,
                        'entry_time': datetime.now(),
                        'count': position_size,
                        'edge': yes_edge,
                        'ev': yes_ev,
                        'strategy_mode': 'longshot'
                    }
                    
                    return {
                        'action': 'buy',
                        'side': 'yes',
                        'count': position_size,
                        'price': best_yes_ask,  # Pay the ask price to get filled
                        'edge': yes_edge,
                        'ev': yes_ev,
                        'strategy_mode': 'longshot'
                    }
                
                # Check NO side for longshot opportunity
                # Use ASK price to check if it's cheap enough
                if (best_no_ask <= self.longshot_max_price and 
                    no_prob >= (self.longshot_min_prob / 100.0) and 
                    no_edge >= self.longshot_min_edge):
                    
                    # Calculate position size using Kelly Criterion (if high confidence) or fixed multiplier
                    # Check confidence: only use Kelly if CI doesn't overlap with market price
                    use_kelly = (ci_lower_no > best_no_ask / 100.0 or ci_upper_no < best_no_ask / 100.0)
                    
                    if use_kelly and len(forecasts) >= 2:
                        # Use Kelly Criterion for optimal position sizing
                        payout_ratio = 1.0 / (best_no_ask / 100.0)  # Payout / Stake
                        kelly_fraction = self.weather_agg.kelly_fraction(no_prob, payout_ratio, fractional=0.5)
                        # Get portfolio value for Kelly calculation
                        portfolio = self.client.get_portfolio()
                        portfolio_value = (portfolio.get('balance', 0) + portfolio.get('portfolio_value', 0)) / 100.0
                        kelly_position = int(kelly_fraction * portfolio_value / (best_no_ask / 100.0))
                        base_position = min(kelly_position, self.max_position_size * 5)
                    else:
                        # Use fixed multiplier for longshot
                        base_position = min(self.max_position_size * self.longshot_position_multiplier, 
                                           self.max_position_size * 5)  # Cap at 5x
                    
                    # Cap by contract count (25 contracts)
                    contract_cap = Config.MAX_CONTRACTS_PER_MARKET
                    # Cap by dollar amount ($3.00 = 300 cents)
                    dollar_cap_contracts = int(Config.MAX_DOLLARS_PER_MARKET * 100 / best_no_ask) if best_no_ask > 0 else contract_cap
                    position_size = min(base_position, contract_cap, dollar_cap_contracts)
                    
                    confidence_str = f"CI: [{ci_lower_no:.1%}, {ci_upper_no:.1%}]" if use_kelly else ""
                    logger.info(f"🎯 LONGSHOT NO: Ask {best_no_ask}¢ (cheap!), Our Prob: {no_prob:.1%} {confidence_str}, Edge: {no_edge:.1f}%, EV: ${no_ev:.4f} (with fees)")
                    logger.info(f"💰 Asymmetric play: Risk ${best_no_ask/100 * position_size:.2f} for ${1.00 * position_size:.2f} payout ({(100/best_no_ask):.1f}x)")
                    
                    # Record position for exit logic
                    self.active_positions[market_ticker] = {
                        'side': 'no',
                        'entry_price': best_no_ask,
                        'entry_time': datetime.now(),
                        'count': position_size,
                        'edge': no_edge,
                        'ev': no_ev,
                        'strategy_mode': 'longshot'
                    }
                    
                    return {
                        'action': 'buy',
                        'side': 'no',
                        'count': position_size,
                        'price': best_no_ask,  # Pay the ask price to get filled
                        'edge': no_edge,
                        'ev': no_ev,
                        'strategy_mode': 'longshot'
                    }
            
            # CONSERVATIVE MODE: Standard edge/EV trading (high win rate)
            # Only trade if confidence interval doesn't overlap with market price (high confidence)
            high_confidence_yes = (ci_lower_yes > best_yes_ask / 100.0 or ci_upper_yes < best_yes_ask / 100.0)
            high_confidence_no = (ci_lower_no > best_no_ask / 100.0 or ci_upper_no < best_no_ask / 100.0)
            
            if yes_edge >= self.min_edge_threshold and yes_ev >= self.min_ev_threshold and high_confidence_yes:
                # Calculate position size with dual cap: $3 OR 25 contracts, whichever is hit first
                # Optionally use Kelly Criterion for conservative trades with very high confidence
                if len(forecasts) >= 2 and our_prob > 0.7:  # Only for high-probability trades
                    payout_ratio = 1.0 / (best_yes_ask / 100.0)
                    kelly_fraction = self.weather_agg.kelly_fraction(our_prob, payout_ratio, fractional=0.25)  # Very conservative
                    portfolio = self.client.get_portfolio()
                    portfolio_value = (portfolio.get('balance', 0) + portfolio.get('portfolio_value', 0)) / 100.0
                    kelly_position = int(kelly_fraction * portfolio_value / (best_yes_ask / 100.0))
                    base_position = min(max(kelly_position, self.max_position_size), self.max_position_size * 2)
                else:
                    base_position = self.max_position_size
                
                contract_cap = Config.MAX_CONTRACTS_PER_MARKET
                dollar_cap_contracts = int(Config.MAX_DOLLARS_PER_MARKET * 100 / best_yes_ask) if best_yes_ask > 0 else contract_cap
                position_size = min(base_position, contract_cap, dollar_cap_contracts)
                
                logger.info(f"✓ Conservative YES: Edge: {yes_edge:.2f}%, EV: ${yes_ev:.4f} (with fees), Our Prob: {our_prob:.2%} CI: [{ci_lower_yes:.1%}, {ci_upper_yes:.1%}], Ask: {best_yes_ask}¢")
                
                # Record position for exit logic
                self.active_positions[market_ticker] = {
                    'side': 'yes',
                    'entry_price': best_yes_ask,
                    'entry_time': datetime.now(),
                    'count': position_size,
                    'edge': yes_edge,
                    'ev': yes_ev,
                    'strategy_mode': 'conservative'
                }
                
                return {
                    'action': 'buy',
                    'side': 'yes',
                    'count': position_size,
                    'price': best_yes_ask,  # Pay the ask price to get filled
                    'edge': yes_edge,
                    'ev': yes_ev,
                    'strategy_mode': 'conservative'
                }
            elif no_edge >= self.min_edge_threshold and no_ev >= self.min_ev_threshold and high_confidence_no:
                # Calculate position size with dual cap: $3 OR 25 contracts, whichever is hit first
                # Optionally use Kelly Criterion for conservative trades with very high confidence
                if len(forecasts) >= 2 and no_prob > 0.7:  # Only for high-probability trades
                    payout_ratio = 1.0 / (best_no_ask / 100.0)
                    kelly_fraction = self.weather_agg.kelly_fraction(no_prob, payout_ratio, fractional=0.25)  # Very conservative
                    portfolio = self.client.get_portfolio()
                    portfolio_value = (portfolio.get('balance', 0) + portfolio.get('portfolio_value', 0)) / 100.0
                    kelly_position = int(kelly_fraction * portfolio_value / (best_no_ask / 100.0))
                    base_position = min(max(kelly_position, self.max_position_size), self.max_position_size * 2)
                else:
                    base_position = self.max_position_size
                
                contract_cap = Config.MAX_CONTRACTS_PER_MARKET
                dollar_cap_contracts = int(Config.MAX_DOLLARS_PER_MARKET * 100 / best_no_ask) if best_no_ask > 0 else contract_cap
                position_size = min(base_position, contract_cap, dollar_cap_contracts)
                
                logger.info(f"✓ Conservative NO: Edge: {no_edge:.2f}%, EV: ${no_ev:.4f} (with fees), Our Prob: {no_prob:.2%} CI: [{ci_lower_no:.1%}, {ci_upper_no:.1%}], Ask: {best_no_ask}¢")
                
                # Record position for exit logic
                self.active_positions[market_ticker] = {
                    'side': 'no',
                    'entry_price': best_no_ask,
                    'entry_time': datetime.now(),
                    'count': position_size,
                    'edge': no_edge,
                    'ev': no_ev,
                    'strategy_mode': 'conservative'
                }
                
                return {
                    'action': 'buy',
                    'side': 'no',
                    'count': position_size,
                    'price': best_no_ask,  # Pay the ask price to get filled
                    'edge': no_edge,
                    'ev': no_ev,
                    'strategy_mode': 'conservative'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in get_trade_decision: {e}", exc_info=True)
            return None
    
    def _check_exit(self, market: Dict, orderbook: Dict, market_ticker: str) -> Optional[Dict]:
        """
        Check if we should exit an active weather position
        
        Exit conditions:
        - Edge disappears (re-evaluate and edge < threshold)
        - Take profit (price moved significantly in our favor)
        - Stop loss (price moved significantly against us)
        
        Args:
            market: Market data from Kalshi
            orderbook: Current orderbook data
            market_ticker: Market ticker symbol
            
        Returns:
            Exit decision dict or None
        """
        try:
            position = self.active_positions.get(market_ticker)
            if not position:
                return None
            
            side = position['side']
            entry_price = position.get('entry_price', 0)
            entry_time = position.get('entry_time')
            entry_edge = position.get('edge', 0)
            
            # Don't exit too quickly (at least 5 minutes for daily markets)
            if entry_time and (datetime.now() - entry_time).total_seconds() < 300:
                return None
            
            # Get current market prices
            yes_orders = orderbook.get('orderbook', {}).get('yes', [])
            no_orders = orderbook.get('orderbook', {}).get('no', [])
            
            if not yes_orders or not no_orders:
                return None
            
            # Calculate current ask prices
            best_no_bid = no_orders[-1][0] if no_orders else 50
            best_yes_bid = yes_orders[-1][0] if yes_orders else 50
            current_yes_ask = 100 - best_no_bid
            current_no_ask = 100 - best_yes_bid
            
            current_ask = current_yes_ask if side == 'yes' else current_no_ask
            
            # Calculate current profit/loss
            if side == 'yes':
                # If YES wins, we get $1 per contract
                # Current value = current_yes_ask / 100
                current_value = current_ask / 100.0
                entry_cost = entry_price / 100.0
                profit_pct = ((current_value - entry_cost) / entry_cost) * 100 if entry_cost > 0 else 0
            else:
                # If NO wins, we get $1 per contract
                current_value = current_ask / 100.0
                entry_cost = entry_price / 100.0
                profit_pct = ((current_value - entry_cost) / entry_cost) * 100 if entry_cost > 0 else 0
            
            # Exit condition 1: Take profit (price moved 20%+ in our favor)
            if profit_pct >= 20:
                logger.info(f"Taking profit on {market_ticker}: {side.upper()} entry {entry_price}¢ -> current {current_ask}¢ ({profit_pct:.1f}% profit)")
                del self.active_positions[market_ticker]
                return {
                    'action': 'sell',
                    'side': side,
                    'count': position.get('count', 1),
                    'price': int(current_ask - 1),  # Slightly below ask to exit quickly
                    'reason': 'take_profit'
                }
            
            # Exit condition 2: Stop loss (price moved 30%+ against us)
            if profit_pct <= -30:
                logger.warning(f"Stop loss triggered on {market_ticker}: {side.upper()} entry {entry_price}¢ -> current {current_ask}¢ ({profit_pct:.1f}% loss)")
                del self.active_positions[market_ticker]
                return {
                    'action': 'sell',
                    'side': side,
                    'count': position.get('count', 1),
                    'price': int(current_ask - 1),
                    'reason': 'stop_loss'
                }
            
            # Exit condition 3: Edge disappeared (re-evaluate market)
            # Re-run strategy evaluation to check if edge still exists
            try:
                decisions = self.get_trade_decision(market, orderbook)
                # If we get a decision for the same side, edge still exists
                # If no decision or different side, edge is gone
                edge_still_exists = False
                if decisions:
                    for decision in decisions if isinstance(decisions, list) else [decisions]:
                        if decision and decision.get('side') == side:
                            current_edge = decision.get('edge', 0)
                            # Edge must still meet minimum threshold
                            if decision.get('strategy_mode') == 'longshot':
                                edge_still_exists = current_edge >= self.longshot_min_edge
                            else:
                                edge_still_exists = current_edge >= self.min_edge_threshold
                            break
                
                if not edge_still_exists and entry_edge > 0:
                    logger.info(f"Edge disappeared on {market_ticker}: {side.upper()} (was {entry_edge:.1f}%), exiting")
                    del self.active_positions[market_ticker]
                    return {
                        'action': 'sell',
                        'side': side,
                        'count': position.get('count', 1),
                        'price': int(current_ask - 1),
                        'reason': 'edge_gone'
                    }
            except Exception as e:
                logger.debug(f"Could not re-evaluate edge for {market_ticker}: {e}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error in _check_exit for {market_ticker}: {e}", exc_info=True)
            return None


class StrategyManager:
    """Manages multiple trading strategies"""
    
    def __init__(self, client: KalshiClient, btc_tracker=None):
        self.client = client
        self.strategies = []
        
        # Focus on weather markets only
        if 'weather_daily' in Config.ENABLED_STRATEGIES:
            self.strategies.append(WeatherDailyStrategy(client))
    
    def evaluate_market(self, market: Dict, orderbook: Optional[Dict] = None) -> List[Dict]:
        """Evaluate a market with all strategies and return trade decisions"""
        decisions = []
        
        # Only fetch orderbook once per market, share across strategies
        orderbook_fetched = orderbook is not None
        
        for strategy in self.strategies:
            if strategy.should_trade(market):
                try:
                    # Fetch orderbook only once per market (with caching) if not provided
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
