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
    MAX_CONTRACTS_PER_MARKET = int(os.getenv('MAX_CONTRACTS_PER_MARKET', '10'))  # Max contracts per base market
    MAX_DOLLARS_PER_MARKET = float(os.getenv('MAX_DOLLARS_PER_MARKET', '5.0'))  # Max dollars per base market
    # Skip placing an order if computed size would be below this (avoids many 1-contract orders).
    MIN_ORDER_CONTRACTS = int(os.getenv('MIN_ORDER_CONTRACTS', '1'))  # 1 = allow 1-contract orders; 2+ = require at least that many
    ENABLED_STRATEGIES = os.getenv('ENABLED_STRATEGIES', 'weather_daily').split(',')
    
    # Weather Strategy Parameters
    # Conservative strategy
    MIN_EDGE_THRESHOLD = float(os.getenv('MIN_EDGE_THRESHOLD', '8.0'))  # Minimum edge % to trade (raised from 5% to filter marginal trades)
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
    # Local hour (24h) after which we skip today's LOW markets (low of day usually 4–7 AM). 8 = 8 AM; set 9 or 10 to extend window.
    LONGSHOT_LOW_CUTOFF_HOUR = int(os.getenv('LONGSHOT_LOW_CUTOFF_HOUR', '8'))
    
    # Market filtering
    MIN_MARKET_VOLUME = int(os.getenv('MIN_MARKET_VOLUME', '15'))  # Minimum volume for liquidity
    MAX_MARKET_DATE_DAYS = int(os.getenv('MAX_MARKET_DATE_DAYS', '3'))  # Max days in future for forecasts
    # Never buy at or above this price (cents). Data shows 51-75¢ entries lose money (42% win rate).
    MAX_BUY_PRICE_CENTS = int(os.getenv('MAX_BUY_PRICE_CENTS', '50'))  # Cap at 50¢ - profitable win rates at 1-50¢ entries
    # Skip single-threshold markets when mean forecast is within this many degrees of the threshold
    # (reduces "coin flip" losses when actual lands right on the boundary). 0 = disabled.
    MIN_DEGREES_FROM_THRESHOLD = float(os.getenv('MIN_DEGREES_FROM_THRESHOLD', '2.0'))  # Skip trades within 2°F of threshold (reduces coin-flip losses)
    
    # Caching
    ORDERBOOK_CACHE_TTL = int(os.getenv('ORDERBOOK_CACHE_TTL', '3'))  # 3 seconds
    PORTFOLIO_CACHE_TTL = int(os.getenv('PORTFOLIO_CACHE_TTL', '10'))  # 10 seconds
    # 24/7 free-tier: Pirate Weather 10k/month (no daily reset) → need ~333/day → TTL ≥ 156 min. Default 3h (10800) keeps all APIs in free tier.
    FORECAST_CACHE_TTL = int(os.getenv('FORECAST_CACHE_TTL', '10800'))  # 3 hours (was 30 min)
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

    # Exit/Sell Logic
    EXIT_LOGIC_ENABLED = os.getenv('EXIT_LOGIC_ENABLED', 'true').lower() == 'true'  # Enabled - sell when profitable
    EXIT_TAKE_PROFIT_PERCENT = float(os.getenv('EXIT_TAKE_PROFIT_PERCENT', '30.0'))  # Sell when position is +30% profitable
    EXIT_MIN_PROFIT_CENTS = int(os.getenv('EXIT_MIN_PROFIT_CENTS', '5'))  # Minimum 5¢ profit to trigger exit

    # Stale Order Management
    STALE_ORDER_MIN_AGE_MINUTES = int(os.getenv('STALE_ORDER_MIN_AGE_MINUTES', '5'))  # Don't cancel orders younger than 5 min

    # Scaled Edge Requirements (require more edge for expensive contracts)
    SCALED_EDGE_ENABLED = os.getenv('SCALED_EDGE_ENABLED', 'true').lower() == 'true'
    SCALED_EDGE_PRICE_THRESHOLD = int(os.getenv('SCALED_EDGE_PRICE_THRESHOLD', '35'))  # Apply scaling above 35¢
    SCALED_EDGE_MULTIPLIER = float(os.getenv('SCALED_EDGE_MULTIPLIER', '1.5'))  # Require 1.5x edge for expensive contracts

    # Market Making Mode (post limit orders at better prices instead of paying the ask)
    MARKET_MAKING_ENABLED = os.getenv('MARKET_MAKING_ENABLED', 'true').lower() == 'true'
    MM_MIN_SPREAD_TO_MAKE = int(os.getenv('MM_MIN_SPREAD_TO_MAKE', '3'))  # Minimum spread to post maker orders
    MM_MAX_SPREAD_TO_MAKE = int(os.getenv('MM_MAX_SPREAD_TO_MAKE', '15'))  # Don't make very wide markets
    MM_REQUOTE_THRESHOLD = int(os.getenv('MM_REQUOTE_THRESHOLD', '2'))  # Requote if outbid by this many cents
    MM_AGGRESSIVE_EDGE_THRESHOLD = float(os.getenv('MM_AGGRESSIVE_EDGE_THRESHOLD', '25.0'))  # Take liquidity if edge > this
    MM_ORDER_URGENCY = os.getenv('MM_ORDER_URGENCY', 'normal')  # 'low', 'normal', 'high'

    # Position Sizing Enhancements
    # 1. Time Decay: Reduce position size based on hours until temperature extreme
    TIME_DECAY_ENABLED = os.getenv('TIME_DECAY_ENABLED', 'true').lower() == 'true'
    TIME_DECAY_MIN_FACTOR = float(os.getenv('TIME_DECAY_MIN_FACTOR', '0.5'))  # Min 50% of base size
    HIGH_EXTREME_HOUR = int(os.getenv('HIGH_EXTREME_HOUR', '16'))  # 4 PM local for daily highs
    LOW_EXTREME_HOUR = int(os.getenv('LOW_EXTREME_HOUR', '6'))  # 6 AM local for daily lows

    # 2. Correlation Adjustment: Reduce size when holding correlated positions (same city/date)
    CORRELATION_ADJUSTMENT_ENABLED = os.getenv('CORRELATION_ADJUSTMENT_ENABLED', 'true').lower() == 'true'
    CORRELATION_MAX_REDUCTION = float(os.getenv('CORRELATION_MAX_REDUCTION', '0.5'))  # Max 50% reduction

    # 3. Liquidity Cap: Don't take more than X% of visible liquidity
    LIQUIDITY_CAP_ENABLED = os.getenv('LIQUIDITY_CAP_ENABLED', 'true').lower() == 'true'
    LIQUIDITY_CAP_PERCENT = float(os.getenv('LIQUIDITY_CAP_PERCENT', '0.5'))  # Take max 50% of visible
    LIQUIDITY_PRICE_TOLERANCE = int(os.getenv('LIQUIDITY_PRICE_TOLERANCE', '2'))  # Within 2 cents

    # 4. EV-Proportional Sizing: Size proportionally to expected value
    EV_PROPORTIONAL_ENABLED = os.getenv('EV_PROPORTIONAL_ENABLED', 'true').lower() == 'true'
    EV_BASELINE_LONGSHOT = float(os.getenv('EV_BASELINE_LONGSHOT', '0.05'))  # $0.05 baseline
    EV_BASELINE_CONSERVATIVE = float(os.getenv('EV_BASELINE_CONSERVATIVE', '0.02'))  # $0.02 baseline
    
    # Adaptive Learning Settings
    # Enable/disable adaptive city management (auto-disable poor performers)
    ADAPTIVE_ENABLED = os.getenv('ADAPTIVE_ENABLED', 'true').lower() == 'true'
    # Minimum trades before evaluating city performance
    ADAPTIVE_MIN_TRADES = int(os.getenv('ADAPTIVE_MIN_TRADES', '20'))
    # Disable city if win rate falls below this threshold (40% = 0.40)
    ADAPTIVE_DISABLE_WIN_RATE = float(os.getenv('ADAPTIVE_DISABLE_WIN_RATE', '0.40'))
    # How long to disable a city (in hours)
    ADAPTIVE_DISABLE_HOURS = int(os.getenv('ADAPTIVE_DISABLE_HOURS', '24'))
    # How often to check if disabled cities should be re-enabled (in hours)
    ADAPTIVE_REENABLE_CHECK_HOURS = int(os.getenv('ADAPTIVE_REENABLE_CHECK_HOURS', '6'))
    # Maximum source RMSE before marking unreliable (in degrees F)
    MAX_SOURCE_RMSE = float(os.getenv('MAX_SOURCE_RMSE', '4.0'))
    # Enable/disable persisting learned state (biases, errors) across restarts
    PERSIST_LEARNING = os.getenv('PERSIST_LEARNING', 'true').lower() == 'true'

    # Hard-disabled cities (bypasses all other filters — will never trade)
    DISABLED_CITIES = {c.strip() for c in os.getenv('DISABLED_CITIES', 'DEN').split(',') if c.strip()}

    # Market Tickers
    # High and Low temperature markets for NYC, Chicago, Miami, Austin, Los Angeles
    # Denver disabled due to poor forecast accuracy (19% win rate, -$46 P&L)
    WEATHER_SERIES = [
        'KXHIGHNY', 'KXLOWNY',      # New York City
        'KXHIGHCHI', 'KXLOWCHI',    # Chicago
        'KXHIGHMIA', 'KXLOWMIA',    # Miami
        'KXHIGHAUS', 'KXLOWAUS',    # Austin
        'KXHIGHLAX', 'KXLOWLAX',    # Los Angeles
        # 'KXHIGHDEN', 'KXLOWDEN'   # Denver - DISABLED
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
