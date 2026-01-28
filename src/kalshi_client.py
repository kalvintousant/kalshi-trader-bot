import base64
import json
import time
import asyncio
import requests
import websockets
import logging
from datetime import datetime
from typing import Dict, List, Optional
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from .config import Config

logger = logging.getLogger(__name__)


class KalshiClient:
    """Client for interacting with Kalshi API"""
    
    def __init__(self):
        self.api_key_id = Config.API_KEY_ID
        self.base_url = Config.BASE_URL
        self.ws_url = Config.WS_URL
        self._private_key = None
        self._load_private_key()
        
        # Use session for connection pooling and better performance
        self.session = requests.Session()
        
        # Cache for orderbooks (from Config)
        self.orderbook_cache = {}
        self.orderbook_cache_timestamp = {}
        self.orderbook_cache_ttl = Config.ORDERBOOK_CACHE_TTL
        
        # Cache for portfolio (from Config)
        self.portfolio_cache = None
        self.portfolio_cache_timestamp = 0
        self.portfolio_cache_ttl = Config.PORTFOLIO_CACHE_TTL
    
    def _load_private_key(self):
        """Load the private key from file"""
        with open(Config.PRIVATE_KEY_PATH, 'rb') as f:
            self._private_key = serialization.load_pem_private_key(
                f.read(),
                password=None
            )
    
    def _sign_pss_text(self, text: str) -> str:
        """Sign message using RSA-PSS"""
        message = text.encode('utf-8')
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    
    def _create_headers(self, method: str, path: str) -> Dict[str, str]:
        """Create authentication headers"""
        timestamp = str(int(time.time() * 1000))
        # Remove query string from path for signing
        path_for_signing = path.split('?')[0]
        # Kalshi requires the full path including /trade-api/v2 for signing
        if not path_for_signing.startswith('/trade-api/v2'):
            path_for_signing = '/trade-api/v2' + path_for_signing
        msg_string = timestamp + method + path_for_signing
        signature = self._sign_pss_text(msg_string)
        
        return {
            'KALSHI-ACCESS-KEY': self.api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json'
        }
    
    def _get(self, path: str, params: Optional[Dict] = None, use_cache: bool = False) -> Dict:
        """Make authenticated GET request with optional caching"""
        # Check cache for orderbook requests
        if use_cache and path.startswith('/markets/') and path.endswith('/orderbook'):
            market_ticker = path.split('/')[-2]
            cache_key = market_ticker
            if cache_key in self.orderbook_cache:
                cache_time = self.orderbook_cache_timestamp.get(cache_key)
                if cache_time and (time.time() - cache_time) < self.orderbook_cache_ttl:
                    return self.orderbook_cache[cache_key]
        
        url = f"{self.base_url}{path}"
        headers = self._create_headers('GET', path)
        
        # Retry logic with exponential backoff
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                result = response.json()
                
                # Cache orderbook results
                if use_cache and path.startswith('/markets/') and path.endswith('/orderbook'):
                    market_ticker = path.split('/')[-2]
                    self.orderbook_cache[market_ticker] = result
                    self.orderbook_cache_timestamp[market_ticker] = time.time()
                
                return result
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    time.sleep(wait_time)
                    continue
                raise
    
    def _post(self, path: str, data: Dict) -> Dict:
        """Make authenticated POST request"""
        url = f"{self.base_url}{path}"
        headers = self._create_headers('POST', path)
        
        # Retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, headers=headers, json=data, timeout=10)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                # Handle rate limiting (429) and other retryable errors
                if attempt < max_retries - 1:
                    if hasattr(e.response, 'status_code') and e.response.status_code == 429:
                        # Rate limited - use longer backoff
                        wait_time = min(60, 2 ** (attempt + 2))  # 4s, 8s, 16s (capped at 60s)
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    else:
                        wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                raise
    
    def _put(self, path: str, data: Dict) -> Dict:
        """Make authenticated PUT request"""
        url = f"{self.base_url}{path}"
        headers = self._create_headers('PUT', path)
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.put(url, headers=headers, json=data, timeout=10)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                # Handle rate limiting (429) and other retryable errors
                if attempt < max_retries - 1:
                    if hasattr(e.response, 'status_code') and e.response.status_code == 429:
                        # Rate limited - use longer backoff
                        wait_time = min(60, 2 ** (attempt + 2))  # 4s, 8s, 16s (capped at 60s)
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    else:
                        wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                raise
    
    def _delete(self, path: str) -> Dict:
        """Make authenticated DELETE request"""
        url = f"{self.base_url}{path}"
        headers = self._create_headers('DELETE', path)
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.delete(url, headers=headers, timeout=10)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                # Handle rate limiting (429) and other retryable errors
                if attempt < max_retries - 1:
                    if hasattr(e.response, 'status_code') and e.response.status_code == 429:
                        # Rate limited - use longer backoff
                        wait_time = min(60, 2 ** (attempt + 2))  # 4s, 8s, 16s (capped at 60s)
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    else:
                        wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                raise
    
    # Market Data Methods
    def get_series(self, series_ticker: str) -> Dict:
        """Get series information"""
        return self._get(f"/series/{series_ticker}")
    
    def get_markets(self, series_ticker: Optional[str] = None, 
                    status: str = 'open', limit: int = 100) -> List[Dict]:
        """Get markets, optionally filtered by series"""
        params = {'status': status, 'limit': limit}
        if series_ticker:
            params['series_ticker'] = series_ticker
        
        response = self._get('/markets', params=params)
        return response.get('markets', [])
    
    def get_market_orderbook(self, market_ticker: str, use_cache: bool = True) -> Dict:
        """Get orderbook for a specific market with caching"""
        return self._get(f"/markets/{market_ticker}/orderbook", use_cache=use_cache)
    
    def get_portfolio(self, use_cache: bool = True) -> Dict:
        """Get portfolio information with caching"""
        # Check cache first
        if use_cache:
            cache_age = time.time() - self.portfolio_cache_timestamp
            if self.portfolio_cache and cache_age < self.portfolio_cache_ttl:
                return self.portfolio_cache
        
        # Fetch fresh portfolio data
        portfolio = self._get('/portfolio/balance')
        
        # Update cache
        if use_cache:
            self.portfolio_cache = portfolio
            self.portfolio_cache_timestamp = time.time()
        
        return portfolio
    
    def get_orders(self, status: Optional[str] = None) -> List[Dict]:
        """Get orders, optionally filtered by status"""
        params = {}
        if status:
            params['status'] = status
        response = self._get('/portfolio/orders', params=params)
        return response.get('orders', [])
    
    # Trading Methods
    def create_order(self, ticker: str, action: str, side: str, 
                    count: int, order_type: str, yes_price: Optional[int] = None,
                    no_price: Optional[int] = None, 
                    client_order_id: Optional[str] = None) -> Dict:
        """Create an order"""
        order_data = {
            'ticker': ticker,
            'action': action,  # 'buy' or 'sell'
            'side': side,  # 'yes' or 'no'
            'count': count,
            'type': order_type  # 'limit' or 'market'
        }
        
        if yes_price is not None:
            order_data['yes_price'] = yes_price
        if no_price is not None:
            order_data['no_price'] = no_price
        if client_order_id:
            order_data['client_order_id'] = client_order_id
        
        response = self._post('/portfolio/orders', order_data)
        return response.get('order', {})
    
    def cancel_order(self, order_id: str) -> Dict:
        """Cancel an order"""
        return self._delete(f"/portfolio/orders/{order_id}")
    
    def amend_order(self, order_id: str, yes_price: Optional[int] = None,
                   no_price: Optional[int] = None, count: Optional[int] = None) -> Dict:
        """Amend an existing order"""
        data = {}
        if yes_price is not None:
            data['yes_price'] = yes_price
        if no_price is not None:
            data['no_price'] = no_price
        if count is not None:
            data['count'] = count
        
        return self._put(f"/portfolio/orders/{order_id}", data)
    
    # WebSocket Methods
    async def connect_websocket(self, message_handler):
        """Connect to WebSocket and handle messages"""
        ws_headers = self._create_headers('GET', '/trade-api/ws/v2')
        
        async with websockets.connect(self.ws_url, additional_headers=ws_headers) as websocket:
            print("Connected to Kalshi WebSocket")
            await message_handler(websocket)
    
    async def subscribe_to_orderbook(self, websocket, market_tickers: List[str]):
        """Subscribe to orderbook updates for specific markets"""
        subscription = {
            'id': int(time.time() * 1000),
            'cmd': 'subscribe',
            'params': {
                'channels': ['orderbook_delta'],
                'market_tickers': market_tickers
            }
        }
        await websocket.send(json.dumps(subscription))
    
    async def subscribe_to_ticker(self, websocket):
        """Subscribe to ticker updates for all markets"""
        subscription = {
            'id': int(time.time() * 1000),
            'cmd': 'subscribe',
            'params': {
                'channels': ['ticker']
            }
        }
        await websocket.send(json.dumps(subscription))
