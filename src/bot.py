import asyncio
import csv
import json
import os
import time
import requests
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set
from src.kalshi_client import KalshiClient
from src.strategies import StrategyManager
from src.config import Config, extract_city_code
from src.logger import setup_logging
from src.outcome_tracker import OutcomeTracker
from src.dashboard import DashboardState, Dashboard

# Set up logging
setup_logging()
logger = logging.getLogger(__name__)


class KalshiTradingBot:
    """Main trading bot orchestrator"""
    
    def __init__(self):
        Config.validate()
        self.client = KalshiClient()
        
        # Weather markets only
        self.strategy_manager = StrategyManager(self.client)
        self.running = False
        self.markets_being_tracked = set()
        self.daily_pnl = 0
        self.last_reset_date = datetime.now().date()
        self.starting_weather_exposure = None  # Track starting weather position value for daily P&L
        self.today_start_timestamp = None  # Timestamp for filtering today's fills/settlements
        self._last_loss_limit_log = None  # Throttle loss limit log to once per hour
        
        # Track seen markets to detect new ones quickly
        self.seen_markets: Set[str] = set()

        # Track tickers with recently placed orders (local cache to avoid API calls)
        # Maps ticker -> timestamp of order placement
        self._recently_ordered_tickers: Dict[str, float] = {}
        
        # Track markets with determined outcomes (skip these in future scans)
        self.determined_outcome_markets: Set[str] = set()
        
        # Track orders we've already notified about (to avoid duplicate notifications)
        self.notified_orders: Set[str] = set()
        
        # Track relevant series for filtering (weather markets only)
        self.relevant_series: Set[str] = set()
        if 'weather_daily' in Config.ENABLED_STRATEGIES:
            self.relevant_series.update(Config.WEATHER_SERIES)
        
        # Adaptive city manager (shared with strategies)
        self.adaptive_manager = None
        if self.strategy_manager.strategies:
            # Get adaptive manager from first strategy (if available)
            first_strategy = self.strategy_manager.strategies[0]
            if hasattr(first_strategy, 'adaptive_manager'):
                self.adaptive_manager = first_strategy.adaptive_manager

        # Get drawdown protector from first strategy (if available)
        self.drawdown_protector = None
        if self.strategy_manager.strategies:
            first_strategy = self.strategy_manager.strategies[0]
            if hasattr(first_strategy, 'drawdown_protector'):
                self.drawdown_protector = first_strategy.drawdown_protector

        # Outcome tracker for learning from results
        weather_agg = self.strategy_manager.strategies[0].weather_agg if self.strategy_manager.strategies else None
        self.outcome_tracker = OutcomeTracker(self.client, weather_agg, self.adaptive_manager, self.drawdown_protector) if weather_agg else None
        self.last_outcome_check = 0  # Timestamp of last outcome check
        self._paper_session_pnl = 0.0  # Accumulated paper P&L for today

        # Reconcile outcomes.csv against Kalshi settlements on startup (skip in paper mode)
        if self.outcome_tracker and not Config.PAPER_TRADING:
            try:
                self.outcome_tracker.reconcile_with_kalshi()
            except Exception as e:
                logger.warning(f"Could not reconcile outcomes on startup: {e}")

        # Dashboard
        self.dashboard_enabled = os.getenv('DASHBOARD_ENABLED', 'true').lower() != 'false'
        self.dashboard_state = DashboardState()
        self.dashboard = Dashboard(self.dashboard_state)

        # In paper mode, load today's P&L and settlements from CSV on startup
        if Config.PAPER_TRADING:
            self._paper_session_pnl = self._load_todays_paper_pnl()
            self._load_todays_paper_settlements()
            self._load_paper_positions_to_dashboard()
    
    def reset_daily_stats(self):
        """Reset daily statistics"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            # Get starting weather position exposure for the day
            self.starting_weather_exposure = self._get_weather_exposure()
            # Set timestamp to filter today's fills/settlements (midnight local time)
            self.today_start_timestamp = int(datetime.combine(today, datetime.min.time()).timestamp() * 1000)
            self.daily_pnl = 0
            self._paper_session_pnl = 0.0
            self.last_reset_date = today
            self.client.invalidate_markets_cache()
            logger.info(f"Daily stats reset for {today}")
            logger.info(f"Starting weather exposure: ${self.starting_weather_exposure:.2f}")
    
    def _is_weather_ticker(self, ticker: str) -> bool:
        """Check if a ticker belongs to a weather market"""
        if not ticker:
            return False
        # Check if ticker starts with any weather series prefix
        for series in Config.WEATHER_SERIES:
            if ticker.startswith(series):
                return True
        return False

    def _get_weather_exposure(self) -> float:
        """Get total market exposure for weather positions only"""
        positions = self.client.get_positions()
        weather_exposure = 0.0
        for pos in positions:
            ticker = pos.get('ticker', '')
            if self._is_weather_ticker(ticker):
                # market_exposure is in cents
                weather_exposure += pos.get('market_exposure', 0) / 100.0
        return weather_exposure

    def _get_todays_weather_fills_cost(self) -> float:
        """Get total cost of weather market fills made today"""
        if self.today_start_timestamp is None:
            return 0.0
        fills = self.client.get_all_fills(since_ts=self.today_start_timestamp, action_filter='buy')
        cost = 0.0
        for fill in fills:
            ticker = fill.get('ticker', '')
            if self._is_weather_ticker(ticker):
                # Fill has 'count' (contracts) and 'yes_price' or 'no_price' in cents
                count = fill.get('count', 0)
                # Price depends on side
                if fill.get('side') == 'yes':
                    price = fill.get('yes_price', 0)
                else:
                    price = fill.get('no_price', 0)
                cost += (count * price) / 100.0  # Convert cents to dollars
        return cost

    def _get_todays_weather_settlements(self) -> float:
        """Get total settlements (payouts) from weather markets today"""
        if self.today_start_timestamp is None:
            return 0.0
        settlements = self.client.get_all_settlements(since_ts=self.today_start_timestamp)
        payout = 0.0
        for settlement in settlements:
            ticker = settlement.get('ticker', '')
            if self._is_weather_ticker(ticker):
                # revenue is in cents (can be positive payout or negative loss)
                payout += settlement.get('revenue', 0) / 100.0
        return payout

    def _load_todays_paper_pnl(self) -> float:
        """Load today's accumulated paper P&L from paper_outcomes.csv (for restart recovery)."""
        try:
            outcomes_file = Path("data/paper_outcomes.csv")
            if not outcomes_file.exists():
                return 0.0
            today_str = datetime.now().date().isoformat()
            total_pnl = 0.0
            with open(outcomes_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Match rows logged today (timestamp starts with today's date)
                    if row.get('timestamp', '').startswith(today_str):
                        try:
                            pnl = float(row.get('profit_loss', 0))
                            total_pnl += pnl
                        except (ValueError, TypeError):
                            pass
            if total_pnl != 0:
                logger.info(f"📋 Loaded today's paper P&L from CSV: ${total_pnl:.2f}")
            return total_pnl
        except Exception as e:
            logger.warning(f"Could not load today's paper P&L: {e}")
            return 0.0

    def _load_todays_paper_settlements(self):
        """Load today's paper settlements into dashboard state (for restart recovery)."""
        try:
            outcomes_file = Path("data/paper_outcomes.csv")
            if not outcomes_file.exists():
                return
            today_str = datetime.now().date().isoformat()
            count = 0
            with open(outcomes_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('timestamp', '').startswith(today_str):
                        ticker = row.get('market_ticker', '')
                        won = row.get('won', '') == 'YES'
                        try:
                            pnl = abs(float(row.get('profit_loss', 0)))
                        except (ValueError, TypeError):
                            pnl = 0.0
                        self.dashboard_state.record_settlement(ticker, won, pnl)
                        count += 1
            if count > 0:
                logger.info(f"📋 Loaded {count} paper settlement(s) into dashboard from CSV")
        except Exception as e:
            logger.warning(f"Could not load today's paper settlements: {e}")

    def _load_paper_positions_to_dashboard(self):
        """Load unsettled paper trades into dashboard city_positions for restart recovery."""
        try:
            trades_file = Path("data/trades.csv")
            if not trades_file.exists():
                return

            # Gather settled tickers so we skip them
            settled_tickers = set()
            outcomes_file = Path("data/paper_outcomes.csv")
            if outcomes_file.exists():
                with open(outcomes_file, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        settled_tickers.add(row.get('market_ticker', ''))

            count = 0
            with open(trades_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    order_id = row.get('order_id', '')
                    if not order_id.startswith('PAPER-'):
                        continue
                    ticker = row.get('market_ticker', '')
                    if not ticker or ticker in settled_tickers:
                        continue
                    side = row.get('side', 'yes')
                    action = row.get('action', 'buy')
                    try:
                        cnt = int(row.get('count', 1))
                        price = int(float(row.get('price', 0)))
                    except (ValueError, TypeError):
                        cnt, price = 1, 0
                    edge = 0.0
                    try:
                        edge = float(row.get('edge', 0))
                    except (ValueError, TypeError):
                        pass
                    self.dashboard_state.record_trade(
                        action, side, cnt, price, ticker,
                        strategy_mode=row.get('strategy_mode', ''),
                        edge=edge,
                    )
                    count += 1
            if count > 0:
                logger.info(f"📋 Loaded {count} paper position(s) into dashboard from trades.csv")
        except Exception as e:
            logger.warning(f"Could not load paper positions to dashboard: {e}")

    def check_daily_loss_limit(self):
        """Check if we've hit daily loss limit based on weather-only P&L"""
        self.reset_daily_stats()

        # Paper mode: use accumulated paper P&L instead of Kalshi API
        if Config.PAPER_TRADING:
            self.daily_pnl = self._paper_session_pnl
            if self.daily_pnl <= -Config.MAX_DAILY_LOSS:
                now = datetime.now()
                if self._last_loss_limit_log is None or (now - self._last_loss_limit_log).total_seconds() >= 3600:
                    logger.critical(f"⛔ Daily loss limit reached (paper mode)! P&L: ${self.daily_pnl:.2f} (limit: -${Config.MAX_DAILY_LOSS:.2f})")
                    self._last_loss_limit_log = now
                return True
            return False

        # Get current weather exposure
        current_weather_exposure = self._get_weather_exposure()

        # Calculate daily P&L for weather markets only
        # P&L = (current exposure + settlements) - (starting exposure + fills cost)
        if self.starting_weather_exposure is None:
            # First check after restart - back-calculate starting exposure from
            # today's fills/settlements so the loss limit survives restarts.
            # starting_exposure = current_exposure + fills_cost - settlements
            self.today_start_timestamp = int(datetime.combine(datetime.now().date(), datetime.min.time()).timestamp() * 1000)
            todays_fills = self._get_todays_weather_fills_cost()
            todays_settlements = self._get_todays_weather_settlements()
            self.starting_weather_exposure = current_weather_exposure + todays_fills - todays_settlements
            logger.info(f"Reconstructed starting exposure: ${self.starting_weather_exposure:.2f} (current=${current_weather_exposure:.2f}, fills=${todays_fills:.2f}, settlements=${todays_settlements:.2f})")
            # Fall through to compute actual P&L (don't assume $0)

        todays_fills_cost = self._get_todays_weather_fills_cost()
        todays_settlements = self._get_todays_weather_settlements()

        # Total invested = starting exposure + new buys today
        total_invested = self.starting_weather_exposure + todays_fills_cost
        # Total return = current exposure + settlements received
        total_return = current_weather_exposure + todays_settlements

        self.daily_pnl = total_return - total_invested

        # Check if we've hit the loss limit
        if self.daily_pnl <= -Config.MAX_DAILY_LOSS:
            now = datetime.now()
            if self._last_loss_limit_log is None or (now - self._last_loss_limit_log).total_seconds() >= 3600:
                logger.critical(f"⛔ Daily loss limit reached (weather markets only)!")
                logger.critical(f"Starting weather exposure: ${self.starting_weather_exposure:.2f}")
                logger.critical(f"Current weather exposure: ${current_weather_exposure:.2f}")
                logger.critical(f"Weather P&L: ${self.daily_pnl:.2f} (limit: -${Config.MAX_DAILY_LOSS:.2f})")
                self._last_loss_limit_log = now
            return True
        return False
    
    def check_filled_orders(self):
        """Check for filled orders and send notifications"""
        if Config.PAPER_TRADING:
            return  # No real orders to check in paper mode
        try:
            try:
                filled_orders = self.client.get_orders(status='filled')
            except Exception as e:
                # Don't crash on 429 or other API errors - log and skip this cycle
                logger.warning(f"Could not fetch filled orders (will retry next cycle): {e}")
                return
            
            for order in filled_orders:
                order_id = order.get('order_id')
                
                # Skip if we've already notified about this order
                if order_id in self.notified_orders:
                    continue
                
                # Only notify about recently filled orders (within last 5 minutes)
                # This prevents notifying about old filled orders on startup
                last_update = order.get('last_update_time')
                if last_update:
                    try:
                        update_time = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                        now = datetime.now(timezone.utc)
                        if (now - update_time).total_seconds() > 300:  # 5 minutes
                            continue
                    except (ValueError, AttributeError, KeyError, TypeError):
                        # If we can't parse time, skip this order (likely old)
                        pass
                
                # Mark as notified
                self.notified_orders.add(order_id)
                
                # Get order details
                action = order.get('action', 'buy').upper()
                side = order.get('side', 'yes').upper()
                fill_count = order.get('fill_count', 0)
                ticker = order.get('ticker', 'unknown')
                
                # Get fill price (average of fills)
                yes_price = order.get('yes_price', 0)
                no_price = order.get('no_price', 0)
                fill_price = yes_price if yes_price > 0 else no_price
                
                if fill_count > 0:
                    # Record fill on dashboard
                    self.dashboard_state.record_fill(action, side, fill_count, fill_price, ticker)

                    # Send notification
                    self._send_notification(
                        f"✅ Trade Filled: {action} {side}",
                        f"{fill_count} contract(s) @ {fill_price}¢\nMarket: {ticker}"
                    )
                    logger.info(f"📬 Notification sent: {action} {fill_count} {side} @ {fill_price}¢ filled for {ticker}")

                    # Render dashboard on fill events
                    self._maybe_render_dashboard()
        
        except Exception as e:
            logger.error(f"Error checking filled orders: {e}", exc_info=True)
    
    def check_and_cancel_stale_orders(self):
        """Check resting orders and cancel if edge/EV no longer meets strategy thresholds"""
        # Skip entirely in paper mode — no real Kalshi orders to cancel
        if Config.PAPER_TRADING:
            return
        try:
            try:
                # Use fresh data (no cache) for accurate stale order detection
                resting_orders = self.client.get_orders(status='resting', use_cache=False)
            except Exception as e:
                logger.warning(f"Could not fetch resting orders (will retry next cycle): {e}")
                return
            if not resting_orders:
                return

            for order in resting_orders:
                order_id = order.get('order_id')
                ticker = order.get('ticker')
                side = order.get('side')
                order_price = order.get('yes_price') or order.get('no_price', 0)

                if not ticker:
                    continue

                # IMPORTANT: Check order age before considering cancellation
                # This prevents the place->cancel->place churn loop
                created_time = order.get('created_time')
                if created_time:
                    try:
                        # Parse ISO format timestamp
                        if created_time.endswith('Z'):
                            created_dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                        else:
                            created_dt = datetime.fromisoformat(created_time)

                        now = datetime.now(timezone.utc)
                        age_minutes = (now - created_dt).total_seconds() / 60

                        min_age = Config.STALE_ORDER_MIN_AGE_MINUTES
                        if age_minutes < min_age:
                            logger.debug(f"Skipping stale check for {order_id}: order is only {age_minutes:.1f} min old (min: {min_age} min)")
                            continue
                    except Exception as e:
                        logger.debug(f"Could not parse order time for {order_id}: {e}")
                        # Continue with cancellation check if we can't parse time

                # Get current market data
                try:
                    # Get market info - fetch by specific ticker to avoid missing it in large lists
                    try:
                        market_response = self.client.get_market(ticker)
                        # API returns {'market': {...}}, extract the market data
                        market = market_response.get('market') if market_response else None
                    except Exception as e:
                        # If we can't fetch the market, it might be closed or invalid
                        # But don't cancel immediately - could be a transient API error
                        logger.debug(f"Could not fetch market {ticker}: {e}")
                        continue  # Skip this order, don't cancel

                    if not market:
                        # Market definitely doesn't exist, cancel order
                        logger.info(f"🗑️  Canceling order {order_id}: Market {ticker} not found (likely closed)")
                        self.client.cancel_order(order_id)
                        self.client.invalidate_orders_cache()
                        self.dashboard_state.record_cancel(order_id, 'market closed')
                        continue
                    
                    # Get current orderbook
                    orderbook = self.client.get_market_orderbook(ticker)
                    
                    # Re-evaluate market with strategy (pass orderbook to avoid re-fetching)
                    decisions = self.strategy_manager.evaluate_market(market, orderbook)
                    
                    # Check if any decision matches our order
                    order_still_valid = False
                    
                    # Get strategy thresholds
                    weather_strategy = next((s for s in self.strategy_manager.strategies 
                                            if s.name == 'WeatherDailyStrategy'), None)
                    
                    if not weather_strategy:
                        # No weather strategy, skip cancellation check
                        continue
                    
                    # Get current ask prices
                    yes_orders = orderbook.get('orderbook', {}).get('yes', [])
                    no_orders = orderbook.get('orderbook', {}).get('no', [])
                    # Arrays are ascending, so calculate asks from opposite bids
                    # YES ask = 100 - NO bid (highest), NO ask = 100 - YES bid (highest)
                    best_no_bid = no_orders[-1][0] if no_orders else market.get('no_price', 50)
                    best_yes_bid = yes_orders[-1][0] if yes_orders else market.get('yes_price', 50)
                    current_yes_ask = 100 - best_no_bid
                    current_no_ask = 100 - best_yes_bid
                    current_ask = current_yes_ask if side == 'yes' else current_no_ask
                    
                    for decision in decisions:
                        decision_side = decision.get('side')
                        edge = decision.get('edge', 0)
                        ev = decision.get('ev', 0)
                        strategy_mode = decision.get('strategy_mode', 'conservative')
                        
                        # Check if this decision matches our order side
                        if decision_side == side:
                            # Check if still meets strategy thresholds
                            if strategy_mode == 'longshot':
                                # Longshot thresholds
                                if (current_ask <= weather_strategy.longshot_max_price and 
                                    edge >= weather_strategy.longshot_min_edge and 
                                    ev > 0):
                                    order_still_valid = True
                                    break
                            else:
                                # Conservative thresholds
                                if edge >= weather_strategy.min_edge_threshold and ev >= weather_strategy.min_ev_threshold:
                                    order_still_valid = True
                                    break
                    
                    # If no matching decision found, or decision doesn't meet thresholds, cancel
                    if not order_still_valid:
                        logger.info(f"🗑️  Canceling order {order_id}: Edge/EV no longer meets strategy thresholds")
                        logger.debug(f"Market: {ticker}, Side: {side.upper()}, Order Price: {order_price}¢, Current Ask: {current_ask}¢")
                        try:
                            self.client.cancel_order(order_id)
                            self.client.invalidate_orders_cache()  # Ensure fresh data for next exposure check
                            logger.info(f"✅ Order {order_id} canceled successfully")
                            self.dashboard_state.record_cancel(order_id, 'stale edge')
                        except Exception as e:
                            logger.warning(f"Error canceling order {order_id}: {e}")
                
                except Exception as e:
                    logger.warning(f"Error evaluating order {order_id} for cancellation: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error checking stale orders: {e}", exc_info=True)
    
    def _send_notification(self, title: str, message: str):
        """Send macOS notification"""
        try:
            import subprocess
            script = f'''
            display notification "{message}" with title "{title}"
            '''
            subprocess.run(['osascript', '-e', script], capture_output=True)
        except Exception as e:
            # Silently fail if notifications don't work
            pass
    
    def scan_and_trade(self):
        """Scan markets and execute trades"""
        if self.check_daily_loss_limit():
            return

        logger.debug(f"Scanning markets at {datetime.now()}")

        # Track markets evaluated this scan to prevent duplicate evaluations
        # This prevents the same ticker from being evaluated multiple times
        # if it appears in multiple threshold lists within the same scan
        markets_traded_this_scan: Set[str] = set()
        self._scan_traded_count = 0
        self._scan_skipped_count = 0
        self._scan_total_count = 0

        # Clear pending cross-threshold decisions from previous scan
        for strategy in self.strategy_manager.strategies:
            if hasattr(strategy, 'clear_pending_decisions'):
                strategy.clear_pending_decisions()

        # Fetch resting orders once and push snapshot to all strategies
        # (single-threaded bot — orders can't change mid-scan except when we place/cancel)
        # In paper mode, use empty list (no real Kalshi orders exist)
        if Config.PAPER_TRADING:
            resting_snapshot = []
        else:
            try:
                resting_snapshot = self.client.get_orders(status='resting', use_cache=False)
            except Exception:
                resting_snapshot = None  # strategies will fall back to per-call API fetch
        for strategy in self.strategy_manager.strategies:
            strategy._resting_orders_snapshot = resting_snapshot

        try:
            # Filter markets by relevant series FIRST to reduce API calls
            # Increase limit to catch all markets, especially new ones
            # Check both 'open' and 'active' status to catch all tradeable markets
            relevant_markets = []
            for series_ticker in self.relevant_series:
                # Get open markets (primary status)
                try:
                    open_markets = self.client.get_markets(series_ticker=series_ticker, status='open', limit=200)
                except Exception as e:
                    logger.warning(f"Error fetching open markets for {series_ticker}: {e}")
                    open_markets = []
                
                # Try to get active markets (some series may not support this status)
                active_markets = []
                try:
                    active_markets = self.client.get_markets(series_ticker=series_ticker, status='active', limit=200)
                except Exception:
                    # Active status not supported for this series, skip silently
                    pass
                
                # Combine and deduplicate by ticker
                seen_tickers = set()
                for market in open_markets + active_markets:
                    ticker = market.get('ticker')
                    if ticker and ticker not in seen_tickers:
                        seen_tickers.add(ticker)
                        relevant_markets.append(market)
            
            # Detect new markets (prioritize them for early entry)
            # Also filter out markets with determined outcomes
            new_markets = []
            existing_markets = []
            for market in relevant_markets:
                market_ticker = market.get('ticker', '')
                
                # Skip markets with determined outcomes
                if market_ticker in self.determined_outcome_markets:
                    continue
                
                if market_ticker not in self.seen_markets:
                    new_markets.append(market)
                    self.seen_markets.add(market_ticker)
                else:
                    existing_markets.append(market)
            
            # Process new markets FIRST (critical for early entry)
            if new_markets:
                logger.info(f"🆕 Found {len(new_markets)} NEW markets! Processing immediately...")
            
            # Combine: new markets first, then existing
            markets_to_process = new_markets + existing_markets
            logger.debug(f"Found {len(markets_to_process)} relevant markets ({len(new_markets)} new, {len(existing_markets)} existing)")
            
            # Debug: show market details
            if markets_to_process:
                sample = markets_to_process[0]
                logger.debug(f"Sample market: {sample.get('ticker')} | Series: {sample.get('series_ticker')} | Volume: {sample.get('volume', 0)} | Status: {sample.get('status')}")
            
            self._scan_total_count = len(markets_to_process)
            markets_evaluated = 0
            for i, market in enumerate(markets_to_process):
                market_ticker = market.get('ticker', '')

                # CRITICAL: Skip if we already evaluated this ticker this scan
                # This prevents duplicate orders when the same market appears multiple times
                if market_ticker in markets_traded_this_scan:
                    logger.debug(f"📊 SKIP {market_ticker}: already evaluated this scan")
                    self._scan_skipped_count += 1
                    continue
                markets_traded_this_scan.add(market_ticker)

                # Skip tickers with recently placed orders (local guard, no API call)
                # Prevents duplicate orders when API is rate-limited and can't verify resting orders
                recent_ts = self._recently_ordered_tickers.get(market_ticker)
                if recent_ts and (time.time() - recent_ts) < 600:  # 10-minute cooldown
                    logger.debug(f"📊 SKIP {market_ticker}: order placed {(time.time() - recent_ts):.0f}s ago (cooldown)")
                    self._scan_skipped_count += 1
                    continue

                # Quick filter check before expensive orderbook call (no API calls, so no pacing needed)
                should_trade = any(strategy.should_trade(market) for strategy in self.strategy_manager.strategies)
                if not should_trade:
                    ticker = market.get('ticker', 'unknown')
                    series = market.get('series_ticker', '') or market.get('series_ticker_symbol', '')
                    status = market.get('status', 'unknown')
                    volume = market.get('volume', 0)
                    if series and series not in Config.WEATHER_SERIES and not any(ticker.startswith(p) for p in ['KXHIGH', 'KXLOW']):
                        logger.debug(f"📊 SKIP {ticker}: not a weather series ({series})")
                    elif status not in ('open', 'active'):
                        logger.debug(f"📊 SKIP {ticker}: status={status} (need open/active)")
                    elif volume < Config.MIN_MARKET_VOLUME:
                        logger.debug(f"📊 SKIP {ticker}: volume {volume} < {Config.MIN_MARKET_VOLUME}")
                    else:
                        logger.debug(f"📊 SKIP {ticker}: filtered by strategy (should_trade=False)")
                    self._scan_skipped_count += 1
                    continue
                
                markets_evaluated += 1

                # Re-check daily loss limit before each evaluation (prevents trading during long scans)
                if self.check_daily_loss_limit():
                    break

                # Pace API calls: 250ms between markets that actually get evaluated
                if markets_evaluated > 1 and not Config.PAPER_TRADING:
                    time.sleep(0.25)

                logger.debug(f"Evaluating market: {market.get('ticker', 'unknown')} - {market.get('title', 'unknown')[:50]}")
                
                # Evaluate market with all strategies
                try:
                    decisions = self.strategy_manager.evaluate_market(market)
                except Exception as e:
                    logger.warning(f"Error evaluating market {market.get('ticker', 'unknown')}: {e}", exc_info=True)
                    continue
                
                for decision in decisions:
                    strategy_name = decision.pop('strategy')
                    market_ticker = decision.pop('market_ticker')
                    
                    # Execute trade
                    strategy = next(s for s in self.strategy_manager.strategies if s.name == strategy_name)
                    order = strategy.execute_trade(decision, market_ticker)
                    
                    if order:
                        self.markets_being_tracked.add(market_ticker)
                        self._recently_ordered_tickers[market_ticker] = time.time()
                        self._scan_traded_count += 1

                        # Refresh resting orders snapshot after placement (skip in paper mode — no real orders)
                        if not Config.PAPER_TRADING:
                            try:
                                resting_snapshot = self.client.get_orders(status='resting', use_cache=False)
                                for strategy in self.strategy_manager.strategies:
                                    strategy._resting_orders_snapshot = resting_snapshot
                            except Exception:
                                pass

                        # Record trade on dashboard
                        self.dashboard_state.record_trade(
                            decision.get('action', 'buy'),
                            decision.get('side', '?'),
                            decision.get('count', 0),
                            decision.get('price', 0),
                            market_ticker,
                            strategy_mode=decision.get('strategy_mode', ''),
                            edge=decision.get('edge', 0.0),
                        )

                        # Log trade summary
                        logger.info(f"Trade executed successfully - Market: {market_ticker}")
                        logger.debug(f"Active positions being tracked: {len(self.markets_being_tracked)}")

                        if not Config.PAPER_TRADING:
                            time.sleep(0.3)  # Rate limiting delay (unnecessary in paper mode)

            # Flush cross-threshold decisions: execute best decision per base market
            for strategy in self.strategy_manager.strategies:
                if not hasattr(strategy, 'get_pending_decisions'):
                    continue
                for decision in strategy.get_pending_decisions():
                    strategy_name = decision.pop('strategy')
                    market_ticker = decision.pop('market_ticker')

                    if self.check_daily_loss_limit():
                        break

                    order = strategy.execute_trade(decision, market_ticker)
                    if order:
                        self.markets_being_tracked.add(market_ticker)
                        self._recently_ordered_tickers[market_ticker] = time.time()
                        self._scan_traded_count += 1

                        # Refresh resting orders snapshot after placement (skip in paper mode)
                        if not Config.PAPER_TRADING:
                            try:
                                resting_snapshot = self.client.get_orders(status='resting', use_cache=False)
                                for s in self.strategy_manager.strategies:
                                    s._resting_orders_snapshot = resting_snapshot
                            except Exception:
                                pass

                        self.dashboard_state.record_trade(
                            decision.get('action', 'buy'),
                            decision.get('side', '?'),
                            decision.get('count', 0),
                            decision.get('price', 0),
                            market_ticker,
                            strategy_mode=decision.get('strategy_mode', ''),
                            edge=decision.get('edge', 0.0),
                        )

                        logger.info(f"Trade executed successfully - Market: {market_ticker}")
                        if not Config.PAPER_TRADING:
                            time.sleep(0.3)

        except Exception as e:
            self.dashboard_state.record_error()
            logger.error(f"Error in scan_and_trade: {e}", exc_info=True)
        finally:
            # Clear resting orders snapshot at end of scan
            for strategy in self.strategy_manager.strategies:
                strategy._resting_orders_snapshot = None
    
    async def handle_websocket_messages(self, websocket):
        """Handle incoming WebSocket messages"""
        # Subscribe to ticker updates
        await self.client.subscribe_to_ticker(websocket)
        
        # Subscribe to orderbook for tracked markets
        if self.markets_being_tracked:
            await self.client.subscribe_to_orderbook(
                websocket, 
                list(self.markets_being_tracked)
            )
        
        print("[Bot] WebSocket subscriptions active")
        
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type')
                
                if msg_type == 'ticker':
                    # Handle ticker update
                    market_ticker = data.get('data', {}).get('market_ticker')
                    bid = data.get('data', {}).get('bid')
                    ask = data.get('data', {}).get('ask')
                    print(f"[WS] {market_ticker}: Bid {bid}¢, Ask {ask}¢")
                
                elif msg_type == 'orderbook_delta':
                    # Handle orderbook update
                    market_ticker = data.get('data', {}).get('market_ticker')
                    print(f"[WS] Orderbook update for {market_ticker}")
                
                elif msg_type == 'subscribed':
                    print(f"[WS] Subscribed: {data}")
                
                elif msg_type == 'error':
                    error_msg = data.get('msg', {})
                    print(f"[WS] Error: {error_msg}")
            
            except json.JSONDecodeError:
                print(f"[WS] Invalid JSON: {message}")
            except Exception as e:
                print(f"[WS] Error processing message: {e}")
    
    async def run_websocket(self):
        """Run WebSocket connection"""
        while self.running:
            try:
                await self.client.connect_websocket(self.handle_websocket_messages)
            except Exception as e:
                logger.warning(f"WebSocket error: {e}, reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    def _manage_market_maker_orders(self):
        """
        Manage market maker orders - requote if outbid.

        This iterates through all strategies that have market making enabled
        and calls their market maker's manage_orders() method.
        """
        try:
            for strategy in self.strategy_manager.strategies:
                if hasattr(strategy, 'market_maker') and strategy.market_making_enabled:
                    managed_count = len(strategy.market_maker.get_managed_orders())
                    if managed_count > 0:
                        logger.debug(f"Managing {managed_count} market maker orders...")
                        strategy.market_maker.manage_orders()
        except Exception as e:
            logger.debug(f"Error managing market maker orders: {e}")

    def _maybe_render_dashboard(self, force: bool = False):
        """Render the dashboard if enabled (rate-limited unless forced)."""
        if not self.dashboard_enabled:
            return
        self.dashboard.render(force=force)

    def _update_dashboard_account(self):
        """Fetch account data and update dashboard state."""
        try:
            portfolio = self.client.get_portfolio()
            balance = portfolio.get('balance', 0) / 100
            portfolio_value = portfolio.get('portfolio_value', 0) / 100
            exposure = self._get_weather_exposure()

            # Count active positions and resting orders
            positions = self.client.get_positions()
            active_count = sum(1 for p in positions if p.get('position', 0) != 0)
            try:
                resting = self.client.get_orders(status='resting')
                resting_count = len(resting)
            except Exception:
                resting_count = 0

            self.dashboard_state.update_account(
                cash=balance,
                portfolio_value=portfolio_value,
                daily_pnl=self.daily_pnl,
                daily_loss_limit=Config.MAX_DAILY_LOSS,
                exposure=exposure,
            )
            self.dashboard_state.update_positions(active_count, resting_count)

            # Update strategy status (drawdown, cities, sources)
            self._update_dashboard_strategy_status()

            return balance, portfolio_value
        except Exception as e:
            logger.debug(f"Could not update dashboard account: {e}")
            return None, None

    def _update_dashboard_strategy_status(self):
        """Gather strategy status info for the dashboard."""
        try:
            dd_level = 'NORMAL'
            dd_consecutive = 0
            dd_multiplier = 1.0
            forecast_sources = 0
            cities_enabled = []
            cities_disabled = []

            for strategy in self.strategy_manager.strategies:
                # Drawdown protector
                if hasattr(strategy, 'drawdown_protector') and strategy.drawdown_protector:
                    dp = strategy.drawdown_protector
                    status = dp.get_status()
                    dd_level = status.get('level', 'NORMAL')
                    dd_consecutive = status.get('consecutive_losses', 0)
                    dd_multiplier = dp.get_position_multiplier()

                # Forecast sources count
                if hasattr(strategy, 'weather_agg'):
                    sources = strategy.weather_agg.get_enabled_sources()
                    forecast_sources = len(sources) if sources else 0

                # Adaptive city status
                if hasattr(strategy, 'adaptive_manager') and strategy.adaptive_manager:
                    am = strategy.adaptive_manager
                    seen_cities = set()
                    for series in Config.WEATHER_SERIES:
                        city = extract_city_code(series)
                        if city in seen_cities:
                            continue
                        seen_cities.add(city)
                        if city.upper() in Config.DISABLED_CITIES:
                            cities_disabled.append(city)
                        elif not am.is_city_enabled(series):
                            cities_disabled.append(city)
                        else:
                            cities_enabled.append(city)

            # Deduplicate city lists
            cities_enabled = sorted(set(cities_enabled))
            cities_disabled = sorted(set(cities_disabled))

            self.dashboard_state.update_strategy_status(
                drawdown_level=dd_level,
                drawdown_consecutive=dd_consecutive,
                drawdown_multiplier=dd_multiplier,
                forecast_sources=forecast_sources,
                cities_enabled=cities_enabled,
                cities_disabled=cities_disabled,
            )
        except Exception as e:
            logger.debug(f"Could not update strategy status: {e}")

    def run(self, use_websocket: bool = False):
        """Run the trading bot"""
        self.running = True
        logger.info("Starting Kalshi Trading Bot...")
        logger.info(f"Enabled strategies: {', '.join(Config.ENABLED_STRATEGIES)}")
        
        # Get initial portfolio balance
        try:
            portfolio = self.client.get_portfolio()
            balance = portfolio.get('balance', 0) / 100
            portfolio_value = portfolio.get('portfolio_value', 0) / 100
            logger.info(f"Portfolio balance: ${balance:.2f}, Portfolio value: ${portfolio_value:.2f}")
        except Exception as e:
            logger.error(f"Could not fetch portfolio: {e}", exc_info=True)
        
        if use_websocket:
            # Run with WebSocket for real-time updates
            logger.info("Starting WebSocket connection...")
            asyncio.run(self.run_websocket())
        else:
            # Run polling mode
            logger.info("Running in polling mode...")
            if 'weather_daily' in Config.ENABLED_STRATEGIES:
                logger.info(f"Scan interval: 30 seconds (Kalshi odds check) | Weather forecast cache: {Config.FORECAST_CACHE_TTL/60:.0f} min")
            else:
                logger.info("Scan interval: 15 seconds")
            # Heartbeat interval (5 min so dashboard refreshes regularly)
            heartbeat_interval = 300
            last_heartbeat = time.time()
            first_scan_done = False

            while self.running:
                try:
                    scan_start = time.time()
                    self.scan_and_trade()
                    scan_duration = time.time() - scan_start

                    # Record scan stats on dashboard
                    self.dashboard_state.record_scan(
                        markets=getattr(self, '_scan_total_count', 0),
                        skipped=getattr(self, '_scan_skipped_count', 0),
                        traded=getattr(self, '_scan_traded_count', 0),
                        duration=scan_duration,
                    )

                    # Log scan completion (goes to file only via filter)
                    logger.info(f"✅ Scan complete in {scan_duration:.1f}s. Next scan in {max(0, 30 - scan_duration):.0f}s")

                    # Render dashboard immediately after first scan
                    if not first_scan_done:
                        first_scan_done = True
                        self._update_dashboard_account()
                        self._maybe_render_dashboard(force=True)

                    # Check for filled orders and send notifications
                    self.check_filled_orders()

                    # Check and cancel stale orders (edge/EV no longer valid)
                    self.check_and_cancel_stale_orders()

                    # Manage market maker orders (requote if outbid)
                    self._manage_market_maker_orders()

                    # Check for settled positions and update forecast model (every hour)
                    outcome_check_interval = 3600  # 1 hour
                    if self.outcome_tracker and time.time() - self.last_outcome_check >= outcome_check_interval:
                        try:
                            settlement_results = self.outcome_tracker.run_outcome_check() or []
                            self.last_outcome_check = time.time()
                            for result in settlement_results:
                                self.dashboard_state.record_settlement(result['ticker'], result['won'], result['pnl'])
                                if Config.PAPER_TRADING:
                                    self._paper_session_pnl += result['signed_pnl']
                            if settlement_results:
                                self._update_dashboard_account()
                                self._maybe_render_dashboard(force=True)
                        except Exception as e:
                            logger.error(f"Error checking outcomes: {e}", exc_info=True)
                    
                    # Heartbeat logging to confirm bot is alive + render dashboard
                    if time.time() - last_heartbeat >= heartbeat_interval:
                        portfolio = self.client.get_portfolio()
                        balance = portfolio.get('balance', 0) / 100  # Convert cents to dollars
                        portfolio_value = portfolio.get('portfolio_value', 0) / 100  # Convert cents to dollars
                        total_value = balance + portfolio_value

                        # Update weather-only daily P&L for heartbeat
                        if Config.PAPER_TRADING:
                            self.daily_pnl = self._paper_session_pnl
                        else:
                            current_weather_exposure = self._get_weather_exposure()
                            if self.starting_weather_exposure is not None:
                                todays_fills_cost = self._get_todays_weather_fills_cost()
                                todays_settlements = self._get_todays_weather_settlements()
                                total_invested = self.starting_weather_exposure + todays_fills_cost
                                total_return = current_weather_exposure + todays_settlements
                                self.daily_pnl = total_return - total_invested

                        logger.info(f"❤️  Heartbeat: Running for {(time.time() - last_heartbeat)/3600:.1f}h")
                        logger.info(f"   Account - Cash: ${balance:.2f}, Portfolio: ${portfolio_value:.2f}, Total: ${total_value:.2f}")
                        logger.info(f"   Weather P&L: ${self.daily_pnl:.2f} (limit: -${Config.MAX_DAILY_LOSS:.2f})")
                        last_heartbeat = time.time()

                        # Update dashboard with fresh account data and render
                        self._update_dashboard_account()
                        self._maybe_render_dashboard(force=True)
                    
                    # Adaptive scan intervals based on market type
                    # Weather daily: 30s (frequent Kalshi odds check, weather forecasts cached)
                    if 'weather_daily' in Config.ENABLED_STRATEGIES:
                        sleep_time = max(0, 30 - scan_duration)  # 30 seconds - frequent Kalshi odds check (forecasts cached)
                    else:
                        sleep_time = max(0, 15 - scan_duration)  # 15 second default
                    
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                        
                except KeyboardInterrupt:
                    logger.info("\nShutting down...")
                    self.running = False
                except ConnectionError as e:
                    logger.warning(f"Connection error: {e}. Retrying in 30 seconds...")
                    time.sleep(30)
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Network error: {e}. Retrying in 30 seconds...")
                    time.sleep(30)
                except Exception as e:
                    logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                    logger.info("Continuing in 60 seconds...")
                    time.sleep(60)
    
    def stop(self):
        """Stop the bot"""
        self.running = False
        logger.info("Bot stopped")


if __name__ == '__main__':
    bot = KalshiTradingBot()
    
    # Run in polling mode (set use_websocket=True for WebSocket mode)
    bot.run(use_websocket=False)
