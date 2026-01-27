import asyncio
import json
import time
from datetime import datetime
from typing import Dict, List, Set
from kalshi_client import KalshiClient
from strategies import StrategyManager
from config import Config
from btc_data import BTCPriceTracker


class KalshiTradingBot:
    """Main trading bot orchestrator"""
    
    def __init__(self):
        Config.validate()
        self.client = KalshiClient()
        
        # Create shared BTC tracker (update once per scan, not per market)
        self.btc_tracker = None
        if 'btc_hourly' in Config.ENABLED_STRATEGIES or 'btc_15m' in Config.ENABLED_STRATEGIES:  # Support both for backward compat
            self.btc_tracker = BTCPriceTracker()
            self.btc_tracker.update()
        
        self.strategy_manager = StrategyManager(self.client, btc_tracker=self.btc_tracker)
        self.running = False
        self.markets_being_tracked = set()
        self.daily_pnl = 0
        self.last_reset_date = datetime.now().date()
        
        # Track relevant series for filtering
        self.relevant_series: Set[str] = set()
        if 'btc_hourly' in Config.ENABLED_STRATEGIES or 'btc_15m' in Config.ENABLED_STRATEGIES:  # Support both for backward compat
            self.relevant_series.add(Config.BTC_HOURLY_SERIES)
        if 'weather_daily' in Config.ENABLED_STRATEGIES:
            self.relevant_series.update(Config.WEATHER_SERIES)
    
    def reset_daily_stats(self):
        """Reset daily statistics"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.daily_pnl = 0
            self.last_reset_date = today
            print(f"[Bot] Daily stats reset for {today}")
    
    def check_daily_loss_limit(self):
        """Check if we've hit daily loss limit"""
        self.reset_daily_stats()
        if self.daily_pnl <= -Config.MAX_DAILY_LOSS:
            print(f"[Bot] Daily loss limit reached: ${self.daily_pnl}")
            return True
        return False
    
    def scan_and_trade(self):
        """Scan markets and execute trades"""
        if self.check_daily_loss_limit():
            print("[Bot] Pausing trading due to daily loss limit")
            return
        
        print(f"[Bot] Scanning markets at {datetime.now()}")
        
        # Update BTC data once per scan (not per market) for performance
        if self.btc_tracker and not self.btc_tracker.is_fresh(max_age_seconds=30):
            self.btc_tracker.update()
        
        try:
            # Filter markets by relevant series FIRST to reduce API calls
            relevant_markets = []
            for series_ticker in self.relevant_series:
                series_markets = self.client.get_markets(series_ticker=series_ticker, status='open', limit=50)
                relevant_markets.extend(series_markets)
            
            print(f"[Bot] Found {len(relevant_markets)} relevant markets (filtered from series)")
            
            for market in relevant_markets:
                # Quick filter check before expensive orderbook call
                if not any(strategy.should_trade(market) for strategy in self.strategy_manager.strategies):
                    continue
                
                # Evaluate market with all strategies
                decisions = self.strategy_manager.evaluate_market(market)
                
                for decision in decisions:
                    strategy_name = decision.pop('strategy')
                    market_ticker = decision.pop('market_ticker')
                    
                    # Execute trade
                    strategy = next(s for s in self.strategy_manager.strategies if s.name == strategy_name)
                    order = strategy.execute_trade(decision, market_ticker)
                    
                    if order:
                        self.markets_being_tracked.add(market_ticker)
                        
                        # Log trade summary
                        print(f"[Bot] Trade executed successfully - Market: {market_ticker}")
                        print(f"[Bot] Active positions being tracked: {len(self.markets_being_tracked)}")
                        
                        time.sleep(0.3)  # Reduced rate limiting delay
        except Exception as e:
            print(f"[Bot] Error in scan_and_trade: {e}")
    
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
                print(f"[Bot] WebSocket error: {e}, reconnecting in 5 seconds...")
                await asyncio.sleep(5)
    
    def run(self, use_websocket: bool = False):
        """Run the trading bot"""
        self.running = True
        print("[Bot] Starting Kalshi Trading Bot...")
        print(f"[Bot] Enabled strategies: {', '.join(Config.ENABLED_STRATEGIES)}")
        
        # Get initial portfolio balance
        try:
            portfolio = self.client.get_portfolio()
            print(f"[Bot] Portfolio balance: ${portfolio.get('balance', 0) / 100}")
        except Exception as e:
            print(f"[Bot] Could not fetch portfolio: {e}")
        
        if use_websocket:
            # Run with WebSocket for real-time updates
            print("[Bot] Starting WebSocket connection...")
            asyncio.run(self.run_websocket())
        else:
            # Run polling mode
            print("[Bot] Running in polling mode...")
            if 'btc_hourly' in Config.ENABLED_STRATEGIES or 'btc_15m' in Config.ENABLED_STRATEGIES:
                print("[Bot] Scan interval: 10 seconds (optimized for hourly BTC markets)")
            else:
                print("[Bot] Scan interval: 15 seconds")
            while self.running:
                try:
                    scan_start = time.time()
                    self.scan_and_trade()
                    scan_duration = time.time() - scan_start
                    
                    # Adaptive sleep: 10 seconds for BTC hourly (less frequent than 15-min), 15 for weather
                    if 'btc_hourly' in Config.ENABLED_STRATEGIES or 'btc_15m' in Config.ENABLED_STRATEGIES:
                        sleep_time = max(0, 10 - scan_duration)  # 10 second interval for BTC hourly
                    else:
                        sleep_time = max(0, 15 - scan_duration)  # 15 second for weather
                    
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                except KeyboardInterrupt:
                    print("\n[Bot] Shutting down...")
                    self.running = False
                except Exception as e:
                    print(f"[Bot] Error in main loop: {e}")
                    time.sleep(5)
    
    def stop(self):
        """Stop the bot"""
        self.running = False
        print("[Bot] Bot stopped")


if __name__ == '__main__':
    bot = KalshiTradingBot()
    
    # Run in polling mode (set use_websocket=True for WebSocket mode)
    bot.run(use_websocket=False)
