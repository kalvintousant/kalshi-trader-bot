# Kalshi Weather Trading Bot

Automated trading bot for Kalshi **daily weather markets** using advanced multi-source forecast aggregation and dual-strategy approach (longshot + conservative).

## Features

- **Daily Weather Markets**: Multi-source forecast aggregation strategy
  - Aggregates forecasts from multiple weather APIs (NWS, Tomorrow.io, Weatherbit)
  - Supports both HIGH and LOW temperature markets for 4 cities
  - Dual strategy: Longshot mode (asymmetric payouts) + Conservative mode (steady gains)
  - Calculates edge and expected value (EV) based on probability distributions
  - Optimized for all contract rules (NHIGH, CHIHIGH, MIHIGH, AUSHIGH, and LOW variants)
  - Daytime schedule (6am-10pm) optimized for forecast update patterns
  
- **Real-time Market Data**: Efficient polling with caching and connection pooling
- **Trade Notifications**: macOS notifications + file logging for every trade
- **Risk Management**: Daily loss limits and position sizing controls
- **Performance Optimized**: Caching, connection pooling, parallel execution
- **Automatic Scheduling**: Runs during optimal hours (6am-10pm) via cron

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

### Daytime Schedule (Recommended)

The bot is configured to run automatically during optimal trading hours:

**Automatic (via cron):**
- Starts at 6:00 AM daily
- Stops at 10:00 PM daily
- No manual intervention needed

**Manual start:**
```bash
./start_daytime.sh
```
(Only starts if between 6am-10pm)

**Set up automatic scheduling:**
```bash
./setup_schedule.sh
```
Follow instructions to configure cron jobs.

### Manual Operation

Run the bot manually:
```bash
python3 bot.py
```

Run in background (keeps laptop awake):
```bash
nohup caffeinate -i python3 -u bot.py > bot_output.log 2>&1 &
```

The bot will:
- Scan markets every 30 minutes (optimized for daily weather markets)
- Evaluate markets using dual strategy (longshot + conservative)
- Place trades when opportunities are identified
- Send macOS notifications for each trade
- Log all trades to `trades.log`
- Detect new markets immediately for early entry opportunities
- Run during daytime hours (6am-10pm) when forecasts update most

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

- `MAX_POSITION_SIZE`: Maximum contracts per trade (default: 1 for weather)
- `MAX_DAILY_LOSS`: Stop trading if daily loss exceeds this (default: $20)
- `ENABLED_STRATEGIES`: Set to `weather_daily` for weather markets

Example:
```
MAX_POSITION_SIZE=1
MAX_DAILY_LOSS=20
ENABLED_STRATEGIES=weather_daily
```

### Weather API Keys

Add to `.env`:
```
TOMORROWIO_API_KEY=your_key
WEATHERBIT_API_KEY=your_key
```

NWS is free and requires no key. All APIs stay within free tier limits.

## Strategy: Weather Daily Markets

### Dual Strategy Approach

**Dual Strategy Approach:**

**1. Conservative Mode (High Win Rate)**
- Min edge: 5%, Min EV: $0.01
- Any price range
- Position size: 1 contract
- Expected win rate: 60-80%
- Steady, predictable returns

**2. Longshot Mode (Asymmetric Payouts) 🎯**
- Target: Market price ≤ 10¢ (cheap shares)
- Min edge: 30% (massive mispricing)
- Our probability: ≥ 50% (forecast certainty)
- Position size: 3 contracts (3x multiplier)
- Expected win rate: 25-40%
- 10-20x returns when right

**How it works:**
1. Aggregates forecasts from 3 weather APIs (NWS, Tomorrow.io, Weatherbit)
2. Builds probability distributions using normal distribution
3. Calculates edge: `(Your Probability - Market Price) × 100`
4. Checks longshot criteria first (priority for big wins)
5. Falls back to conservative mode (consistent gains)

**Why this works:** Inspired by successful Polymarket bot ($27 → $63K). Buys "cheap certainty" - when market says 10% but forecasts say 80%. Low win rate acceptable when payouts are 10-20x.

**Supported Markets:**
- **High Temperature Markets**: KXHIGHNY, KXHIGHCH, KXHIGHMI, KXHIGHAU
- **Low Temperature Markets**: KXLOWNY, KXLOWCH, KXLOWMI, KXLOWAU
- **Cities**: New York City, Chicago, Miami, Austin

