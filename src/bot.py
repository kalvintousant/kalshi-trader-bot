import asyncio
import json
import time
import requests
from datetime import datetime
from typing import Dict, List, Set
from src.kalshi_client import KalshiClient
from src.strategies import StrategyManager
from src.config import Config


class KalshiTradingBot:
    """Main trading bot orchestrator"""
    
    def __init__(self):
        Config.validate()
        self.client = KalshiClient()
        
        # Weather markets only - no BTC tracker needed
        self.strategy_manager = StrategyManager(self.client)
        self.running = False
        self.markets_being_tracked = set()
        self.daily_pnl = 0
        self.last_reset_date = datetime.now().date()
        
        # Track seen markets to detect new ones quickly
        self.seen_markets: Set[str] = set()
        
        # Track relevant series for filtering
        self.relevant_series: Set[str] = set()
        if 'btc_15m' in Config.ENABLED_STRATEGIES:
            self.relevant_series.add(Config.BTC_15M_SERIES)
        if 'btc_hourly' in Config.ENABLED_STRATEGIES:
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
        
        # Weather markets only - no BTC data needed
        
        try:
            # Filter markets by relevant series FIRST to reduce API calls
            # Increase limit to catch all markets, especially new ones
            relevant_markets = []
            for series_ticker in self.relevant_series:
                series_markets = self.client.get_markets(series_ticker=series_ticker, status='open', limit=200)
                relevant_markets.extend(series_markets)
            
            # Detect new markets (prioritize them for early entry)
            new_markets = []
            existing_markets = []
            for market in relevant_markets:
                market_ticker = market.get('ticker', '')
                if market_ticker not in self.seen_markets:
                    new_markets.append(market)
                    self.seen_markets.add(market_ticker)
                else:
                    existing_markets.append(market)
            
            # Process new markets FIRST (critical for early entry)
            if new_markets:
                print(f"[Bot] 🆕 Found {len(new_markets)} NEW markets! Processing immediately...")
            
            # Combine: new markets first, then existing
            markets_to_process = new_markets + existing_markets
            print(f"[Bot] Found {len(markets_to_process)} relevant markets ({len(new_markets)} new, {len(existing_markets)} existing)")
            
            for market in markets_to_process:
                # Quick filter check before expensive orderbook call
                if not any(strategy.should_trade(market) for strategy in self.strategy_manager.strategies):
                    continue
                
                # Evaluate market with all strategies
                try:
                    decisions = self.strategy_manager.evaluate_market(market)
                except Exception as e:
                    print(f"[Bot] ⚠️  Error evaluating market {market.get('ticker', 'unknown')}: {e}")
                    import traceback
                    traceback.print_exc()
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
            if 'btc_15m' in Config.ENABLED_STRATEGIES:
                print("[Bot] Scan interval: 0.5 seconds (ultra-fast for new market detection and latency arbitrage)")
            elif 'btc_hourly' in Config.ENABLED_STRATEGIES:
                print("[Bot] Scan interval: 10 seconds (optimized for hourly BTC markets)")
            elif 'weather_daily' in Config.ENABLED_STRATEGIES:
                print("[Bot] Scan interval: 30 minutes (optimized for daily weather markets - matches forecast cache)")
            else:
                print("[Bot] Scan interval: 15 seconds")
            # Heartbeat interval (log every 30 minutes for weather, every hour for BTC)
            heartbeat_interval = 1800 if 'weather_daily' in Config.ENABLED_STRATEGIES else 3600
            last_heartbeat = time.time()
            
            while self.running:
                try:
                    scan_start = time.time()
                    self.scan_and_trade()
                    scan_duration = time.time() - scan_start
                    
                    # Heartbeat logging to confirm bot is alive
                    if time.time() - last_heartbeat >= heartbeat_interval:
                        portfolio = self.client.get_portfolio()
                        balance = portfolio.get('balance', 0) / 100  # Convert cents to dollars
                        print(f"[Bot] ❤️  Heartbeat: Running for {(time.time() - last_heartbeat)/3600:.1f}h, Balance: ${balance:.2f}, Daily P&L: ${self.daily_pnl:.2f}")
                        last_heartbeat = time.time()
                    
                    # Adaptive scan intervals based on market type
                    # BTC 15-min: 0.5s (ultra-fast for new market detection)
                    # BTC hourly: 10s (moderate speed)
                    # Weather daily: 30 min (matches forecast cache, appropriate for daily settlements)
                    if 'btc_15m' in Config.ENABLED_STRATEGIES:
                        sleep_time = max(0, 0.5 - scan_duration)  # 0.5 second interval
                    elif 'btc_hourly' in Config.ENABLED_STRATEGIES:
                        sleep_time = max(0, 10 - scan_duration)  # 10 second interval
                    elif 'weather_daily' in Config.ENABLED_STRATEGIES:
                        sleep_time = max(0, 1800 - scan_duration)  # 30 minutes (1800 seconds) for daily weather markets
                    else:
                        sleep_time = max(0, 15 - scan_duration)  # 15 second default
                    
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                        
                except KeyboardInterrupt:
                    print("\n[Bot] Shutting down...")
                    self.running = False
                except ConnectionError as e:
                    print(f"[Bot] ⚠️  Connection error: {e}. Retrying in 30 seconds...")
                    time.sleep(30)
                except requests.exceptions.RequestException as e:
                    print(f"[Bot] ⚠️  Network error: {e}. Retrying in 30 seconds...")
                    time.sleep(30)
                except Exception as e:
                    print(f"[Bot] ⚠️  Unexpected error in main loop: {e}")
                    import traceback
                    traceback.print_exc()
                    print("[Bot] Continuing in 60 seconds...")
                    time.sleep(60)
    
    def stop(self):
        """Stop the bot"""
        self.running = False
        print("[Bot] Bot stopped")


if __name__ == '__main__':
    bot = KalshiTradingBot()
    
    # Run in polling mode (set use_websocket=True for WebSocket mode)
    bot.run(use_websocket=False)
