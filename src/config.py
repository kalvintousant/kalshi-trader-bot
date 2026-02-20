import os
from dotenv import load_dotenv

load_dotenv()


def extract_city_code(series_ticker: str) -> str:
    """Extract city code from series ticker (e.g., KXHIGHNY -> NY, KXHIGHTDAL -> DAL)."""
    for prefix in ('KXHIGHT', 'KXLOWT', 'KXHIGH', 'KXLOW'):
        if series_ticker.startswith(prefix):
            return series_ticker[len(prefix):]
    return series_ticker


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
    MIN_EDGE_THRESHOLD = float(os.getenv('MIN_EDGE_THRESHOLD', '8.0'))  # Minimum edge % to trade (relaxed to 8% for paper trading volume)
    MIN_EV_THRESHOLD = float(os.getenv('MIN_EV_THRESHOLD', '0.02'))  # Minimum EV in dollars (relaxed for paper trading data collection)
    # If True, only trade when confidence interval does NOT overlap market price (stricter).
    # If False (default), trade when edge/EV meet thresholds even if CI overlaps (more trades, higher risk).
    REQUIRE_HIGH_CONFIDENCE = os.getenv('REQUIRE_HIGH_CONFIDENCE', 'false').lower() == 'true'
    
    # Longshot strategy
    LONGSHOT_ENABLED = os.getenv('LONGSHOT_ENABLED', 'false').lower() == 'true'  # Disabled until probability model validated
    LONGSHOT_MAX_PRICE = int(os.getenv('LONGSHOT_MAX_PRICE', '10'))  # Only consider if market price ≤ 10¢
    LONGSHOT_MIN_EDGE = float(os.getenv('LONGSHOT_MIN_EDGE', '30.0'))  # Require massive edge (30%+)
    LONGSHOT_MIN_PROB = float(os.getenv('LONGSHOT_MIN_PROB', '50.0'))  # Our probability must be ≥ 50%
    LONGSHOT_POSITION_MULTIPLIER = int(os.getenv('LONGSHOT_POSITION_MULTIPLIER', '3'))  # Trade 3x normal size
    # Local hour (24h) after which we skip today's LOW markets (low of day usually 4–7 AM). 8 = 8 AM; set 9 or 10 to extend window.
    LONGSHOT_LOW_CUTOFF_HOUR = int(os.getenv('LONGSHOT_LOW_CUTOFF_HOUR', '8'))
    
    # Market filtering
    MIN_MARKET_VOLUME = int(os.getenv('MIN_MARKET_VOLUME', '15'))  # Minimum volume for liquidity
    MAX_MARKET_DATE_DAYS = int(os.getenv('MAX_MARKET_DATE_DAYS', '1'))  # 1-day horizon: only trade today/tomorrow (forecasts most accurate)
    # Never buy at or above this price (cents). Data shows 51-75¢ entries lose money (42% win rate).
    MAX_BUY_PRICE_CENTS = int(os.getenv('MAX_BUY_PRICE_CENTS', '55'))  # Allow moderately priced contracts; scaled edge still guards >35c
    MAX_NO_BUY_PRICE_CENTS = int(os.getenv('MAX_NO_BUY_PRICE_CENTS', '30'))  # NO bets at 40-50¢ are near coin-flips with bad risk/reward
    # Skip single-threshold markets when mean forecast is within this many degrees of the threshold
    # (reduces "coin flip" losses when actual lands right on the boundary). 0 = disabled.
    MIN_DEGREES_FROM_THRESHOLD = float(os.getenv('MIN_DEGREES_FROM_THRESHOLD', '1.0'))  # Skip trades within 1°F of threshold (relaxed from 2.0 for volume)

    # Forecast quality gates
    MIN_FORECAST_SOURCES = int(os.getenv('MIN_FORECAST_SOURCES', '2'))  # Need >=2 independent forecasts (rate-limited sources often 429)
    MIN_FORECAST_SPREAD = float(os.getenv('MIN_FORECAST_SPREAD', '0.5'))  # Minimum std across forecasts (°F) — blocks correlated sources

    # Forecast direction gate: only trade when the forecast mean supports the bet direction
    # For "below" markets (YES = temp < T): require forecast mean < threshold
    # For "above" markets (YES = temp > T): require forecast mean > threshold
    REQUIRE_FORECAST_DIRECTION = os.getenv('REQUIRE_FORECAST_DIRECTION', 'true').lower() == 'true'

    # Range market boundary guard
    RANGE_BOUNDARY_MIN_DISTANCE = float(os.getenv('RANGE_BOUNDARY_MIN_DISTANCE', '3.0'))  # Skip range markets when forecast is within 3°F of boundary

    # Range market controls (range markets have 0% WR in real trading — disabled by default)
    RANGE_MARKETS_ENABLED = os.getenv('RANGE_MARKETS_ENABLED', 'false').lower() == 'true'
    RANGE_MAX_BUY_PRICE_CENTS = int(os.getenv('RANGE_MAX_BUY_PRICE_CENTS', '25'))  # Lower ceiling than global 40c
    RANGE_MIN_EDGE_MULTIPLIER = float(os.getenv('RANGE_MIN_EDGE_MULTIPLIER', '2.0'))  # Require 2x normal edge (30% vs 15%)
    RANGE_MAX_PROBABILITY = float(os.getenv('RANGE_MAX_PROBABILITY', '0.40'))  # Cap computed probability (realistic for 2°F bin)
    RANGE_MIN_STD_FLOOR = float(os.getenv('RANGE_MIN_STD_FLOOR', '3.0'))  # Higher std floor than threshold markets

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
    MIN_SAMPLES_FOR_BIAS = int(os.getenv('MIN_SAMPLES_FOR_BIAS', '10'))  # Min samples before applying bias correction
    MAX_BIAS_CORRECTION_F = float(os.getenv('MAX_BIAS_CORRECTION_F', '3.0'))  # Cap bias correction magnitude (°F)
    NWS_SOURCE_WEIGHT = float(os.getenv('NWS_SOURCE_WEIGHT', '1.5'))  # Extra weight for NWS (Kalshi settles on NWS CLI)

    # Exit/Sell Logic
    EXIT_LOGIC_ENABLED = os.getenv('EXIT_LOGIC_ENABLED', 'true').lower() == 'true'  # Enabled - sell when profitable
    EXIT_TAKE_PROFIT_PERCENT = float(os.getenv('EXIT_TAKE_PROFIT_PERCENT', '30.0'))  # Sell when position is +30% profitable
    EXIT_MIN_PROFIT_CENTS = int(os.getenv('EXIT_MIN_PROFIT_CENTS', '5'))  # Minimum 5¢ profit to trigger exit
    EXIT_MIN_ENTRY_PRICE = int(os.getenv('EXIT_MIN_ENTRY_PRICE', '15'))  # Never sell positions entered at or below this price

    # Stale Order Management
    STALE_ORDER_MIN_AGE_MINUTES = int(os.getenv('STALE_ORDER_MIN_AGE_MINUTES', '5'))  # Don't cancel orders younger than 5 min

    # Scaled Edge Requirements (require more edge for expensive contracts)
    SCALED_EDGE_ENABLED = os.getenv('SCALED_EDGE_ENABLED', 'true').lower() == 'true'
    SCALED_EDGE_PRICE_THRESHOLD = int(os.getenv('SCALED_EDGE_PRICE_THRESHOLD', '35'))  # Apply scaling above 35¢
    SCALED_EDGE_MULTIPLIER = float(os.getenv('SCALED_EDGE_MULTIPLIER', '1.2'))  # Require 1.2x edge for expensive contracts (relaxed from 1.5)

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
    HIGH_EXTREME_HOUR = int(os.getenv('HIGH_EXTREME_HOUR', '18'))  # 6 PM local for daily highs (extended from 4 PM; outcome check handles observed extremes)
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

    # 5. Fee-Aware Sizing: Adjust position size based on price band profitability
    # Historical data shows: 0% win rate <10¢, sweet spot at 15-40¢, diminishing returns above
    FEE_AWARE_SIZING_ENABLED = os.getenv('FEE_AWARE_SIZING_ENABLED', 'true').lower() == 'true'
    FEE_AWARE_SWEET_LOW = int(os.getenv('FEE_AWARE_SWEET_LOW', '15'))   # Sweet spot lower bound (cents)
    FEE_AWARE_SWEET_HIGH = int(os.getenv('FEE_AWARE_SWEET_HIGH', '40'))  # Sweet spot upper bound (cents)
    FEE_AWARE_SWEET_MULTIPLIER = float(os.getenv('FEE_AWARE_SWEET_MULTIPLIER', '1.5'))  # Boost in sweet spot
    FEE_AWARE_CHEAP_MULTIPLIER = float(os.getenv('FEE_AWARE_CHEAP_MULTIPLIER', '0.5'))  # Reduce for cheap contracts
    FEE_AWARE_EXPENSIVE_MULTIPLIER = float(os.getenv('FEE_AWARE_EXPENSIVE_MULTIPLIER', '0.75'))  # Reduce for expensive
    
    # Adaptive Learning Settings
    # Enable/disable adaptive city management (auto-disable poor performers)
    ADAPTIVE_ENABLED = os.getenv('ADAPTIVE_ENABLED', 'true').lower() == 'true'
    # Minimum trades before evaluating city performance (lowered from 20 for faster response)
    ADAPTIVE_MIN_TRADES = int(os.getenv('ADAPTIVE_MIN_TRADES', '10'))
    # Disable city if win rate falls below this threshold (raised from 40% — need >50% to be profitable)
    ADAPTIVE_DISABLE_WIN_RATE = float(os.getenv('ADAPTIVE_DISABLE_WIN_RATE', '0.50'))
    # How long to disable a city (in hours) — extended from 24h to 72h for meaningful cooldown
    ADAPTIVE_DISABLE_HOURS = int(os.getenv('ADAPTIVE_DISABLE_HOURS', '72'))
    # How often to check if disabled cities should be re-enabled (in hours)
    ADAPTIVE_REENABLE_CHECK_HOURS = int(os.getenv('ADAPTIVE_REENABLE_CHECK_HOURS', '6'))
    # Maximum source RMSE before marking unreliable (in degrees F)
    MAX_SOURCE_RMSE = float(os.getenv('MAX_SOURCE_RMSE', '4.0'))
    # Enable/disable persisting learned state (biases, errors) across restarts
    PERSIST_LEARNING = os.getenv('PERSIST_LEARNING', 'true').lower() == 'true'

    # Paper Trading Mode (simulate trades without placing real orders)
    PAPER_TRADING = os.getenv('PAPER_TRADING', 'false').lower() == 'true'

    # Web Dashboard (aiohttp, served from bot process)
    WEB_DASHBOARD_ENABLED = os.getenv('WEB_DASHBOARD_ENABLED', 'false').lower() == 'true'
    WEB_DASHBOARD_HOST = os.getenv('WEB_DASHBOARD_HOST', '0.0.0.0')
    WEB_DASHBOARD_PORT = int(os.getenv('WEB_DASHBOARD_PORT', '8050'))

    # Hard-disabled cities (bypasses all other filters — will never trade)
    DISABLED_CITIES = {c.strip() for c in os.getenv('DISABLED_CITIES', '').split(',') if c.strip()}

    # Market Tickers
    # High and Low temperature markets for NYC, Chicago, Miami, Austin, Los Angeles
    # Denver disabled due to poor forecast accuracy (19% win rate, -$46 P&L)
    WEATHER_SERIES = [
        'KXHIGHNY', 'KXLOWNY',      # New York City
        'KXHIGHCHI', 'KXLOWCHI',    # Chicago
        'KXHIGHMIA', 'KXLOWMIA',    # Miami
        'KXHIGHAUS', 'KXLOWAUS',    # Austin
        'KXHIGHLAX', 'KXLOWLAX',    # Los Angeles
        'KXHIGHDEN', 'KXLOWDEN',    # Denver
        'KXHIGHPHIL', 'KXLOWTPHIL', # Philadelphia (HIGH + LOW)
        'KXHIGHTDAL',               # Dallas (HIGH only)
        'KXHIGHTBOS',               # Boston (HIGH only)
        'KXHIGHTATL',               # Atlanta (HIGH only)
        'KXHIGHTHOU',               # Houston (HIGH only)
        'KXHIGHTSEA',               # Seattle (HIGH only)
        'KXHIGHTPHX',               # Phoenix (HIGH only)
        'KXHIGHTMIN',               # Minneapolis (HIGH only)
        'KXHIGHTDC',                # Washington DC (HIGH only)
        'KXHIGHTOKC',               # Oklahoma City (HIGH only)
        'KXHIGHTSFO',               # San Francisco (HIGH only)
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
