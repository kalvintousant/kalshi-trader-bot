# Kalshi Trading Bot

Automated trading bot for Kalshi prediction markets, supporting **hourly BTC markets** and **daily weather markets** with advanced strategies.

## Features

- **Hourly BTC Markets**: Latency arbitrage strategy on Bitcoin price movement predictions
  - Tracks real-time BTC moves from Binance
  - Detects mispricing when Kalshi odds lag behind market movements
  - Automated entry/exit logic
  
- **Daily Weather Markets**: Multi-source forecast aggregation strategy
  - Aggregates forecasts from multiple weather APIs (NWS, Tomorrow.io, Weatherbit)
  - Supports both HIGH and LOW temperature markets for 4 cities
  - Calculates edge and expected value (EV) based on probability distributions
  - Trades when edge > threshold
  - Optimized for AUSHIGH contract rules (5-minute scans, 30-minute cache)
  
- **Real-time Market Data**: Efficient polling with caching and connection pooling
- **Trade Notifications**: macOS notifications + file logging for every trade
- **Risk Management**: Daily loss limits and position sizing controls
- **Performance Optimized**: Caching, connection pooling, parallel execution

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Get Kalshi API credentials**:
   - Create a Kalshi account at https://kalshi.com
   - Generate API keys in Account & Security settings
   - Download your private key (you can only download it once!)

3. **Configure environment**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your API credentials:
   ```
   KALSHI_API_KEY_ID=your_api_key_id
   KALSHI_PRIVATE_KEY_PATH=/path/to/private_key.pem
   ```

