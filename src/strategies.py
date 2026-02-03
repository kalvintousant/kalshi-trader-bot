import time
import uuid
import logging
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from .kalshi_client import KalshiClient
from .config import Config
from .weather_data import WeatherDataAggregator, extract_threshold_from_market
from .market_maker import MarketMaker, SmartOrderRouter
from .portfolio_risk import CorrelationAwareRisk
from .backtester import get_data_store

logger = logging.getLogger(__name__)


class TradingStrategy:
    """Base class for trading strategies"""

    def __init__(self, client: KalshiClient):
        # Don't call super() - this is the base class
        self.client = client
        self.name = self.__class__.__name__

        # Data store for backtesting (shared instance)
        self.data_store = get_data_store()
    
    def _has_resting_order_on_ticker(self, ticker: str) -> bool:
        """
        Check if we already have a resting order on this EXACT ticker.

        This prevents placing duplicate orders on the same ticker every scan cycle.
        The base market limit check prevents over-exposure to a market, but this
        check prevents order accumulation on the same specific ticker.

        Args:
            ticker: The exact ticker to check (e.g., KXHIGHLAX-26JAN28-B69.5)

        Returns:
            True if there's already a resting order on this exact ticker
        """
        try:
            orders = self.client.get_orders(status='resting', use_cache=False)
            for order in orders:
                if order.get('ticker') == ticker:
                    return True
            return False
        except Exception as e:
            logger.warning(f"Could not check resting orders for {ticker}: {e}")
            # Return True (assume order exists) to be safe and prevent duplicates
            return True

    def _get_market_exposure(self, market_ticker: str) -> Dict:
        """
        Calculate total exposure (contracts + dollars) on a specific BASE MARKET.
        Includes both current positions AND resting (open) orders.

        IMPORTANT: Tracks at BASE MARKET level (e.g., KXHIGHMIA-26FEB01)
        not per-threshold (e.g., KXHIGHMIA-26FEB01-B51.5).
        This means all temperature thresholds for a market are combined.

        Uses get_positions() for actual holdings (not get_fills which is historical).
        Uses use_cache=False for resting orders to get fresh data for accurate limit checks.
        """
        try:
            # Extract base market ticker (remove threshold suffix)
            # e.g., KXHIGHMIA-26FEB01-B51.5 -> KXHIGHMIA-26FEB01
            # e.g., KXHIGHMIA-26FEB01-T64 -> KXHIGHMIA-26FEB01
            parts = market_ticker.split('-')
            if len(parts) >= 3:
                base_market = '-'.join(parts[:2])  # Take series + date
            else:
                base_market = market_ticker
            
            total_contracts = 0
            total_dollars = 0.0

            # Get ACTUAL current positions (not historical fills)
            # Check ALL thresholds for this base market
            try:
                positions = self.client.get_positions()
                for position in positions:
                    pos_ticker = position.get('ticker', '')
                    # Check if this position belongs to our base market
                    pos_parts = pos_ticker.split('-')
                    if len(pos_parts) >= 2:
                        pos_base = '-'.join(pos_parts[:2])
                        if pos_base == base_market:
                            # 'position' field is the net contract count (can be negative for short)
                            contracts = abs(position.get('position', 0))
                            total_contracts += contracts

                            # Use market_exposure from API (actual dollars at risk)
                            # This is the real cost basis, not an estimate
                            market_exposure = position.get('market_exposure', 0)
                            # market_exposure is in cents, convert to dollars
                            cost_dollars = market_exposure / 100.0
                            total_dollars += cost_dollars
            except Exception as e:
                logger.debug(f"Could not fetch positions for {base_market}: {e}")

            # Get resting (open) orders - use_cache=False for fresh data!
            # This is critical: stale cache was causing duplicate orders
            try:
                orders = self.client.get_orders(status='resting', use_cache=False)
                for order in orders:
                    order_ticker = order.get('ticker', '')
                    # Check if this order belongs to our base market
                    order_parts = order_ticker.split('-')
                    if len(order_parts) >= 2:
                        order_base = '-'.join(order_parts[:2])
                        if order_base == base_market:
                            remaining = order.get('remaining_count', 0)
                            total_contracts += remaining

                            side = order.get('side', '')
                            if side == 'yes':
                                price = order.get('yes_price', 0)
                            else:
                                price = order.get('no_price', 0)
                            total_dollars += (remaining * price) / 100.0
            except Exception as e:
                logger.debug(f"Could not fetch orders for {base_market}: {e}")

            return {
                'total_contracts': total_contracts,
                'total_dollars': total_dollars,
                'base_market': base_market  # Include for logging
            }

        except Exception as e:
            logger.error(f"Error getting market exposure for {market_ticker}: {e}", exc_info=True)
            # Return safe defaults (assume at limit to prevent over-trading)
            return {
                'total_contracts': Config.MAX_CONTRACTS_PER_MARKET,
                'total_dollars': Config.MAX_DOLLARS_PER_MARKET,
                'base_market': market_ticker
            }
    
    def should_trade(self, market: Dict) -> bool:
        """Determine if we should trade this market"""
        raise NotImplementedError
    
    def get_trade_decision(self, market: Dict, orderbook: Dict) -> Optional[Dict]:
        """Get trading decision: {'action': 'buy'/'sell', 'side': 'yes'/'no', 'count': int, 'price': int}"""
        raise NotImplementedError
    
    def execute_trade(self, decision: Dict, market_ticker: str) -> Optional[Dict]:
        """Execute a trade"""
        try:
            # CRITICAL: Re-check exposure limits RIGHT BEFORE placing order
            # This prevents multiple strategies/scans from over-trading the same market
            existing_exposure = self._get_market_exposure(market_ticker)
            existing_contracts = existing_exposure['total_contracts']
            existing_dollars = existing_exposure['total_dollars']
            base_market = existing_exposure.get('base_market', market_ticker)
            
            # Check if we would exceed limits with this trade
            new_count = decision.get('count', 0)
            new_price = decision.get('price', 0)
            new_dollars = (new_count * new_price) / 100.0
            
            # Never buy at 100¢ (no value)
            if new_price > Config.MAX_BUY_PRICE_CENTS:
                logger.warning(f"⛔ BLOCKED trade on {market_ticker}: price {new_price}¢ > MAX_BUY_PRICE_CENTS ({Config.MAX_BUY_PRICE_CENTS})")
                return None
            
            # Log pre-trade exposure for debugging
            logger.debug(f"Pre-trade check {market_ticker}: {existing_contracts} contracts, ${existing_dollars:.2f} | Adding: {new_count} @ {new_price}¢ = ${new_dollars:.2f}")

            # Block if EITHER limit would be exceeded by this trade
            # Uses > (not >=) to allow trading UP TO the limit (e.g., 3 contracts allowed, block 4th)
            # NOTE: Limits apply to BASE MARKET (e.g., KXHIGHMIA-26FEB01) not per-threshold
            if existing_contracts + new_count > Config.MAX_CONTRACTS_PER_MARKET:
                logger.warning(f"⛔ BLOCKED trade on {market_ticker}: Would exceed BASE MARKET contract limit")
                logger.warning(f"   Base market {base_market}: {existing_contracts} + {new_count} = {existing_contracts + new_count} > {Config.MAX_CONTRACTS_PER_MARKET}")
                return None

            if existing_dollars + new_dollars > Config.MAX_DOLLARS_PER_MARKET:
                logger.warning(f"⛔ BLOCKED trade on {market_ticker}: Would exceed BASE MARKET dollar limit")
                logger.warning(f"   Base market {base_market}: ${existing_dollars:.2f} + ${new_dollars:.2f} = ${existing_dollars + new_dollars:.2f} > ${Config.MAX_DOLLARS_PER_MARKET:.2f}")
                return None
            
            # Set price for the side we're trading (YES or NO)
            price = decision.get('price', 0)
            if decision['side'] == 'yes':
                yes_price = price
                no_price = None
            else:
                yes_price = None
                no_price = price
            
            try:
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
            finally:
                # ALWAYS invalidate orders cache after order attempt (success or failure)
                # This ensures subsequent exposure checks see accurate order state
                self.client.invalidate_orders_cache()

            # Store trade in data store for backtesting
            try:
                self.data_store.store_trade(
                    ticker=market_ticker,
                    side=decision['side'],
                    action=decision['action'],
                    count=decision['count'],
                    price=decision.get('price', 0),
                    edge=decision.get('edge'),
                    ev=decision.get('ev'),
                    strategy_mode=decision.get('strategy_mode'),
                    market_price=decision.get('price', 0)
                )
            except Exception as store_err:
                logger.debug(f"Could not store trade in data store: {store_err}")

            # Track order with market maker for requote management
            order_type = decision.get('order_type', 'taker')
            if hasattr(self, 'market_maker') and order_type == 'maker':
                try:
                    self.market_maker.track_order(
                        order_id=order.get('order_id'),
                        ticker=market_ticker,
                        side=decision['side'],
                        price=decision.get('price', 0),
                        count=decision['count'],
                        order_type=order_type
                    )
                except Exception as track_err:
                    logger.debug(f"Could not track order with market maker: {track_err}")

            # Enhanced trade notification
            order_id = order.get('order_id', 'N/A')
            action = decision['action']
            side = decision['side']
            count = decision['count']
            price = decision.get('price', 'N/A')
            
            # Get current exposure for this market to display
            try:
                exp = self._get_market_exposure(market_ticker)
                exposure_str = f" | Exposure: {exp['total_contracts']}/{Config.MAX_CONTRACTS_PER_MARKET} contracts, ${exp['total_dollars']:.2f}/${Config.MAX_DOLLARS_PER_MARKET:.2f}"
            except (KeyError, TypeError, ValueError):
                exposure_str = ""
            
            trade_msg = f"🔄 TRADE EXECUTED: {action.upper()} {count} {side.upper()} @ {price}¢{exposure_str} | Order: {order_id} | Market: {market_ticker}"
            
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
        """Log trade to file (both human-readable and CSV for analysis)"""
        try:
            from datetime import datetime
            import csv
            from pathlib import Path

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Human-readable log
            log_file = "trades.log"
            log_entry = f"[{timestamp}] {message}\n"
            if order:
                log_entry += f"  Order Details: {order}\n"
            log_entry += f"  Decision: {decision}\n"
            log_entry += "-" * 70 + "\n"

            with open(log_file, 'a') as f:
                f.write(log_entry)

            # Structured CSV for outcome tracking (enhanced columns)
            csv_file = Path("data/trades.csv")
            csv_file.parent.mkdir(exist_ok=True)

            # Create CSV with headers if it doesn't exist (enhanced columns)
            if not csv_file.exists():
                with open(csv_file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'timestamp', 'market_ticker', 'order_id', 'action', 'side', 'count',
                        'price', 'edge', 'ev', 'strategy_mode', 'our_probability',
                        'market_price', 'status',
                        # Enhanced columns for analysis
                        'mean_forecast', 'forecast_std', 'ci_lower', 'ci_upper',
                        'time_decay_factor', 'num_sources', 'threshold', 'target_date'
                    ])

            # Append trade details with enhanced columns
            if order:
                with open(csv_file, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.now().isoformat(),
                        market_ticker,
                        order.get('order_id', ''),
                        decision.get('action', ''),
                        decision.get('side', ''),
                        decision.get('count', 0),
                        decision.get('price', 0),
                        decision.get('edge', 0),
                        decision.get('ev', 0),
                        decision.get('strategy_mode', ''),
                        decision.get('our_probability', ''),
                        decision.get('price', 0),  # market_price at time of trade
                        order.get('status', 'unknown'),
                        # Enhanced columns
                        decision.get('mean_forecast', ''),
                        decision.get('forecast_std', ''),
                        decision.get('ci_lower', ''),
                        decision.get('ci_upper', ''),
                        decision.get('time_decay_factor', ''),
                        decision.get('num_sources', ''),
                        decision.get('threshold', ''),
                        decision.get('target_date', '')
                    ])
        except Exception as e:
            logger.error(f"Error logging trade: {e}")

    def _log_trade_decision(self, market_ticker: str, decision_data: Dict):
        """
        Log detailed trade decision data to JSONL file for analysis.

        Writes comprehensive decision context including:
        - All forecast sources with temperatures and weights
        - Confidence interval bounds
        - Position sizing factors
        - Edge/EV breakdown for both sides
        - Market context
        """
        try:
            import json
            from pathlib import Path

            jsonl_file = Path("data/trade_decisions.jsonl")
            jsonl_file.parent.mkdir(exist_ok=True)

            # Add timestamp
            decision_data['timestamp'] = datetime.now().isoformat()
            decision_data['market_ticker'] = market_ticker

            # Write as JSONL (one JSON object per line)
            with open(jsonl_file, 'a') as f:
                f.write(json.dumps(decision_data) + '\n')

        except Exception as e:
            logger.debug(f"Error logging trade decision: {e}")
    
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
        self.require_high_confidence = getattr(Config, 'REQUIRE_HIGH_CONFIDENCE', True)
        
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

        # Scaled edge requirements - require more edge for expensive contracts
        self.scaled_edge_enabled = Config.SCALED_EDGE_ENABLED
        self.scaled_edge_price_threshold = Config.SCALED_EDGE_PRICE_THRESHOLD
        self.scaled_edge_multiplier = Config.SCALED_EDGE_MULTIPLIER

        # Market making mode - post limit orders at better prices
        self.market_making_enabled = Config.MARKET_MAKING_ENABLED
        if self.market_making_enabled:
            self.market_maker = MarketMaker(client)
            self.order_router = SmartOrderRouter(self.market_maker)
            logger.info("📈 Market making mode ENABLED - will post limit orders at better prices")

        # Correlation-aware risk management
        self.risk_manager = CorrelationAwareRisk(client)

        # Data store for backtesting
        self.data_store = get_data_store()

    def _get_required_edge(self, price: int) -> float:
        """
        Calculate required edge threshold based on entry price.
        Expensive contracts require more edge to be profitable.

        Args:
            price: Entry price in cents

        Returns:
            Required edge percentage
        """
        if not self.scaled_edge_enabled:
            return self.min_edge_threshold

        if price <= self.scaled_edge_price_threshold:
            # Below threshold, use normal edge requirement
            return self.min_edge_threshold
        else:
            # Above threshold, scale up edge requirement
            # E.g., at 50¢ with 35¢ threshold and 1.5x multiplier: 8% * 1.5 = 12%
            return self.min_edge_threshold * self.scaled_edge_multiplier

    def _calculate_time_decay_factor(self, target_date: datetime, series_ticker: str) -> float:
        """
        Calculate time decay factor (0.5-1.0) based on hours until temperature extreme.

        HIGH markets: Extreme typically 2-6 PM local (use configurable hour, default 4 PM)
        LOW markets: Extreme typically 4-7 AM local (use configurable hour, default 6 AM)

        Closer to extreme = higher confidence = larger positions
        Further from extreme = more uncertainty = smaller positions
        """
        from zoneinfo import ZoneInfo

        tz_name = self.weather_agg.CITY_TIMEZONES.get(series_ticker)
        if tz_name:
            tz = ZoneInfo(tz_name)
            local_now = datetime.now(tz)
        else:
            local_now = datetime.now()
            tz = None

        is_high_market = 'HIGH' in series_ticker
        is_low_market = 'LOW' in series_ticker

        # Determine when the extreme typically occurs (local time)
        if is_high_market:
            extreme_hour = Config.HIGH_EXTREME_HOUR  # Default 4 PM local
        elif is_low_market:
            extreme_hour = Config.LOW_EXTREME_HOUR   # Default 6 AM local
        else:
            extreme_hour = 12  # Fallback to noon

        # Calculate extreme time for target date
        extreme_time = datetime.combine(target_date.date(), datetime.min.time().replace(hour=extreme_hour))
        if tz:
            extreme_time = extreme_time.replace(tzinfo=tz)

        # Hours until the extreme occurs
        hours_until_extreme = (extreme_time - local_now).total_seconds() / 3600

        min_factor = Config.TIME_DECAY_MIN_FACTOR

        # If extreme has passed (negative hours), return high confidence
        if hours_until_extreme <= 0:
            return 1.0

        # If same day and within 6 hours of extreme: high confidence (0.85-1.0)
        if hours_until_extreme <= 6:
            return 0.85 + (0.15 * (1 - hours_until_extreme / 6))

        # If 6-24 hours out: medium confidence (0.65-0.85)
        if hours_until_extreme <= 24:
            return 0.65 + (0.20 * (1 - (hours_until_extreme - 6) / 18))

        # If 24-48 hours out: lower confidence (min_factor to 0.65)
        if hours_until_extreme <= 48:
            return min_factor + ((0.65 - min_factor) * (1 - (hours_until_extreme - 24) / 24))

        # Beyond 48 hours: minimum factor
        return min_factor

    def _get_correlated_exposure(self, market_ticker: str) -> Dict:
        """
        Calculate total exposure across ALL correlated markets:
        - Same city (KXHIGHNY and KXLOWNY are correlated)
        - Same date

        Returns dict with total_contracts, total_dollars, correlation_factor
        """
        parts = market_ticker.split('-')
        if len(parts) < 2:
            return {'total_contracts': 0, 'total_dollars': 0.0, 'correlation_factor': 1.0}

        # Extract city and date
        series = parts[0]  # e.g., KXHIGHNY
        date_part = parts[1]  # e.g., 26FEB01

        # Find correlated series (HIGH/LOW for same city)
        city_code = series.replace('KXHIGH', '').replace('KXLOW', '')
        correlated_series = [f'KXHIGH{city_code}', f'KXLOW{city_code}']

        total_contracts = 0
        total_dollars = 0.0

        try:
            positions = self.client.get_positions()
            for position in positions:
                pos_ticker = position.get('ticker', '')
                pos_parts = pos_ticker.split('-')
                if len(pos_parts) >= 2:
                    pos_series = pos_parts[0]
                    pos_date = pos_parts[1]
                    # Check if same city AND same date
                    if pos_series in correlated_series and pos_date == date_part:
                        contracts = abs(position.get('position', 0))
                        total_contracts += contracts
                        total_dollars += contracts * 0.47  # Estimated cost basis
        except Exception as e:
            logger.debug(f"Error fetching positions for correlation check: {e}")

        try:
            # Also check resting orders
            orders = self.client.get_orders(status='resting', use_cache=False)
            for order in orders:
                order_ticker = order.get('ticker', '')
                order_parts = order_ticker.split('-')
                if len(order_parts) >= 2:
                    order_series = order_parts[0]
                    order_date = order_parts[1]
                    if order_series in correlated_series and order_date == date_part:
                        remaining = order.get('remaining_count', 0)
                        total_contracts += remaining
                        price = order.get('yes_price') or order.get('no_price') or 50
                        total_dollars += (remaining * price) / 100.0
        except Exception as e:
            logger.debug(f"Error fetching orders for correlation check: {e}")

        # Correlation factor: reduce size as correlated exposure increases
        # At 50% of max contracts, reduce new positions by 25%
        # At 100% of max, reduce by max_reduction (default 50%)
        max_reduction = Config.CORRELATION_MAX_REDUCTION
        exposure_ratio = min(1.0, total_contracts / Config.MAX_CONTRACTS_PER_MARKET)
        correlation_factor = max(1.0 - max_reduction, 1.0 - (exposure_ratio * max_reduction))

        return {
            'total_contracts': total_contracts,
            'total_dollars': total_dollars,
            'correlation_factor': correlation_factor
        }

    def _calculate_liquidity_cap(self, orderbook: Dict, side: str, target_price: int) -> int:
        """
        Calculate max contracts we can buy without significant slippage.
        Returns max contracts at or near target_price.

        Prevents taking more than LIQUIDITY_CAP_PERCENT of visible liquidity.
        """
        # Get orderbook for opposite side (we're buying, so look at sellers)
        opposite_side = 'no' if side == 'yes' else 'yes'
        orders = orderbook.get('orderbook', {}).get(opposite_side, [])

        if not orders:
            return Config.MAX_POSITION_SIZE * 5  # No data, use high default

        # Sum up available contracts within tolerance of target price
        # Orderbook format: [[price, quantity], ...] sorted ascending
        available_contracts = 0
        price_tolerance = Config.LIQUIDITY_PRICE_TOLERANCE

        for price, quantity in orders:
            # For buying YES: our ask = 100 - their bid
            effective_ask = 100 - price
            if effective_ask <= target_price + price_tolerance:
                available_contracts += quantity

        # Don't take more than configured percent of visible liquidity
        liquidity_cap = int(available_contracts * Config.LIQUIDITY_CAP_PERCENT)

        return max(1, liquidity_cap)  # At least 1 contract

    def _calculate_ev_proportional_size(self, ev: float, is_longshot: bool) -> int:
        """
        Calculate position size proportional to expected value.
        Higher EV = larger position (within limits).

        Replaces discrete multipliers with continuous EV-based scaling.
        """
        # Baseline EV thresholds from config
        if is_longshot:
            baseline_ev = Config.EV_BASELINE_LONGSHOT  # Default $0.05
            max_multiplier = 5.0  # Up to 5x for exceptional EV
        else:
            baseline_ev = Config.EV_BASELINE_CONSERVATIVE  # Default $0.02
            max_multiplier = 2.0  # Up to 2x for conservative

        # Calculate EV multiplier (capped)
        if ev <= 0:
            return 0

        ev_ratio = ev / baseline_ev
        ev_multiplier = min(max_multiplier, max(0.5, ev_ratio))

        # Apply to base position
        base_position = int(self.max_position_size * ev_multiplier)

        return base_position

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
                logger.info(f"📊 SKIP {market_ticker}: could not determine series")
                return None
            
            # Extract target date from market ticker or title
            # Ticker format: KXHIGHNY-26JAN28-T26 (date is 26JAN28 = Jan 28, 2026)
            # Title format: "Will the **high temp in NYC** be >26° on Jan 28, 2026?"
            target_date = self._extract_market_date(market)
            if not target_date:
                logger.info(f"📊 SKIP {market_ticker}: could not extract date from ticker/title")
                return None
            
            # Verify date is reasonable (not too far in past/future)
            today = datetime.now().date()
            market_date = target_date.date()
            days_diff = (market_date - today).days
            
            max_days = Config.MAX_MARKET_DATE_DAYS
            if days_diff < -1 or days_diff > max_days:  # Allow -1 (yesterday) to max_days
                logger.info(f"📊 SKIP {market_ticker}: date too far (today ± {max_days}d, got {days_diff}d)")
                return None
            
            # Extract temperature threshold from market title (single float or (low, high) range)
            threshold = self.extract_threshold(market)
            if not threshold:
                logger.info(f"📊 SKIP {market_ticker}: could not extract temp threshold from title")
                return None
            
            # CRITICAL: Check if outcome is already determined by today's observations
            # Only check if this is a market for TODAY (not future dates)
            observed_today = None  # Used later for "past extreme of day" longshot cutoff
            is_high_market = series_ticker.startswith('KXHIGH')
            is_low_market = series_ticker.startswith('KXLOW')
            
            if target_date.date() == datetime.now().date():
                # This market is for today - check if outcome already determined
                if is_high_market:
                    observed_today = self.weather_agg.get_todays_observed_high(series_ticker)
                elif is_low_market:
                    observed_today = self.weather_agg.get_todays_observed_low(series_ticker)
                
                observed = observed_today
                
                if observed:
                    observed_extreme, obs_time = observed
                    is_range_market = isinstance(threshold, tuple)
                    
                    # Check if outcome is already certain based on observations
                    outcome_determined = False
                    reason = ""
                    
                    if is_range_market:
                        range_low, range_high = threshold
                        if is_high_market:
                            # For HIGH range markets: if observed high already exceeds range, outcome is NO
                            if observed_extreme >= range_high:
                                outcome_determined = True
                                reason = f"Observed high {observed_extreme:.1f}°F already exceeds range [{range_low}-{range_high}°F)"
                        elif is_low_market:
                            # For LOW range markets: if observed low already below range, outcome is NO
                            if observed_extreme <= range_low:
                                outcome_determined = True
                                reason = f"Observed low {observed_extreme:.1f}°F already below range [{range_low}-{range_high}°F)"
                    else:
                        # Single threshold market
                        market_title = market.get('title', '').lower()
                        is_above_market = 'above' in market_title or '>' in market_title
                        
                        if is_high_market:
                            if is_above_market:
                                # Market is "Will high be >X°?"
                                if observed_extreme > threshold:
                                    outcome_determined = True
                                    reason = f"Observed high {observed_extreme:.1f}°F already exceeds threshold {threshold}°F (YES certain)"
                            else:
                                # Market is "Will high be <X°?"
                                if observed_extreme >= threshold:
                                    outcome_determined = True
                                    reason = f"Observed high {observed_extreme:.1f}°F already reached threshold {threshold}°F (NO certain)"
                        elif is_low_market:
                            if is_above_market:
                                # Market is "Will low be >X°?"
                                if observed_extreme > threshold:
                                    outcome_determined = True
                                    reason = f"Observed low {observed_extreme:.1f}°F already exceeds threshold {threshold}°F (YES certain)"
                            else:
                                # Market is "Will low be <X°?"
                                if observed_extreme <= threshold:
                                    outcome_determined = True
                                    reason = f"Observed low {observed_extreme:.1f}°F already below threshold {threshold}°F (NO certain)"
                    
                    if outcome_determined:
                        logger.info(f"📊 SKIP {market_ticker}: outcome already determined — {reason}")
                        
                        # Mark this market for exclusion from future scans
                        if hasattr(self, '_bot_ref') and self._bot_ref:
                            self._bot_ref.determined_outcome_markets.add(market_ticker)
                            logger.debug(f"🚫 Added {market_ticker} to exclusion list (will skip in future scans)")
                        
                        # Cancel any resting orders for this market since outcome is certain
                        try:
                            all_orders = self.client.get_orders(status='resting', use_cache=False)
                            market_orders = [o for o in all_orders if o.get('ticker') == market_ticker]

                            if market_orders:
                                logger.info(f"🚫 Cancelling {len(market_orders)} resting order(s) for {market_ticker} (outcome determined)")
                                for order in market_orders:
                                    order_id = order.get('order_id')
                                    if order_id:
                                        try:
                                            self.client.cancel_order(order_id)
                                            logger.info(f"   ✅ Cancelled order {order_id}")
                                        except Exception as cancel_error:
                                            logger.warning(f"   ⚠️  Failed to cancel order {order_id}: {cancel_error}")
                                # Invalidate cache after cancellations
                                self.client.invalidate_orders_cache()
                        except Exception as e:
                            logger.warning(f"Failed to fetch/cancel orders for {market_ticker}: {e}")
                        
                        return None
            
            # Get forecasts from all available sources
            forecasts = self.weather_agg.get_all_forecasts(series_ticker, target_date)
            
            if not forecasts:
                logger.info(f"📊 SKIP {market_ticker}: no forecasts for {series_ticker} on {target_date.strftime('%Y-%m-%d')}")
                return None
            
            # Log market type for LOW vs HIGH debugging
            market_type = "LOW temp" if is_low_market else "HIGH temp"
            mean_forecast = sum(forecasts) / len(forecasts)
            logger.debug(f"Evaluating {market_type} market {market_ticker}: {len(forecasts)} forecasts, mean={mean_forecast:.1f}°F, threshold={threshold}")
            
            # Build temperature ranges (2-degree brackets as mentioned in guide)
            # Kalshi weather markets typically have 6 brackets
            # We'll create a fine-grained distribution first, then map to brackets
            mean_forecast = sum(forecasts) / len(forecasts)
            
            # Skip single-threshold markets when forecast is too close to threshold (high uncertainty)
            min_deg = getattr(Config, 'MIN_DEGREES_FROM_THRESHOLD', 0)
            if min_deg > 0 and not isinstance(threshold, tuple):
                if abs(mean_forecast - threshold) < min_deg:
                    logger.info(f"📊 SKIP {market_ticker}: forecast {mean_forecast:.1f}° within {min_deg}° of threshold {threshold}° (reduce coin-flip losses)")
                    return None
            
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
                logger.info(f"📊 SKIP {market_ticker}: could not build probability distribution")
                return None
            
            # Calculate our probability for this market
            market_title = market.get('title', '').lower()
            is_range_market = isinstance(threshold, tuple)
            if is_range_market:
                range_low, range_high = threshold
                # "Will the temp be 71-72°?" -> P(71 <= temp < 72) = sum of prob * overlap per bracket
                our_prob = 0.0
                for (temp_min, temp_max), prob in prob_dist.items():
                    # Overlap of bracket [temp_min, temp_max) with [range_low, range_high)
                    overlap_min = max(temp_min, range_low)
                    overlap_max = min(temp_max, range_high)
                    if overlap_max > overlap_min:
                        bracket_width = temp_max - temp_min
                        overlap_frac = (overlap_max - overlap_min) / bracket_width if bracket_width > 0 else 0
                        our_prob += prob * overlap_frac
                is_above_market = True  # used only for CI; use midpoint for approximate CI
                threshold_for_ci = (range_low + range_high) / 2.0
            else:
                is_above_market = 'above' in market_title or '>' in market_title
                threshold_for_ci = threshold
                # Single-threshold (above/below) probability
                our_prob = 0.0
                for (temp_min, temp_max), prob in prob_dist.items():
                    if is_above_market:
                        if temp_min >= threshold:
                            our_prob += prob
                        elif temp_max > threshold:
                            overlap = (temp_max - threshold) / (temp_max - temp_min) if (temp_max - temp_min) > 0 else 0
                            our_prob += prob * overlap
                    else:  # below market
                        if temp_max <= threshold:
                            our_prob += prob
                        elif temp_min < threshold:
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
                logger.info(f"📊 SKIP {market_ticker}: empty orderbook (no yes/no orders)")
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

            # EARLY PRICE CHECK: Skip if BOTH sides are too expensive (saves calculation time)
            if best_yes_ask > Config.MAX_BUY_PRICE_CENTS and best_no_ask > Config.MAX_BUY_PRICE_CENTS:
                logger.info(f"📊 SKIP {market_ticker}: both YES ({best_yes_ask}¢) and NO ({best_no_ask}¢) exceed max price ({Config.MAX_BUY_PRICE_CENTS}¢)")
                return None

            # Calculate edge for YES side using ASK price (what we'd actually pay)
            yes_edge = self.weather_agg.calculate_edge(our_prob, int(best_yes_ask))
            
            # Calculate edge for NO side (inverse probability) using ASK price
            no_prob = 1.0 - our_prob
            no_edge = self.weather_agg.calculate_edge(no_prob, int(best_no_ask))
            
            # Calculate confidence intervals for probability estimates
            # For "above" markets, YES = temp > threshold; for "below", YES = temp < threshold
            # For range markets we use midpoint for approximate CI
            prob_ci_yes, (ci_lower_yes, ci_upper_yes) = self.weather_agg.calculate_confidence_interval(
                forecasts, threshold_for_ci, is_above=is_above_market
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
            
            # CRITICAL FIX: Check if we already have a resting order on THIS EXACT ticker
            # This prevents the bug where we place multiple orders on the same ticker every scan
            if self._has_resting_order_on_ticker(market_ticker):
                logger.info(f"📊 SKIP {market_ticker}: already have resting order on this ticker")
                return None

            # Check existing exposure on this BASE MARKET BEFORE placing new orders
            # This prevents over-exposure to a market (across all thresholds)
            existing_exposure = self._get_market_exposure(market_ticker)
            existing_contracts = existing_exposure['total_contracts']
            existing_dollars = existing_exposure['total_dollars']
            base_market = existing_exposure.get('base_market', market_ticker)

            # Calculate remaining capacity
            contracts_remaining = max(0, Config.MAX_CONTRACTS_PER_MARKET - existing_contracts)
            dollars_remaining = max(0, Config.MAX_DOLLARS_PER_MARKET - existing_dollars)

            # HARD BLOCK: If we're already at or over dollar limit, skip this market
            # This enforces the $5 limit even if existing orders already exceeded it
            if existing_dollars >= Config.MAX_DOLLARS_PER_MARKET:
                logger.info(f"📊 SKIP {market_ticker}: already at dollar limit ${existing_dollars:.2f}/${Config.MAX_DOLLARS_PER_MARKET:.2f} for {base_market}")
                return None

            # If we're at or over contract limits, skip this market
            if contracts_remaining == 0:
                logger.info(f"📊 SKIP {market_ticker}: at BASE MARKET position limit ({existing_contracts}/{Config.MAX_CONTRACTS_PER_MARKET} contracts, ${existing_dollars:.2f}/${Config.MAX_DOLLARS_PER_MARKET:.2f}) for {base_market}")
                return None

            logger.debug(f"✅ {market_ticker}: {contracts_remaining} contracts, ${dollars_remaining:.2f} remaining for BASE MARKET {base_market} (current: {existing_contracts} contracts, ${existing_dollars:.2f})")
            
            # Skip ALL new trades on today's markets once the extreme (high/low) of day has likely occurred.
            # Official report is typically in by afternoon; buying after that is bad (outcome known or soon known).
            skip_todays_market_past_report = (
                target_date.date() == datetime.now().date()
                and self.weather_agg.is_likely_past_extreme_of_day(
                    series_ticker,
                    target_date,
                    observed_extreme=observed_today[0] if observed_today else None,
                    forecasted_extreme=mean_forecast,
                )
            )
            if skip_todays_market_past_report:
                market_type = "high" if is_high_market else "low" if is_low_market else "temperature"
                logger.info(f"📊 SKIP {market_ticker}: today's market past report time — {market_type} of day likely already occurred (no new buys)")
                return None
            
            # DUAL STRATEGY: Check both conservative and longshot modes
            
            # LONGSHOT MODE: Hunt for extreme mispricings (0.1-10% odds with massive edges)
            # Inspired by successful Polymarket bot: buy cheap certainty
            if self.longshot_enabled:
                # Check YES side for longshot opportunity
                # Use ASK price to check if it's cheap enough
                if (best_yes_ask <= self.longshot_max_price and 
                    our_prob >= (self.longshot_min_prob / 100.0) and 
                    yes_edge >= self.longshot_min_edge):
                    
                    # HYBRID POSITION SIZING: Kelly for high confidence, confidence scoring otherwise
                    # Check confidence: only use Kelly if CI doesn't overlap with market price
                    use_kelly = (ci_lower_yes > best_yes_ask / 100.0 or ci_upper_yes < best_yes_ask / 100.0)
                    
                    # Position sizing: EV-proportional (new) or Kelly/Confidence (legacy)
                    if Config.EV_PROPORTIONAL_ENABLED:
                        base_position = self._calculate_ev_proportional_size(yes_ev, is_longshot=True)
                        logger.debug(f"EV-proportional sizing: EV=${yes_ev:.4f}, position={base_position}")
                    elif use_kelly and len(forecasts) >= 2:
                        # HIGH CONFIDENCE: Use Kelly Criterion for optimal position sizing
                        payout_ratio = 1.0 / (best_yes_ask / 100.0)  # Payout / Stake
                        kelly_fraction = self.weather_agg.kelly_fraction(our_prob, payout_ratio, fractional=0.5)
                        # Get portfolio value for Kelly calculation
                        portfolio = self.client.get_portfolio()
                        portfolio_value = (portfolio.get('balance', 0) + portfolio.get('portfolio_value', 0)) / 100.0
                        kelly_position = int(kelly_fraction * portfolio_value / (best_yes_ask / 100.0))
                        base_position = min(kelly_position, self.max_position_size * 5)
                        logger.debug(f"Using Kelly: fraction={kelly_fraction:.3f}, position={base_position}")
                    else:
                        # LOWER CONFIDENCE: Use confidence scoring for conservative sizing
                        ci_width = ci_upper_yes - ci_lower_yes
                        confidence = self.weather_agg.calculate_confidence_score(
                            edge=yes_edge,
                            ci_width=ci_width,
                            num_forecasts=len(forecasts),
                            ev=yes_ev,
                            is_longshot=True
                        )
                        # Scale by confidence: 0.1 confidence = 1x base, 1.0 confidence = 5x base
                        confidence_multiplier = 1 + (confidence * 4)  # 1x to 5x
                        base_position = int(self.max_position_size * confidence_multiplier)
                        base_position = min(base_position, self.max_position_size * 5)  # Cap at 5x
                        logger.debug(f"Using Confidence: score={confidence:.3f}, multiplier={confidence_multiplier:.2f}x, position={base_position}")

                    # Apply time decay factor (reduce size for markets further from temperature extreme)
                    if Config.TIME_DECAY_ENABLED:
                        time_factor = self._calculate_time_decay_factor(target_date, series_ticker)
                        base_position = max(1, int(base_position * time_factor))
                        logger.debug(f"Time decay: factor={time_factor:.2f}, adjusted position={base_position}")

                    # Apply correlation adjustment (reduce size when holding correlated positions)
                    if Config.CORRELATION_ADJUSTMENT_ENABLED:
                        corr_data = self._get_correlated_exposure(market_ticker)
                        base_position = max(1, int(base_position * corr_data['correlation_factor']))
                        if corr_data['correlation_factor'] < 1.0:
                            logger.debug(f"Correlation adjustment: factor={corr_data['correlation_factor']:.2f}, correlated contracts={corr_data['total_contracts']}")

                    # Calculate liquidity cap
                    if Config.LIQUIDITY_CAP_ENABLED:
                        liquidity_cap = self._calculate_liquidity_cap(orderbook, 'yes', int(best_yes_ask))
                    else:
                        liquidity_cap = self.max_position_size * 10  # Effectively no cap

                    # Cap by REMAINING contract count, dollars, and liquidity
                    dollar_cap_contracts = int(dollars_remaining * 100 / best_yes_ask) if best_yes_ask > 0 else contracts_remaining
                    position_size = min(base_position, contracts_remaining, dollar_cap_contracts, liquidity_cap)

                    if liquidity_cap < base_position:
                        logger.debug(f"Liquidity cap applied: {liquidity_cap} contracts (was {base_position})")
                    
                    # Skip if no room or below minimum order size
                    if position_size <= 0:
                        logger.info(f"📊 SKIP {market_ticker}: longshot YES ok but no capacity (position_size=0)")
                        return None
                    if position_size < Config.MIN_ORDER_CONTRACTS:
                        logger.info(f"📊 SKIP {market_ticker}: longshot YES size {position_size} < MIN_ORDER_CONTRACTS ({Config.MIN_ORDER_CONTRACTS})")
                        return None
                    
                    if best_yes_ask > Config.MAX_BUY_PRICE_CENTS:
                        logger.info(f"📊 SKIP {market_ticker}: longshot YES ask {best_yes_ask}¢ exceeds max price ({Config.MAX_BUY_PRICE_CENTS}¢)")
                        # Fall through to check NO side (don't return yet)
                    else:
                        # Apply portfolio-wide correlation adjustment via risk manager
                        position_size = self.risk_manager.adjust_position_size(
                            position_size, market_ticker, 'yes'
                        )
                        if position_size <= 0:
                            logger.info(f"📊 SKIP {market_ticker}: risk manager reduced size to 0")
                            return None

                        # Determine execution price (market making or taker)
                        execution_price = best_yes_ask
                        order_type = 'taker'
                        if self.market_making_enabled and hasattr(self, 'order_router'):
                            routes = self.order_router.route_order(
                                side='yes',
                                count=position_size,
                                orderbook=orderbook,
                                our_fair_value=int(our_prob * 100),
                                edge=yes_edge,
                                urgency=Config.MM_ORDER_URGENCY
                            )
                            if routes:
                                execution_price = routes[0]['price']
                                order_type = routes[0]['type']
                                if order_type == 'maker':
                                    logger.info(f"📝 Market making: posting at {execution_price}¢ (ask: {best_yes_ask}¢, saving {best_yes_ask - execution_price}¢)")

                        confidence_str = f"CI: [{ci_lower_yes:.1%}, {ci_upper_yes:.1%}]" if use_kelly else ""
                        logger.info(f"🎯 LONGSHOT YES {market_ticker}: Ask {best_yes_ask}¢ (cheap!), Our Prob: {our_prob:.1%} {confidence_str}, Edge: {yes_edge:.1f}%, EV: ${yes_ev:.4f} (with fees)")
                        logger.info(f"💰 Asymmetric play: Risk ${execution_price/100 * position_size:.2f} for ${1.00 * position_size:.2f} payout ({(100/execution_price):.1f}x)")

                        # Record position for exit logic
                        self.active_positions[market_ticker] = {
                            'side': 'yes',
                            'entry_price': execution_price,
                            'entry_time': datetime.now(),
                            'count': position_size,
                            'edge': yes_edge,
                            'ev': yes_ev,
                            'strategy_mode': 'longshot'
                        }

                        # Build enhanced decision with analysis data
                        time_factor = self._calculate_time_decay_factor(target_date, series_ticker) if Config.TIME_DECAY_ENABLED else 1.0
                        corr_data = self._get_correlated_exposure(market_ticker) if Config.CORRELATION_ADJUSTMENT_ENABLED else {'correlation_factor': 1.0}

                        decision = {
                            'action': 'buy',
                            'side': 'yes',
                            'count': position_size,
                            'price': execution_price,
                            'edge': yes_edge,
                            'ev': yes_ev,
                            'strategy_mode': 'longshot',
                            'order_type': order_type,
                            # Enhanced fields for analysis
                            'our_probability': our_prob,
                            'mean_forecast': mean_forecast,
                            'forecast_std': float(np.std(forecasts)) if len(forecasts) > 1 else 0,
                            'ci_lower': ci_lower_yes,
                            'ci_upper': ci_upper_yes,
                            'time_decay_factor': time_factor,
                            'num_sources': len(forecasts),
                            'threshold': str(threshold),
                            'target_date': target_date.strftime('%Y-%m-%d') if target_date else ''
                        }

                        # Log detailed trade decision for analysis
                        self._log_trade_decision(market_ticker, {
                            'decision': 'longshot_yes',
                            'forecasts': [(f, s, t.isoformat() if hasattr(t, 'isoformat') else str(t))
                                         for f, s, t in self.weather_agg.forecast_metadata.get(
                                             f"{series_ticker}_{target_date.strftime('%Y-%m-%d')}", [])],
                            'ci_lower': ci_lower_yes,
                            'ci_upper': ci_upper_yes,
                            'time_decay_factor': time_factor,
                            'correlation_factor': corr_data['correlation_factor'],
                            'liquidity_cap': liquidity_cap,
                            'yes_edge': yes_edge,
                            'yes_ev': yes_ev,
                            'no_edge': no_edge,
                            'no_ev': no_ev,
                            'threshold': str(threshold),
                            'target_date': target_date.strftime('%Y-%m-%d') if target_date else '',
                            'is_longshot': True,
                            'series_ticker': series_ticker
                        })

                        return decision

                # Check NO side for longshot opportunity
                # Use ASK price to check if it's cheap enough
                if (best_no_ask <= self.longshot_max_price and 
                    no_prob >= (self.longshot_min_prob / 100.0) and 
                    no_edge >= self.longshot_min_edge):
                    
                    # HYBRID POSITION SIZING: Kelly for high confidence, confidence scoring otherwise
                    # Check confidence: only use Kelly if CI doesn't overlap with market price
                    use_kelly = (ci_lower_no > best_no_ask / 100.0 or ci_upper_no < best_no_ask / 100.0)
                    
                    # Position sizing: EV-proportional (new) or Kelly/Confidence (legacy)
                    if Config.EV_PROPORTIONAL_ENABLED:
                        base_position = self._calculate_ev_proportional_size(no_ev, is_longshot=True)
                        logger.debug(f"EV-proportional sizing: EV=${no_ev:.4f}, position={base_position}")
                    elif use_kelly and len(forecasts) >= 2:
                        # HIGH CONFIDENCE: Use Kelly Criterion for optimal position sizing
                        payout_ratio = 1.0 / (best_no_ask / 100.0)  # Payout / Stake
                        kelly_fraction = self.weather_agg.kelly_fraction(no_prob, payout_ratio, fractional=0.5)
                        # Get portfolio value for Kelly calculation
                        portfolio = self.client.get_portfolio()
                        portfolio_value = (portfolio.get('balance', 0) + portfolio.get('portfolio_value', 0)) / 100.0
                        kelly_position = int(kelly_fraction * portfolio_value / (best_no_ask / 100.0))
                        base_position = min(kelly_position, self.max_position_size * 5)
                        logger.debug(f"Using Kelly: fraction={kelly_fraction:.3f}, position={base_position}")
                    else:
                        # LOWER CONFIDENCE: Use confidence scoring for conservative sizing
                        ci_width = ci_upper_no - ci_lower_no
                        confidence = self.weather_agg.calculate_confidence_score(
                            edge=no_edge,
                            ci_width=ci_width,
                            num_forecasts=len(forecasts),
                            ev=no_ev,
                            is_longshot=True
                        )
                        # Scale by confidence: 0.1 confidence = 1x base, 1.0 confidence = 5x base
                        confidence_multiplier = 1 + (confidence * 4)  # 1x to 5x
                        base_position = int(self.max_position_size * confidence_multiplier)
                        base_position = min(base_position, self.max_position_size * 5)  # Cap at 5x
                        logger.debug(f"Using Confidence: score={confidence:.3f}, multiplier={confidence_multiplier:.2f}x, position={base_position}")

                    # Apply time decay factor (reduce size for markets further from temperature extreme)
                    if Config.TIME_DECAY_ENABLED:
                        time_factor = self._calculate_time_decay_factor(target_date, series_ticker)
                        base_position = max(1, int(base_position * time_factor))
                        logger.debug(f"Time decay: factor={time_factor:.2f}, adjusted position={base_position}")

                    # Apply correlation adjustment (reduce size when holding correlated positions)
                    if Config.CORRELATION_ADJUSTMENT_ENABLED:
                        corr_data = self._get_correlated_exposure(market_ticker)
                        base_position = max(1, int(base_position * corr_data['correlation_factor']))
                        if corr_data['correlation_factor'] < 1.0:
                            logger.debug(f"Correlation adjustment: factor={corr_data['correlation_factor']:.2f}, correlated contracts={corr_data['total_contracts']}")

                    # Calculate liquidity cap
                    if Config.LIQUIDITY_CAP_ENABLED:
                        liquidity_cap = self._calculate_liquidity_cap(orderbook, 'no', int(best_no_ask))
                    else:
                        liquidity_cap = self.max_position_size * 10  # Effectively no cap

                    # Cap by REMAINING contract count, dollars, and liquidity
                    dollar_cap_contracts = int(dollars_remaining * 100 / best_no_ask) if best_no_ask > 0 else contracts_remaining
                    position_size = min(base_position, contracts_remaining, dollar_cap_contracts, liquidity_cap)

                    if liquidity_cap < base_position:
                        logger.debug(f"Liquidity cap applied: {liquidity_cap} contracts (was {base_position})")

                    if position_size <= 0:
                        logger.info(f"📊 SKIP {market_ticker}: longshot NO ok but no capacity (position_size=0)")
                        return None
                    if position_size < Config.MIN_ORDER_CONTRACTS:
                        logger.info(f"📊 SKIP {market_ticker}: longshot NO size {position_size} < MIN_ORDER_CONTRACTS ({Config.MIN_ORDER_CONTRACTS})")
                        return None
                    
                    if best_no_ask > Config.MAX_BUY_PRICE_CENTS:
                        logger.info(f"📊 SKIP {market_ticker}: longshot NO ask {best_no_ask}¢ exceeds max price ({Config.MAX_BUY_PRICE_CENTS}¢)")
                        return None  # EXPLICIT: Don't trade above price limit

                    # Apply portfolio-wide correlation adjustment via risk manager
                    position_size = self.risk_manager.adjust_position_size(
                        position_size, market_ticker, 'no'
                    )
                    if position_size <= 0:
                        logger.info(f"📊 SKIP {market_ticker}: risk manager reduced size to 0")
                        return None

                    # Determine execution price (market making or taker)
                    execution_price = best_no_ask
                    order_type = 'taker'
                    if self.market_making_enabled and hasattr(self, 'order_router'):
                        routes = self.order_router.route_order(
                            side='no',
                            count=position_size,
                            orderbook=orderbook,
                            our_fair_value=int(no_prob * 100),
                            edge=no_edge,
                            urgency=Config.MM_ORDER_URGENCY
                        )
                        if routes:
                            execution_price = routes[0]['price']
                            order_type = routes[0]['type']
                            if order_type == 'maker':
                                logger.info(f"📝 Market making: posting at {execution_price}¢ (ask: {best_no_ask}¢, saving {best_no_ask - execution_price}¢)")

                    confidence_str = f"CI: [{ci_lower_no:.1%}, {ci_upper_no:.1%}]" if use_kelly else ""
                    logger.info(f"🎯 LONGSHOT NO {market_ticker}: Ask {best_no_ask}¢ (cheap!), Our Prob: {no_prob:.1%} {confidence_str}, Edge: {no_edge:.1f}%, EV: ${no_ev:.4f} (with fees)")
                    logger.info(f"💰 Asymmetric play: Risk ${execution_price/100 * position_size:.2f} for ${1.00 * position_size:.2f} payout ({(100/execution_price):.1f}x)")

                    # Record position for exit logic
                    self.active_positions[market_ticker] = {
                        'side': 'no',
                        'entry_price': execution_price,
                        'entry_time': datetime.now(),
                        'count': position_size,
                        'edge': no_edge,
                        'ev': no_ev,
                        'strategy_mode': 'longshot'
                    }

                    # Build enhanced decision with analysis data
                    time_factor = self._calculate_time_decay_factor(target_date, series_ticker) if Config.TIME_DECAY_ENABLED else 1.0
                    corr_data = self._get_correlated_exposure(market_ticker) if Config.CORRELATION_ADJUSTMENT_ENABLED else {'correlation_factor': 1.0}

                    decision = {
                        'action': 'buy',
                        'side': 'no',
                        'count': position_size,
                        'price': execution_price,
                        'edge': no_edge,
                        'ev': no_ev,
                        'strategy_mode': 'longshot',
                        'order_type': order_type,
                        # Enhanced fields for analysis
                        'our_probability': no_prob,
                        'mean_forecast': mean_forecast,
                        'forecast_std': float(np.std(forecasts)) if len(forecasts) > 1 else 0,
                        'ci_lower': ci_lower_no,
                        'ci_upper': ci_upper_no,
                        'time_decay_factor': time_factor,
                        'num_sources': len(forecasts),
                        'threshold': str(threshold),
                        'target_date': target_date.strftime('%Y-%m-%d') if target_date else ''
                    }

                    # Log detailed trade decision for analysis
                    self._log_trade_decision(market_ticker, {
                        'decision': 'longshot_no',
                        'forecasts': [(f, s, t.isoformat() if hasattr(t, 'isoformat') else str(t))
                                     for f, s, t in self.weather_agg.forecast_metadata.get(
                                         f"{series_ticker}_{target_date.strftime('%Y-%m-%d')}", [])],
                        'ci_lower': ci_lower_no,
                        'ci_upper': ci_upper_no,
                        'time_decay_factor': time_factor,
                        'correlation_factor': corr_data['correlation_factor'],
                        'liquidity_cap': liquidity_cap,
                        'yes_edge': yes_edge,
                        'yes_ev': yes_ev,
                        'no_edge': no_edge,
                        'no_ev': no_ev,
                        'threshold': str(threshold),
                        'target_date': target_date.strftime('%Y-%m-%d') if target_date else '',
                        'is_longshot': True,
                        'series_ticker': series_ticker
                    })

                    return decision

            # CONSERVATIVE MODE: Standard edge/EV trading (high win rate)
            # Optionally require confidence interval to not overlap market price (REQUIRE_HIGH_CONFIDENCE)
            high_confidence_yes = (ci_lower_yes > best_yes_ask / 100.0 or ci_upper_yes < best_yes_ask / 100.0)
            high_confidence_no = (ci_lower_no > best_no_ask / 100.0 or ci_upper_no < best_no_ask / 100.0)
            
            # Get required edge based on price (scaled edge for expensive contracts)
            required_yes_edge = self._get_required_edge(best_yes_ask)
            if yes_edge >= required_yes_edge and yes_ev >= self.min_ev_threshold and (not self.require_high_confidence or high_confidence_yes):
                # HYBRID POSITION SIZING for conservative trades
                # Use Kelly for high confidence (2+ sources, high prob), confidence scoring otherwise
                use_kelly = len(forecasts) >= 2 and our_prob > 0.7 and (ci_lower_yes > best_yes_ask / 100.0)

                # Position sizing: EV-proportional (new) or Kelly/Confidence (legacy)
                if Config.EV_PROPORTIONAL_ENABLED:
                    base_position = self._calculate_ev_proportional_size(yes_ev, is_longshot=False)
                    logger.debug(f"EV-proportional sizing: EV=${yes_ev:.4f}, position={base_position}")
                elif use_kelly:
                    # HIGH CONFIDENCE: Kelly Criterion with very conservative fractional (0.25)
                    payout_ratio = 1.0 / (best_yes_ask / 100.0)
                    kelly_fraction = self.weather_agg.kelly_fraction(our_prob, payout_ratio, fractional=0.25)
                    portfolio = self.client.get_portfolio()
                    portfolio_value = (portfolio.get('balance', 0) + portfolio.get('portfolio_value', 0)) / 100.0
                    kelly_position = int(kelly_fraction * portfolio_value / (best_yes_ask / 100.0))
                    base_position = min(max(kelly_position, self.max_position_size), self.max_position_size * 2)
                    logger.debug(f"Conservative Kelly: fraction={kelly_fraction:.3f}, position={base_position}")
                else:
                    # LOWER CONFIDENCE: Use confidence scoring
                    ci_width = ci_upper_yes - ci_lower_yes
                    confidence = self.weather_agg.calculate_confidence_score(
                        edge=yes_edge,
                        ci_width=ci_width,
                        num_forecasts=len(forecasts),
                        ev=yes_ev,
                        is_longshot=False
                    )
                    # Conservative: 0.5 confidence = 1x, 1.0 confidence = 1.5x
                    confidence_multiplier = 0.5 + (confidence * 1.0)  # 0.5x to 1.5x
                    base_position = int(self.max_position_size * confidence_multiplier)
                    base_position = max(1, min(base_position, self.max_position_size * 2))
                    logger.debug(f"Conservative Confidence: score={confidence:.3f}, multiplier={confidence_multiplier:.2f}x, position={base_position}")

                # Apply time decay factor (reduce size for markets further from temperature extreme)
                if Config.TIME_DECAY_ENABLED:
                    time_factor = self._calculate_time_decay_factor(target_date, series_ticker)
                    base_position = max(1, int(base_position * time_factor))
                    logger.debug(f"Time decay: factor={time_factor:.2f}, adjusted position={base_position}")

                # Apply correlation adjustment (reduce size when holding correlated positions)
                if Config.CORRELATION_ADJUSTMENT_ENABLED:
                    corr_data = self._get_correlated_exposure(market_ticker)
                    base_position = max(1, int(base_position * corr_data['correlation_factor']))
                    if corr_data['correlation_factor'] < 1.0:
                        logger.debug(f"Correlation adjustment: factor={corr_data['correlation_factor']:.2f}, correlated contracts={corr_data['total_contracts']}")

                # Calculate liquidity cap
                if Config.LIQUIDITY_CAP_ENABLED:
                    liquidity_cap = self._calculate_liquidity_cap(orderbook, 'yes', int(best_yes_ask))
                else:
                    liquidity_cap = self.max_position_size * 10  # Effectively no cap

                # Cap by REMAINING capacity, dollars, and liquidity
                dollar_cap_contracts = int(dollars_remaining * 100 / best_yes_ask) if best_yes_ask > 0 else contracts_remaining
                position_size = min(base_position, contracts_remaining, dollar_cap_contracts, liquidity_cap)

                if liquidity_cap < base_position:
                    logger.debug(f"Liquidity cap applied: {liquidity_cap} contracts (was {base_position})")

                if position_size <= 0:
                    logger.info(f"📊 SKIP {market_ticker}: conservative YES ok but no capacity (position_size=0)")
                    return None
                if position_size < Config.MIN_ORDER_CONTRACTS:
                    logger.info(f"📊 SKIP {market_ticker}: conservative YES size {position_size} < MIN_ORDER_CONTRACTS ({Config.MIN_ORDER_CONTRACTS})")
                    return None
                
                if best_yes_ask > Config.MAX_BUY_PRICE_CENTS:
                    logger.info(f"📊 SKIP {market_ticker}: conservative YES ask {best_yes_ask}¢ exceeds max price ({Config.MAX_BUY_PRICE_CENTS}¢)")
                    return None  # EXPLICIT: Don't trade above price limit

                # Apply portfolio-wide correlation adjustment via risk manager
                position_size = self.risk_manager.adjust_position_size(
                    position_size, market_ticker, 'yes'
                )
                if position_size <= 0:
                    logger.info(f"📊 SKIP {market_ticker}: risk manager reduced size to 0")
                    return None

                # Determine execution price (market making or taker)
                execution_price = best_yes_ask
                order_type = 'taker'
                if self.market_making_enabled and hasattr(self, 'order_router'):
                    routes = self.order_router.route_order(
                        side='yes',
                        count=position_size,
                        orderbook=orderbook,
                        our_fair_value=int(our_prob * 100),
                        edge=yes_edge,
                        urgency=Config.MM_ORDER_URGENCY
                    )
                    if routes:
                        execution_price = routes[0]['price']
                        order_type = routes[0]['type']
                        if order_type == 'maker':
                            logger.info(f"📝 Market making: posting at {execution_price}¢ (ask: {best_yes_ask}¢, saving {best_yes_ask - execution_price}¢)")

                logger.info(f"✓ Conservative YES {market_ticker}: Edge: {yes_edge:.2f}%, EV: ${yes_ev:.4f} (with fees), Our Prob: {our_prob:.2%} CI: [{ci_lower_yes:.1%}, {ci_upper_yes:.1%}], Price: {execution_price}¢")

                # Record position for exit logic
                self.active_positions[market_ticker] = {
                    'side': 'yes',
                    'entry_price': execution_price,
                    'entry_time': datetime.now(),
                    'count': position_size,
                    'edge': yes_edge,
                    'ev': yes_ev,
                    'strategy_mode': 'conservative'
                }

                # Build enhanced decision with analysis data
                time_factor = self._calculate_time_decay_factor(target_date, series_ticker) if Config.TIME_DECAY_ENABLED else 1.0
                corr_data = self._get_correlated_exposure(market_ticker) if Config.CORRELATION_ADJUSTMENT_ENABLED else {'correlation_factor': 1.0}

                decision = {
                    'action': 'buy',
                    'side': 'yes',
                    'count': position_size,
                    'price': execution_price,
                    'edge': yes_edge,
                    'ev': yes_ev,
                    'strategy_mode': 'conservative',
                    'order_type': order_type,
                    # Enhanced fields for analysis
                    'our_probability': our_prob,
                    'mean_forecast': mean_forecast,
                    'forecast_std': float(np.std(forecasts)) if len(forecasts) > 1 else 0,
                    'ci_lower': ci_lower_yes,
                    'ci_upper': ci_upper_yes,
                    'time_decay_factor': time_factor,
                    'num_sources': len(forecasts),
                    'threshold': str(threshold),
                    'target_date': target_date.strftime('%Y-%m-%d') if target_date else ''
                }

                # Log detailed trade decision for analysis
                self._log_trade_decision(market_ticker, {
                    'decision': 'conservative_yes',
                    'forecasts': [(f, s, t.isoformat() if hasattr(t, 'isoformat') else str(t))
                                 for f, s, t in self.weather_agg.forecast_metadata.get(
                                     f"{series_ticker}_{target_date.strftime('%Y-%m-%d')}", [])],
                    'ci_lower': ci_lower_yes,
                    'ci_upper': ci_upper_yes,
                    'time_decay_factor': time_factor,
                    'correlation_factor': corr_data['correlation_factor'],
                    'liquidity_cap': liquidity_cap,
                    'yes_edge': yes_edge,
                    'yes_ev': yes_ev,
                    'no_edge': no_edge,
                    'no_ev': no_ev,
                    'threshold': str(threshold),
                    'target_date': target_date.strftime('%Y-%m-%d') if target_date else '',
                    'is_longshot': False,
                    'series_ticker': series_ticker
                })

                return decision

            # Get required edge based on price (scaled edge for expensive contracts)
            required_no_edge = self._get_required_edge(best_no_ask)
            if no_edge >= required_no_edge and no_ev >= self.min_ev_threshold and (not self.require_high_confidence or high_confidence_no):
                # HYBRID POSITION SIZING for conservative trades
                # Use Kelly for high confidence (2+ sources, high prob), confidence scoring otherwise
                use_kelly = len(forecasts) >= 2 and no_prob > 0.7 and (ci_lower_no > best_no_ask / 100.0)

                # Position sizing: EV-proportional (new) or Kelly/Confidence (legacy)
                if Config.EV_PROPORTIONAL_ENABLED:
                    base_position = self._calculate_ev_proportional_size(no_ev, is_longshot=False)
                    logger.debug(f"EV-proportional sizing: EV=${no_ev:.4f}, position={base_position}")
                elif use_kelly:
                    # HIGH CONFIDENCE: Kelly Criterion with very conservative fractional (0.25)
                    payout_ratio = 1.0 / (best_no_ask / 100.0)
                    kelly_fraction = self.weather_agg.kelly_fraction(no_prob, payout_ratio, fractional=0.25)
                    portfolio = self.client.get_portfolio()
                    portfolio_value = (portfolio.get('balance', 0) + portfolio.get('portfolio_value', 0)) / 100.0
                    kelly_position = int(kelly_fraction * portfolio_value / (best_no_ask / 100.0))
                    base_position = min(max(kelly_position, self.max_position_size), self.max_position_size * 2)
                    logger.debug(f"Conservative Kelly: fraction={kelly_fraction:.3f}, position={base_position}")
                else:
                    # LOWER CONFIDENCE: Use confidence scoring
                    ci_width = ci_upper_no - ci_lower_no
                    confidence = self.weather_agg.calculate_confidence_score(
                        edge=no_edge,
                        ci_width=ci_width,
                        num_forecasts=len(forecasts),
                        ev=no_ev,
                        is_longshot=False
                    )
                    # Conservative: 0.5 confidence = 1x, 1.0 confidence = 1.5x
                    confidence_multiplier = 0.5 + (confidence * 1.0)  # 0.5x to 1.5x
                    base_position = int(self.max_position_size * confidence_multiplier)
                    base_position = max(1, min(base_position, self.max_position_size * 2))
                    logger.debug(f"Conservative Confidence: score={confidence:.3f}, multiplier={confidence_multiplier:.2f}x, position={base_position}")

                # Apply time decay factor (reduce size for markets further from temperature extreme)
                if Config.TIME_DECAY_ENABLED:
                    time_factor = self._calculate_time_decay_factor(target_date, series_ticker)
                    base_position = max(1, int(base_position * time_factor))
                    logger.debug(f"Time decay: factor={time_factor:.2f}, adjusted position={base_position}")

                # Apply correlation adjustment (reduce size when holding correlated positions)
                if Config.CORRELATION_ADJUSTMENT_ENABLED:
                    corr_data = self._get_correlated_exposure(market_ticker)
                    base_position = max(1, int(base_position * corr_data['correlation_factor']))
                    if corr_data['correlation_factor'] < 1.0:
                        logger.debug(f"Correlation adjustment: factor={corr_data['correlation_factor']:.2f}, correlated contracts={corr_data['total_contracts']}")

                # Calculate liquidity cap
                if Config.LIQUIDITY_CAP_ENABLED:
                    liquidity_cap = self._calculate_liquidity_cap(orderbook, 'no', int(best_no_ask))
                else:
                    liquidity_cap = self.max_position_size * 10  # Effectively no cap

                # Cap by REMAINING capacity, dollars, and liquidity
                dollar_cap_contracts = int(dollars_remaining * 100 / best_no_ask) if best_no_ask > 0 else contracts_remaining
                position_size = min(base_position, contracts_remaining, dollar_cap_contracts, liquidity_cap)

                if liquidity_cap < base_position:
                    logger.debug(f"Liquidity cap applied: {liquidity_cap} contracts (was {base_position})")

                if position_size <= 0:
                    logger.info(f"📊 SKIP {market_ticker}: conservative NO ok but no capacity (position_size=0)")
                    return None
                if position_size < Config.MIN_ORDER_CONTRACTS:
                    logger.info(f"📊 SKIP {market_ticker}: conservative NO size {position_size} < MIN_ORDER_CONTRACTS ({Config.MIN_ORDER_CONTRACTS})")
                    return None
                
                if best_no_ask > Config.MAX_BUY_PRICE_CENTS:
                    logger.info(f"📊 SKIP {market_ticker}: conservative NO ask {best_no_ask}¢ exceeds max price ({Config.MAX_BUY_PRICE_CENTS}¢)")
                    return None  # EXPLICIT: Don't trade above price limit

                # Apply portfolio-wide correlation adjustment via risk manager
                position_size = self.risk_manager.adjust_position_size(
                    position_size, market_ticker, 'no'
                )
                if position_size <= 0:
                    logger.info(f"📊 SKIP {market_ticker}: risk manager reduced size to 0")
                    return None

                # Determine execution price (market making or taker)
                execution_price = best_no_ask
                order_type = 'taker'
                if self.market_making_enabled and hasattr(self, 'order_router'):
                    routes = self.order_router.route_order(
                        side='no',
                        count=position_size,
                        orderbook=orderbook,
                        our_fair_value=int(no_prob * 100),
                        edge=no_edge,
                        urgency=Config.MM_ORDER_URGENCY
                    )
                    if routes:
                        execution_price = routes[0]['price']
                        order_type = routes[0]['type']
                        if order_type == 'maker':
                            logger.info(f"📝 Market making: posting at {execution_price}¢ (ask: {best_no_ask}¢, saving {best_no_ask - execution_price}¢)")

                logger.info(f"✓ Conservative NO {market_ticker}: Edge: {no_edge:.2f}%, EV: ${no_ev:.4f} (with fees), Our Prob: {no_prob:.2%} CI: [{ci_lower_no:.1%}, {ci_upper_no:.1%}], Price: {execution_price}¢")

                # Record position for exit logic
                self.active_positions[market_ticker] = {
                    'side': 'no',
                    'entry_price': execution_price,
                    'entry_time': datetime.now(),
                    'count': position_size,
                    'edge': no_edge,
                    'ev': no_ev,
                    'strategy_mode': 'conservative'
                }

                # Build enhanced decision with analysis data
                time_factor = self._calculate_time_decay_factor(target_date, series_ticker) if Config.TIME_DECAY_ENABLED else 1.0
                corr_data = self._get_correlated_exposure(market_ticker) if Config.CORRELATION_ADJUSTMENT_ENABLED else {'correlation_factor': 1.0}

                decision = {
                    'action': 'buy',
                    'side': 'no',
                    'count': position_size,
                    'price': execution_price,
                    'edge': no_edge,
                    'ev': no_ev,
                    'strategy_mode': 'conservative',
                    'order_type': order_type,
                    # Enhanced fields for analysis
                    'our_probability': no_prob,
                    'mean_forecast': mean_forecast,
                    'forecast_std': float(np.std(forecasts)) if len(forecasts) > 1 else 0,
                    'ci_lower': ci_lower_no,
                    'ci_upper': ci_upper_no,
                    'time_decay_factor': time_factor,
                    'num_sources': len(forecasts),
                    'threshold': str(threshold),
                    'target_date': target_date.strftime('%Y-%m-%d') if target_date else ''
                }

                # Log detailed trade decision for analysis
                self._log_trade_decision(market_ticker, {
                    'decision': 'conservative_no',
                    'forecasts': [(f, s, t.isoformat() if hasattr(t, 'isoformat') else str(t))
                                 for f, s, t in self.weather_agg.forecast_metadata.get(
                                     f"{series_ticker}_{target_date.strftime('%Y-%m-%d')}", [])],
                    'ci_lower': ci_lower_no,
                    'ci_upper': ci_upper_no,
                    'time_decay_factor': time_factor,
                    'correlation_factor': corr_data['correlation_factor'],
                    'liquidity_cap': liquidity_cap,
                    'yes_edge': yes_edge,
                    'yes_ev': yes_ev,
                    'no_edge': no_edge,
                    'no_ev': no_ev,
                    'threshold': str(threshold),
                    'target_date': target_date.strftime('%Y-%m-%d') if target_date else '',
                    'is_longshot': False,
                    'series_ticker': series_ticker
                })

                return decision

            # Diagnostic: log why we didn't trade (helps debug "no purchases")
            best_edge = max(yes_edge, no_edge)
            best_ev = max(yes_ev, no_ev)
            min_required_edge = min(required_yes_edge, required_no_edge)
            if yes_edge >= required_yes_edge and yes_ev >= self.min_ev_threshold and self.require_high_confidence and not high_confidence_yes:
                reason = f"YES edge {yes_edge:.1f}% EV ${yes_ev:.4f} ok but CI overlaps ask (REQUIRE_HIGH_CONFIDENCE=false to allow)"
            elif no_edge >= required_no_edge and no_ev >= self.min_ev_threshold and self.require_high_confidence and not high_confidence_no:
                reason = f"NO edge {no_edge:.1f}% EV ${no_ev:.4f} ok but CI overlaps ask (REQUIRE_HIGH_CONFIDENCE=false to allow)"
            elif best_edge < min_required_edge:
                reason = f"best edge {best_edge:.1f}% < {min_required_edge:.1f}%"
            elif best_ev < self.min_ev_threshold:
                reason = f"edge ok, best EV ${best_ev:.4f} < ${self.min_ev_threshold}"
            else:
                reason = "no side met edge/EV/confidence"
            logger.info(f"📊 SKIP {market_ticker}: {reason}")
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
        # Check if exit logic is enabled
        if not Config.EXIT_LOGIC_ENABLED:
            return None

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
            # For both YES and NO: profit = what we can sell for now - what we paid
            # We can sell by placing an order on the opposite side
            if side == 'yes':
                # We own YES, can sell at YES bid price
                sell_price = yes_orders[-1][0] if yes_orders else 50
            else:
                # We own NO, can sell at NO bid price
                sell_price = no_orders[-1][0] if no_orders else 50

            entry_cost = entry_price / 100.0
            current_value = sell_price / 100.0
            profit_cents = sell_price - entry_price
            profit_pct = ((current_value - entry_cost) / entry_cost) * 100 if entry_cost > 0 else 0

            # Exit condition 1: Take profit (configurable threshold)
            take_profit_threshold = Config.EXIT_TAKE_PROFIT_PERCENT
            min_profit_cents = Config.EXIT_MIN_PROFIT_CENTS
            if profit_pct >= take_profit_threshold and profit_cents >= min_profit_cents:
                logger.info(f"💰 Taking profit on {market_ticker}: {side.upper()} entry {entry_price}¢ -> sell {sell_price}¢ ({profit_pct:.1f}% / {profit_cents}¢ profit)")
                del self.active_positions[market_ticker]
                return {
                    'action': 'sell',
                    'side': side,
                    'count': position.get('count', 1),
                    'price': int(sell_price - 1),  # Slightly below bid to exit quickly
                    'reason': 'take_profit'
                }
            
            # Exit condition 2: Stop loss (price moved 30%+ against us)
            # Disabled for now - weather markets often recover, stop loss causes unnecessary losses
            # if profit_pct <= -30:
            #     logger.warning(f"Stop loss triggered on {market_ticker}: {side.upper()} entry {entry_price}¢ -> sell {sell_price}¢ ({profit_pct:.1f}% loss)")
            #     del self.active_positions[market_ticker]
            #     return {
            #         'action': 'sell',
            #         'side': side,
            #         'count': position.get('count', 1),
            #         'price': int(sell_price - 1),
            #         'reason': 'stop_loss'
            #     }
            
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
                    # Only exit on edge disappearing if we're not losing too much
                    # This prevents panic selling at a loss when edge fluctuates
                    if profit_pct >= -10:  # Only exit if not losing more than 10%
                        logger.info(f"📉 Edge disappeared on {market_ticker}: {side.upper()} (was {entry_edge:.1f}%), exiting at {sell_price}¢")
                        del self.active_positions[market_ticker]
                        return {
                            'action': 'sell',
                            'side': side,
                            'count': position.get('count', 1),
                            'price': int(sell_price - 1),
                            'reason': 'edge_gone'
                        }
                    else:
                        logger.debug(f"Edge gone on {market_ticker} but holding (loss: {profit_pct:.1f}%)")
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