**Official Measurement Locations (per contract rules):**
- **New York**: Central Park (40.7711°N, 73.9742°W) - NHIGH/NLOW contracts
- **Chicago**: Chicago Midway Airport (41.7868°N, 87.7522°W) - CHIHIGH/CHILOW contracts
- **Miami**: Miami International Airport (25.7932°N, 80.2906°W) - MIHIGH/MILOW contracts
- **Austin**: Austin Bergstrom International Airport (30.1831°N, 97.6799°W) - AUSHIGH/AUSLOW contracts

**Contract Compliance:**
- Optimized for all weather contract rules (NHIGH, CHIHIGH, MIHIGH, AUSHIGH, and LOW variants)
- Uses official NWS measurement locations matching contract settlement data
- 30-minute scan interval matches forecast update frequency
- 30-minute forecast cache ensures compliance with API rate limits
- Coordinates match exact weather station locations used for contract settlement

**Data Sources:**
- National Weather Service (NWS) - Free, no API key needed
- Tomorrow.io - Free tier (500 calls/day)
- Weatherbit - Free tier (500 calls/day)
- OpenWeather - Removed (per optimization)

**Optimizations:**
- Scan interval: 30 minutes (matches forecast cache TTL - appropriate for daily settlements)
- Forecast cache: 30 minutes (reduces API calls by 95%)
- API calls: ~192/day per API (38.4% of 500/day free tier limit)
- Parallel fetching: All 3 APIs called simultaneously for speed
- Official NWS coordinates: Matches exact measurement locations for accuracy
- Quality thresholds: Min edge 5%, min EV $0.01, min volume 15 contracts
- Daytime schedule: 6am-10pm (when forecasts update most)
- Contract compliance: Optimized for all weather contract rules

See [WEATHER_STRATEGY.md](WEATHER_STRATEGY.md), [LONGSHOT_STRATEGY.md](LONGSHOT_STRATEGY.md), and [DAYTIME_SCHEDULE.md](DAYTIME_SCHEDULE.md) for detailed documentation.

## Project Structure

```
.
├── bot.py                       # Main bot orchestrator
├── strategies.py                # Weather trading strategies (dual mode)
├── kalshi_client.py             # Kalshi API client with authentication
├── weather_data.py              # Multi-source weather forecast aggregation
├── config.py                    # Configuration management
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variable template
├── README.md                    # This file
├── start_daytime.sh             # Daytime startup script (6am-10pm)
├── setup_schedule.sh            # Cron setup instructions
├── start_bot.sh                 # 24/7 startup script (if needed)
├── WEATHER_STRATEGY.md          # Weather strategy documentation
├── LONGSHOT_STRATEGY.md         # Asymmetric longshot strategy guide
├── DAYTIME_SCHEDULE.md          # Daytime scheduling documentation
├── WEATHER_OPTIMIZATION.md      # API efficiency analysis
├── STRATEGY_IMPROVEMENTS.md     # Improvement framework
└── OPTIMIZATION_FINAL.md        # Production optimization details
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
- **Forecast caching**: 30-minute cache reduces weather API calls by 95%
- **New market detection**: Tracks seen markets to prioritize new ones
- **Parallel API calls**: Weather forecasts fetched simultaneously from 3 sources
- **Optimized for free tiers**: All weather APIs stay within free tier limits (38% usage)
- **Daytime schedule**: Runs during optimal hours (6am-10pm) when forecasts update most
- **Contract compliance**: Optimized scan intervals and coordinates for all weather contracts

See [OPTIMIZATION_FINAL.md](OPTIMIZATION_FINAL.md) and [WEATHER_OPTIMIZATION.md](WEATHER_OPTIMIZATION.md) for details.

## Important Notes

- **Daytime schedule**: Bot runs 6am-10pm when forecasts update most (automatic via cron)
- **Risk management**: Set appropriate position sizes and loss limits (default: $20 max daily loss)
- **Rate limits**: All weather APIs stay within free tier limits (38% usage)
- **Contract compliance**: Bot optimized for all weather contract rules (NHIGH, CHIHIGH, MIHIGH, AUSHIGH, and LOW variants)
- **Official coordinates**: Uses exact NWS measurement locations matching contract settlement data
- **Forecast accuracy**: Multi-source aggregation (3 APIs) for better probability estimates

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
- [Weather Contract Terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/) (NHIGH, CHIHIGH, MIHIGH, AUSHIGH, and LOW variants)

## License

Private repository - All rights reserved.
