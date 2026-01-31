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
    # Skip placing an order if computed size would be below this (avoids many 1-contract orders).
    MIN_ORDER_CONTRACTS = int(os.getenv('MIN_ORDER_CONTRACTS', '1'))  # 1 = allow 1-contract orders; 2+ = require at least that many
    ENABLED_STRATEGIES = os.getenv('ENABLED_STRATEGIES', 'weather_daily').split(',')
    
    # Weather Strategy Parameters
    # Conservative strategy
    MIN_EDGE_THRESHOLD = float(os.getenv('MIN_EDGE_THRESHOLD', '5.0'))  # Minimum edge % to trade
    MIN_EV_THRESHOLD = float(os.getenv('MIN_EV_THRESHOLD', '0.01'))  # Minimum EV in dollars
    # If True, only trade when confidence interval does NOT overlap market price (stricter).
    # If False (default), trade when edge/EV meet thresholds even if CI overlaps (more trades, higher risk).
    REQUIRE_HIGH_CONFIDENCE = os.getenv('REQUIRE_HIGH_CONFIDENCE', 'false').lower() == 'true'
    
    # Longshot strategy
    LONGSHOT_ENABLED = os.getenv('LONGSHOT_ENABLED', 'true').lower() == 'true'
    LONGSHOT_MAX_PRICE = int(os.getenv('LONGSHOT_MAX_PRICE', '10'))  # Only consider if market price ≤ 10¢
    LONGSHOT_MIN_EDGE = float(os.getenv('LONGSHOT_MIN_EDGE', '30.0'))  # Require massive edge (30%+)
    LONGSHOT_MIN_PROB = float(os.getenv('LONGSHOT_MIN_PROB', '50.0'))  # Our probability must be ≥ 50%
    LONGSHOT_POSITION_MULTIPLIER = int(os.getenv('LONGSHOT_POSITION_MULTIPLIER', '3'))  # Trade 3x normal size
    
    # Market filtering
    MIN_MARKET_VOLUME = int(os.getenv('MIN_MARKET_VOLUME', '15'))  # Minimum volume for liquidity
    MAX_MARKET_DATE_DAYS = int(os.getenv('MAX_MARKET_DATE_DAYS', '3'))  # Max days in future for forecasts
    # Never buy at or above this price (cents). 99 = no buys at 99¢ or 100¢ (no edge).
    MAX_BUY_PRICE_CENTS = int(os.getenv('MAX_BUY_PRICE_CENTS', '99'))
    # Skip single-threshold markets when mean forecast is within this many degrees of the threshold
    # (reduces "coin flip" losses when actual lands right on the boundary). 0 = disabled.
    MIN_DEGREES_FROM_THRESHOLD = float(os.getenv('MIN_DEGREES_FROM_THRESHOLD', '0'))
    
    # Caching
    ORDERBOOK_CACHE_TTL = int(os.getenv('ORDERBOOK_CACHE_TTL', '3'))  # 3 seconds
    PORTFOLIO_CACHE_TTL = int(os.getenv('PORTFOLIO_CACHE_TTL', '10'))  # 10 seconds
    FORECAST_CACHE_TTL = int(os.getenv('FORECAST_CACHE_TTL', '1800'))  # 30 minutes
    ENSEMBLE_CACHE_TTL = int(os.getenv('ENSEMBLE_CACHE_TTL', '3600'))  # 1 hour for ensemble data

    # Weather Data Source Configuration
    # Enable/disable specific data sources (all enabled by default)
    ENABLE_OPEN_METEO = os.getenv('ENABLE_OPEN_METEO', 'true').lower() == 'true'
    ENABLE_PIRATE_WEATHER = os.getenv('ENABLE_PIRATE_WEATHER', 'true').lower() == 'true'
    ENABLE_VISUAL_CROSSING = os.getenv('ENABLE_VISUAL_CROSSING', 'true').lower() == 'true'
    ENABLE_ENSEMBLE_DATA = os.getenv('ENABLE_ENSEMBLE_DATA', 'true').lower() == 'true'

    # Minimum number of ensemble members required to use ensemble uncertainty
    MIN_ENSEMBLE_MEMBERS = int(os.getenv('MIN_ENSEMBLE_MEMBERS', '10'))

    # Bias correction settings
    ENABLE_BIAS_CORRECTION = os.getenv('ENABLE_BIAS_CORRECTION', 'true').lower() == 'true'
    MIN_SAMPLES_FOR_BIAS = int(os.getenv('MIN_SAMPLES_FOR_BIAS', '5'))  # Min samples before applying bias correction
    
    # Market Tickers
    # High and Low temperature markets for NYC, Chicago, Miami, Austin, Los Angeles, Denver
    WEATHER_SERIES = [
        'KXHIGHNY', 'KXLOWNY',      # New York City
        'KXHIGHCHI', 'KXLOWCHI',    # Chicago (corrected from KXHIGHCH)
        'KXHIGHMIA', 'KXLOWMIA',    # Miami (corrected from KXHIGHMI)
        'KXHIGHAUS', 'KXLOWAUS',    # Austin
        'KXHIGHLAX', 'KXLOWLAX',    # Los Angeles
        'KXHIGHDEN', 'KXLOWDEN'     # Denver
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
