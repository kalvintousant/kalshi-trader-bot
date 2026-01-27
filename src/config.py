import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # API Credentials
    API_KEY_ID = os.getenv('KALSHI_API_KEY_ID')
    PRIVATE_KEY_PATH = os.getenv('KALSHI_PRIVATE_KEY_PATH')
    BASE_URL = os.getenv('KALSHI_BASE_URL', 'https://api.elections.kalshi.com/trade-api/v2')
    WS_URL = os.getenv('KALSHI_WS_URL', 'wss://api.elections.kalshi.com/trade-api/ws/v2')
    
    # Trading Settings
    MAX_POSITION_SIZE = int(os.getenv('MAX_POSITION_SIZE', '10'))
    MAX_DAILY_LOSS = int(os.getenv('MAX_DAILY_LOSS', '10'))  # $10 max daily loss limit
    MAX_CONTRACTS_PER_MARKET = int(os.getenv('MAX_CONTRACTS_PER_MARKET', '25'))  # Max contracts per market
    MAX_DOLLARS_PER_MARKET = float(os.getenv('MAX_DOLLARS_PER_MARKET', '3.0'))  # Max dollars per market ($3.00)
    ENABLED_STRATEGIES = os.getenv('ENABLED_STRATEGIES', 'btc_15m,weather_daily').split(',')
    
    # Market Tickers
    BTC_15M_SERIES = 'KXBTC15M'  # 15-minute BTC markets (up/down)
    BTC_HOURLY_SERIES = 'KXBTC'  # Hourly BTC markets (price ranges)
    # High and Low temperature markets for NYC, Chicago, Miami, Austin, Los Angeles
    WEATHER_SERIES = [
        'KXHIGHNY', 'KXLOWNY',   # New York City
        'KXHIGHCH', 'KXLOWCH',   # Chicago
        'KXHIGHMI', 'KXLOWMI',   # Miami
        'KXHIGHAUS', 'KXLOWAUS',   # Austin
        'KXHIGHLAX', 'KXLOWLAX'  # Los Angeles
    ]
    
    @classmethod
    def validate(cls):
        """Validate that required configuration is present"""
        if not cls.API_KEY_ID:
            raise ValueError("KALSHI_API_KEY_ID not set in environment")
        if not cls.PRIVATE_KEY_PATH:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH not set in environment")
        if not os.path.exists(cls.PRIVATE_KEY_PATH):
            raise FileNotFoundError(f"Private key file not found: {cls.PRIVATE_KEY_PATH}")