4. **Optional: Weather API Keys** (for weather strategy):
   - NWS is free and requires no key
   - Get free API keys from [Tomorrow.io](https://www.tomorrow.io/weather-api/) and [Weatherbit](https://www.weatherbit.io/api)
   - Add them to `.env`:
   ```
   TOMORROWIO_API_KEY=your_key
   WEATHERBIT_API_KEY=your_key
   ```
   - All APIs stay within free tier limits with optimized call intervals

5. **Test with demo environment first** (optional):
   Update `.env` to use demo URLs:
   ```
   KALSHI_BASE_URL=https://demo-api.kalshi.co/trade-api/v2
   KALSHI_WS_URL=wss://demo-api.kalshi.co/trade-api/ws/v2
   ```

## Usage

Run the bot:
```bash
python3 bot.py
```

Run in background (keeps laptop awake):
```bash
caffeinate -i python3 -u bot.py > bot_output.log 2>&1 &
```

The bot will:
- Scan markets adaptively: 0.5 seconds (BTC 15-min), 10 seconds (BTC hourly), or 5 minutes (weather)
- Evaluate markets using enabled strategies
- Place trades when opportunities are identified
- Send macOS notifications for each trade
- Log all trades to `trades.log`
- Detect new markets immediately for early entry opportunities

### Monitoring

Watch live activity:
```bash
tail -f bot_output.log
```

Watch trades only:
```bash
tail -f trades.log
```

Stop the bot:
```bash
pkill -f "python3.*bot.py"
```

## Configuration

Edit `.env` to customize:

- `MAX_POSITION_SIZE`: Maximum contracts per trade (default: 10)
- `MAX_DAILY_LOSS`: Stop trading if daily loss exceeds this (default: $100)
- `ENABLED_STRATEGIES`: Comma-separated list:
  - `btc_15m` - 15-minute BTC latency arbitrage (KXBTC15M - up/down markets)
  - `btc_hourly` - Hourly BTC latency arbitrage (KXBTC - price range markets)
  - `weather_daily` - Daily weather markets with multi-source forecasts

Example:
```
MAX_POSITION_SIZE=1
MAX_DAILY_LOSS=10
ENABLED_STRATEGIES=btc_hourly
```

## Strategies

### BTC Hourly Strategy (Latency Arbitrage)

**How it works:**
1. Tracks real-time BTC price movements from Binance (5-minute candles)
2. Calculates momentum and volatility over 1-hour periods
3. Compares expected price (based on BTC move) to actual Kalshi odds
4. Enters trades when mispricing detected (>3 cents difference)
5. Exits automatically when pricing catches up

**Entry Conditions:**
- BTC momentum > 0.3% (configurable)
- Volatility > 0.2% (ensures real move)
- Mispricing > 3 cents (Kalshi hasn't caught up)

**Exit Logic:**
- Pricing moves towards expected value (mispricing closes)
- Position becomes profitable
- Minimum hold time: 30 seconds

**Contract Compliance:**
- Uses `KXBTC` series (hourly BTC markets)
- Tracks 1-hour price changes to match market expiration
- Only trades markets with `status='open'` (respects expiration)
- See [CONTRACT_COMPLIANCE.md](CONTRACT_COMPLIANCE.md) for details

### Weather Daily Strategy (Edge + EV)

**How it works:**
1. Aggregates forecasts from multiple weather APIs (3 sources)
2. Builds probability distributions over temperature ranges using normal distribution
3. Calculates edge: `(Your Probability - Market Price) × 100`
4. Calculates EV: `(Win Prob × Payout) - (Loss Prob × Stake)`
5. Trades when edge ≥ 5% and EV ≥ $0.01 (optimized thresholds)

**Strategy Parameters (Optimized for Production):**
- Min edge: 5% (ensures quality trades)
- Min EV: $0.01 (10x threshold for better ROI)
- Min volume: 15 contracts (better liquidity than 5)
- Forecast sources: 3 parallel APIs (NWS, Tomorrow.io, Weatherbit)

**Supported Markets:**
- **High Temperature Markets**: KXHIGHNY, KXHIGHCH, KXHIGHMI, KXHIGHAU
- **Low Temperature Markets**: KXLOWNY, KXLOWCH, KXLOWMI, KXLOWAU
- **Cities**: New York City, Chicago, Miami, Austin

**Official Measurement Locations (per contract rules):**
- **New York**: Central Park (40.7711°N, 73.9742°W) - NHIGH contract
- **Chicago**: Chicago Midway Airport (41.7868°N, 87.7522°W) - CHIHIGH contract
- **Miami**: Miami International Airport (25.7932°N, 80.2906°W) - MIHIGH contract
- **Austin**: Austin Bergstrom International Airport (30.1831°N, 97.6799°W) - AUSHIGH contract

**Data Sources:**
- National Weather Service (NWS) - Free, no API key needed
- Tomorrow.io - Free tier (500 calls/day)
- Weatherbit - Free tier (500 calls/day)
- OpenWeather - Removed (per optimization)

**Optimizations:**
- Scan interval: 5 minutes (per AUSHIGH contract rules - daily markets)
- Forecast cache: 30 minutes (reduces API calls by 95%)
- API calls: ~192/day per API (38.4% of 500/day free tier limit)
- Parallel fetching: All 3 APIs called simultaneously for speed
- Official NWS coordinates: Matches exact measurement locations for accuracy
- Quality thresholds: Min edge 5%, min EV $0.01, min volume 15 contracts

See [WEATHER_STRATEGY.md](WEATHER_STRATEGY.md) and [BTC_STRATEGY.md](BTC_STRATEGY.md) for detailed strategy documentation.

## Project Structure

```
.
├── bot.py                       # Main bot orchestrator
├── strategies.py                # Trading strategies (BTC 15-min, BTC hourly, Weather)
├── kalshi_client.py             # Kalshi API client with authentication
├── btc_data.py                  # BTC price tracking from Binance
├── weather_data.py              # Multi-source weather forecast aggregation
├── config.py                    # Configuration management
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variable template
├── README.md                    # This file
├── BTC_15MIN_STRATEGY.md        # 15-minute BTC strategy documentation
├── BTC_STRATEGY.md              # Hourly BTC strategy documentation
├── WEATHER_STRATEGY.md          # Weather strategy documentation
├── CONTRACT_COMPLIANCE.md       # Hourly BTC contract compliance
├── CRYPTO15M_COMPLIANCE.md      # 15-minute BTC contract compliance
├── PERFORMANCE_IMPROVEMENTS.md  # Performance optimizations
├── OPTIMIZATION_RECOMMENDATIONS.md # Further optimization suggestions
├── KEEP_RUNNING.md              # Guide for keeping bot running
└── OVERNIGHT_TEST.md            # Overnight testing guide
```

## Extending the Bot

To add a new strategy:
1. Create a class inheriting from `TradingStrategy` in `strategies.py`
2. Implement `should_trade()` and `get_trade_decision()` methods
3. Add it to `StrategyManager` in `strategies.py`
4. Update `ENABLED_STRATEGIES` in `.env`

Example:
```python
class MyStrategy(TradingStrategy):
    def should_trade(self, market: Dict) -> bool:
        # Check if this market matches your criteria
        return market.get('series_ticker') == 'MY_SERIES'
    
    def get_trade_decision(self, market: Dict, orderbook: Dict) -> Optional[Dict]:
        # Your trading logic here
        return {'action': 'buy', 'side': 'yes', 'count': 1, 'price': 50}
```

## Performance Optimizations

The bot includes several performance optimizations:
- **Orderbook caching**: 5-second cache to reduce API calls
- **Connection pooling**: Reuses HTTP connections
- **Market filtering**: Filters by series before expensive API calls
- **Shared BTC tracker**: Updates once per scan, not per market
- **Adaptive scan intervals**: 0.5s (BTC 15-min), 10s (BTC hourly), 5min (weather)
- **Forecast caching**: 30-minute cache reduces weather API calls by 95%
- **New market detection**: Tracks seen markets to prioritize new ones
- **Parallel API calls**: Weather forecasts fetched simultaneously from 3 sources
- **Optimized for free tiers**: All weather APIs stay within free tier limits

See [PERFORMANCE_IMPROVEMENTS.md](PERFORMANCE_IMPROVEMENTS.md) for details.

## Important Notes

- **Start with demo environment**: Always test in demo mode first
- **Risk management**: Set appropriate position sizes and loss limits
- **Rate limits**: The bot includes rate limiting and caching, but be mindful of API limits
- **Market hours**: Some markets only trade during specific hours
- **Contract compliance**: Bot respects Kalshi contract rules (see [CONTRACT_COMPLIANCE.md](CONTRACT_COMPLIANCE.md))
- **BRTI vs Binance**: Bot uses Binance as a proxy for BRTI (official index) for real-time tracking

## Trade Notifications

The bot sends notifications for every trade:
- **macOS notifications**: Pop-up alerts with trade details
- **Console output**: Formatted trade messages
- **File logging**: All trades logged to `trades.log` with timestamps

## Disclaimer

This bot is for educational purposes. Trading involves risk. Always:
- Test thoroughly in demo environment
- Start with small position sizes
- Monitor the bot closely
- Understand the markets you're trading
- Review contract terms and rules

## Resources

- [Kalshi API Documentation](https://docs.kalshi.com/)
- [Kalshi Trading Console](https://kalshi.com)
- [Kalshi Academy](https://help.kalshi.com/)
- [Kalshi BTC Contract Terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/BTC.pdf)

## License

Private repository - All rights reserved.
