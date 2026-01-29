import asyncio
import json
import time
import requests
import logging
from datetime import datetime
from typing import Dict, List, Set
from src.kalshi_client import KalshiClient
from src.strategies import StrategyManager
from src.config import Config
from src.logger import setup_logging
from src.outcome_tracker import OutcomeTracker

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
        self.starting_account_value = None  # Track starting account value for daily P&L
        
        # Track seen markets to detect new ones quickly
        self.seen_markets: Set[str] = set()
        
        # Track markets with determined outcomes (skip these in future scans)
        self.determined_outcome_markets: Set[str] = set()
        
        # Track orders we've already notified about (to avoid duplicate notifications)
        self.notified_orders: Set[str] = set()
        
        # Track relevant series for filtering (weather markets only)
        self.relevant_series: Set[str] = set()
        if 'weather_daily' in Config.ENABLED_STRATEGIES:
            self.relevant_series.update(Config.WEATHER_SERIES)
        
        # Outcome tracker for learning from results
        weather_agg = self.strategy_manager.strategies[0].weather_agg if self.strategy_manager.strategies else None
        self.outcome_tracker = OutcomeTracker(self.client, weather_agg) if weather_agg else None
        self.last_outcome_check = 0  # Timestamp of last outcome check
    
    def reset_daily_stats(self):
        """Reset daily statistics"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            # Get starting account value (balance + portfolio_value) for the day
            portfolio = self.client.get_portfolio(use_cache=False)  # Force fresh data for daily reset
            balance = portfolio.get('balance', 0) / 100.0  # Convert cents to dollars
            portfolio_value = portfolio.get('portfolio_value', 0) / 100.0
            self.starting_account_value = balance + portfolio_value
            self.daily_pnl = 0
            self.last_reset_date = today
            logger.info(f"Daily stats reset for {today}")
            logger.info(f"Starting account value: ${self.starting_account_value:.2f}")
    
    def check_daily_loss_limit(self):
        """Check if we've hit daily loss limit based on total portfolio P&L"""
        self.reset_daily_stats()
        
        # Get current account value (cash balance + portfolio value)
        portfolio = self.client.get_portfolio()  # Uses cache
        balance = portfolio.get('balance', 0) / 100.0  # Convert cents to dollars
        portfolio_value = portfolio.get('portfolio_value', 0) / 100.0
        current_account_value = balance + portfolio_value
        
        # Calculate daily P&L from account value change
        if self.starting_account_value is not None:
            self.daily_pnl = current_account_value - self.starting_account_value
        else:
            # First check of the day - set starting value
            self.starting_account_value = current_account_value
            self.daily_pnl = 0
        
        # Check if we've hit the loss limit
        if self.daily_pnl <= -Config.MAX_DAILY_LOSS:
            logger.critical(f"⛔ Daily loss limit reached!")
            logger.critical(f"Starting value: ${self.starting_account_value:.2f}")
            logger.critical(f"Current value: ${current_account_value:.2f}")
            logger.critical(f"Daily P&L: ${self.daily_pnl:.2f} (limit: -${Config.MAX_DAILY_LOSS:.2f})")
            return True
        return False
    
    def check_filled_orders(self):
        """Check for filled orders and send notifications"""
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
                        from datetime import datetime, timezone
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
                    # Send notification
                    self._send_notification(
                        f"✅ Trade Filled: {action} {side}",
                        f"{fill_count} contract(s) @ {fill_price}¢\nMarket: {ticker}"
                    )
                    logger.info(f"📬 Notification sent: {action} {fill_count} {side} @ {fill_price}¢ filled for {ticker}")
        
        except Exception as e:
            logger.error(f"Error checking filled orders: {e}", exc_info=True)
    
    def check_and_cancel_stale_orders(self):
        """Check resting orders and cancel if edge/EV no longer meets strategy thresholds"""
        try:
            try:
                resting_orders = self.client.get_orders(status='resting')
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
                
                # Get current market data
                try:
                    # Get market info
                    markets = self.client.get_markets(limit=200)
                    market = next((m for m in markets if m.get('ticker') == ticker), None)
                    
                    if not market:
                        # Market might have closed, cancel order
                        logger.info(f"🗑️  Canceling order {order_id}: Market {ticker} not found (likely closed)")
                        self.client.cancel_order(order_id)
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
                            logger.info(f"✅ Order {order_id} canceled successfully")
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
            logger.warning("Pausing trading due to daily loss limit")
            return
        
        logger.debug(f"Scanning markets at {datetime.now()}")
        
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
            
            markets_evaluated = 0
            for i, market in enumerate(markets_to_process):
                # Small delay every 10 markets to avoid overwhelming the API
                if i > 0 and i % 10 == 0:
                    time.sleep(0.5)  # 500ms pause every 10 markets
                
                # Quick filter check before expensive orderbook call
                should_trade = any(strategy.should_trade(market) for strategy in self.strategy_manager.strategies)
                if not should_trade:
                    # Debug: log why market was skipped
                    series = market.get('series_ticker', 'unknown')
                    status = market.get('status', 'unknown')
                    volume = market.get('volume', 0)
                    if series not in Config.WEATHER_SERIES:
                        continue  # Not a weather market, skip silently
                    if status != 'open':
                        continue  # Not open, skip silently
                    if volume < Config.MIN_MARKET_VOLUME:
                        logger.debug(f"Market {market.get('ticker', 'unknown')} skipped: volume {volume} < {Config.MIN_MARKET_VOLUME}")
                    continue
                
                markets_evaluated += 1
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
                        
                        # Log trade summary
                        logger.info(f"Trade executed successfully - Market: {market_ticker}")
                        logger.debug(f"Active positions being tracked: {len(self.markets_being_tracked)}")
                        
                        time.sleep(0.3)  # Reduced rate limiting delay
        except Exception as e:
            logger.error(f"Error in scan_and_trade: {e}", exc_info=True)
    
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
                logger.info(f"Scan interval: 30 seconds (Kalshi odds check) | Weather forecast cache: {Config.FORECAST_CACHE_TTL/60} minutes")
            else:
                logger.info("Scan interval: 15 seconds")
            # Heartbeat interval (log every 30 minutes for weather markets)
            heartbeat_interval = 1800
            last_heartbeat = time.time()
            
            while self.running:
                try:
                    scan_start = time.time()
                    self.scan_and_trade()
                    scan_duration = time.time() - scan_start
                    
                    # Log scan completion
                    logger.info(f"✅ Scan complete in {scan_duration:.1f}s. Next scan in {max(0, 30 - scan_duration):.0f}s")
                    
                    # Check for filled orders and send notifications
                    self.check_filled_orders()
                    
                    # Check and cancel stale orders (edge/EV no longer valid)
                    self.check_and_cancel_stale_orders()
                    
                    # Check for settled positions and update forecast model (every hour)
                    outcome_check_interval = 3600  # 1 hour
                    if self.outcome_tracker and time.time() - self.last_outcome_check >= outcome_check_interval:
                        try:
                            self.outcome_tracker.run_outcome_check()
                            self.last_outcome_check = time.time()
                        except Exception as e:
                            logger.error(f"Error checking outcomes: {e}", exc_info=True)
                    
                    # Heartbeat logging to confirm bot is alive
                    if time.time() - last_heartbeat >= heartbeat_interval:
                        portfolio = self.client.get_portfolio()
                        balance = portfolio.get('balance', 0) / 100  # Convert cents to dollars
                        portfolio_value = portfolio.get('portfolio_value', 0) / 100  # Convert cents to dollars
                        total_value = balance + portfolio_value
                        
                        # Update daily P&L for heartbeat
                        if self.starting_account_value is not None:
                            self.daily_pnl = total_value - self.starting_account_value
                        
                        logger.info(f"❤️  Heartbeat: Running for {(time.time() - last_heartbeat)/3600:.1f}h")
                        logger.info(f"   Cash: ${balance:.2f}, Portfolio: ${portfolio_value:.2f}, Total: ${total_value:.2f}")
                        logger.info(f"   Daily P&L: ${self.daily_pnl:.2f} (limit: -${Config.MAX_DAILY_LOSS:.2f})")
                        last_heartbeat = time.time()
                    
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
