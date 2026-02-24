"""
WebSocket Price Cache — Feed live Kalshi prices into an in-memory cache.

Runs alongside the polling scan loop (not replacing it). The scan loop
reads cached prices for faster orderbook access, falling back to REST
when the cache is stale or WebSocket is disconnected.

Thread-safe: the WS connection runs on a daemon thread, the scan loop
reads from the cache on the main thread.
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Optional

from .config import Config

logger = logging.getLogger(__name__)


class WsPriceCache:
    """Thread-safe in-memory cache of live Kalshi prices from WebSocket."""

    def __init__(self):
        self._lock = threading.Lock()
        # {ticker: {yes_bid, yes_ask, no_bid, no_ask, updated_at}}
        self._prices: Dict[str, dict] = {}
        self._connected = False
        self._last_message_time = 0.0
        self._message_count = 0

    def update_ticker(self, ticker: str, yes_bid: int, yes_ask: int):
        """Update cached price for a ticker (called from WS thread)."""
        with self._lock:
            self._prices[ticker] = {
                'yes_bid': yes_bid,
                'yes_ask': yes_ask,
                'no_bid': 100 - yes_ask if yes_ask else 0,
                'no_ask': 100 - yes_bid if yes_bid else 0,
                'updated_at': time.time(),
            }
            self._last_message_time = time.time()
            self._message_count += 1

    def get_price(self, ticker: str, max_age_seconds: int = None) -> Optional[dict]:
        """Get cached price for a ticker.

        Args:
            ticker: Market ticker
            max_age_seconds: Max cache age (default from config)

        Returns:
            Price dict or None if stale/missing
        """
        if max_age_seconds is None:
            max_age_seconds = Config.WEBSOCKET_CACHE_MAX_AGE
        with self._lock:
            entry = self._prices.get(ticker)
            if entry is None:
                return None
            age = time.time() - entry['updated_at']
            if age > max_age_seconds:
                return None
            return entry.copy()

    def set_connected(self, connected: bool):
        """Update connection status."""
        self._connected = connected

    def get_status(self) -> dict:
        """Return cache status for dashboard/logging."""
        with self._lock:
            cached_count = len(self._prices)
            last_age = time.time() - self._last_message_time if self._last_message_time > 0 else None
        return {
            'enabled': Config.WEBSOCKET_CACHE_ENABLED,
            'connected': self._connected,
            'cached_tickers': cached_count,
            'last_message_age': round(last_age, 1) if last_age is not None else None,
            'total_messages': self._message_count,
        }


def run_ws_cache(ws_cache: WsPriceCache, client):
    """Run WebSocket connection feeding prices into cache.

    This function runs in a daemon thread. It connects to the Kalshi WS,
    subscribes to ticker updates, and feeds prices into ws_cache.

    Args:
        ws_cache: WsPriceCache instance to feed prices into
        client: KalshiClient instance for WS connection
    """
    import asyncio

    async def _ws_loop():
        while True:
            try:
                import websockets
                from .kalshi_client import KalshiClient

                ws_url = Config.WS_URL
                logger.info(f"WebSocket price cache connecting to {ws_url}")

                # Get auth headers from client
                headers = {}
                if hasattr(client, '_get_auth_headers'):
                    headers = client._get_auth_headers()
                elif hasattr(client, 'get_auth_headers'):
                    headers = client.get_auth_headers()

                async with websockets.connect(ws_url, extra_headers=headers) as ws:
                    ws_cache.set_connected(True)
                    logger.info("WebSocket connected for price cache")

                    # Subscribe to ticker channel
                    subscribe_msg = {
                        'id': 1,
                        'cmd': 'subscribe',
                        'params': {
                            'channels': ['ticker'],
                        }
                    }
                    await ws.send(json.dumps(subscribe_msg))

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            msg_type = data.get('type', '')

                            if msg_type == 'ticker':
                                ticker_data = data.get('msg', data.get('data', {}))
                                ticker = ticker_data.get('market_ticker', '')
                                yes_bid = ticker_data.get('yes_bid', 0)
                                yes_ask = ticker_data.get('yes_ask', 0)
                                if ticker:
                                    ws_cache.update_ticker(ticker, yes_bid, yes_ask)

                            elif msg_type == 'orderbook_snapshot' or msg_type == 'orderbook_delta':
                                # Could also extract best bid/ask from orderbook updates
                                pass

                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            logger.debug(f"WS message processing error: {e}")

            except Exception as e:
                ws_cache.set_connected(False)
                logger.warning(f"WebSocket price cache error: {e}, reconnecting in 5s")
                await asyncio.sleep(5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_ws_loop())
    except Exception as e:
        logger.error(f"WebSocket price cache thread crashed: {e}")
    finally:
        ws_cache.set_connected(False)
