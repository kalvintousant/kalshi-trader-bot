# Kalshi Weather Trading Bot

> **Production-ready automated trading system for Kalshi weather prediction markets**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Sophisticated algorithmic trading bot that leverages multi-source weather forecasting and probability analysis to identify and execute profitable trades on Kalshi's daily weather markets.

---

## 🎯 Overview

This bot implements a dual-strategy approach combining conservative edge-based trading with longshot opportunity detection. It aggregates forecasts from multiple weather APIs, performs statistical analysis, and executes trades based on expected value calculations with comprehensive risk management.

### Key Features

- **🌦️ Weather Markets Only**: Specialized focus on daily weather prediction markets (HIGH and LOW temperature)
- **📊 Multi-Source Data Aggregation**: Combines forecasts from 10+ weather sources including NWS, Open-Meteo, GEFS/ECMWF ensembles, Pirate Weather, Tomorrow.io, and more with outlier detection
- **🎲 Dual Trading Strategies**:
  - **Conservative**: High-confidence trades with >5% edge and positive EV
  - **Longshot**: Undervalued low-probability events (≤10¢, ≥50% estimated probability, ≥30% edge)
- **⏰ Smart Timing**: Longshots disabled after extreme (high/low) likely occurred - value is in early-day uncertainty
- **💰 Position Management**: Automatic exit logic with take-profit (20%), stop-loss (30%), and edge monitoring
- **🧮 Hybrid Position Sizing**: Automatically switches between Kelly Criterion (high confidence) and confidence scoring (lower confidence) for optimal bet sizing
- **🔒 Risk Controls**: Daily loss limits, position caps, and per-market exposure tracking (prevents over-trading)
- **✅ Outcome Validation**: Checks NWS observations to skip trades on already-determined outcomes (HIGH and LOW)
- **⚡ Performance Optimized**: API response caching (orderbook: 3s, portfolio: 10s, forecasts: 30m)
- **📝 Professional Logging**: Structured logging with rotating file handlers and detailed audit trail
- **🔄 Error Handling**: Comprehensive error handling with automatic retry logic and exponential backoff

---

## 📋 Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Trading Strategies](#trading-strategies)
- [Risk Management](#risk-management)
- [Architecture](#architecture)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

---

<a id="installation"></a>
## 🚀 Installation

### Prerequisites

- **Python 3.9+**
- **macOS** (tested on macOS 12+)
- **Kalshi API Credentials** ([Get API keys](https://kalshi.com/))
- **Weather API Keys** (optional - many sources are free):
  - Free (no key): NWS, Open-Meteo, GEFS Ensemble (31 members), ECMWF Ensemble (51 members)
  - Free tier (key required): [Tomorrow.io](https://www.tomorrow.io/), [Pirate Weather](https://pirateweather.net/), [Visual Crossing](https://www.visualcrossing.com/), [Weatherbit](https://www.weatherbit.io/)

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/kalshi-trader-bot.git
   cd kalshi-trader-bot
   ```

2. **Install dependencies**
   ```bash
   pip3 install -r requirements.txt
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   nano .env  # Edit with your API keys
   ```

4. **Verify installation**
   ```bash
   python3 -c "from src.bot import KalshiTradingBot; print('✅ Installation successful')"
   ```

---

<a id="configuration"></a>
## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# Kalshi API (Required)
KALSHI_API_KEY_ID=your-api-key-id
KALSHI_PRIVATE_KEY_PATH=/path/to/private_key.pem
KALSHI_BASE_URL=https://api.elections.kalshi.com/trade-api/v2

# Weather APIs (Optional - many free sources work without keys)
TOMORROWIO_API_KEY=your-tomorrow-api-key       # Optional (500 req/day free)
PIRATE_WEATHER_API_KEY=your-pirate-key         # Optional (10k req/month free)
VISUAL_CROSSING_API_KEY=your-vc-key            # Optional (1k records/day free)
WEATHERBIT_API_KEY=your-weatherbit-api-key     # Optional (50 req/day free)

# Trading Configuration
ENABLED_STRATEGIES=weather_daily
MAX_POSITION_SIZE=1                            # Contracts per order
MAX_CONTRACTS_PER_MARKET=3                     # Max contracts per market
MAX_DOLLARS_PER_MARKET=1.00                    # Max $ per market
MAX_DAILY_LOSS=10                              # Daily loss limit

# Strategy Parameters
MIN_EDGE_THRESHOLD=5.0                # Minimum edge percentage (%)
MIN_EV_THRESHOLD=0.01                 # Minimum expected value ($)
LONGSHOT_ENABLED=true
LONGSHOT_MAX_PRICE=10                 # Maximum price for longshots (¢)
LONGSHOT_MIN_EDGE=30                  # Minimum edge for longshots (%)
LONGSHOT_MIN_PROB=50                  # Minimum estimated probability (%)

# Risk Management
MAX_CONTRACTS_PER_MARKET=25
MAX_DOLLARS_PER_MARKET=300
MIN_MARKET_VOLUME=50                  # Minimum market volume to trade

# Performance
ORDERBOOK_CACHE_TTL=3                 # Seconds
PORTFOLIO_CACHE_TTL=10                # Seconds
FORECAST_CACHE_TTL=1800               # Seconds (30 minutes)

# Logging
LOG_LEVEL=INFO                        # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE=bot.log
```

### Trading Parameters Explained

| Parameter | Description | Default | Recommended Range |
|-----------|-------------|---------|-------------------|
| `MIN_EDGE_THRESHOLD` | Minimum edge (market mispricing) to trigger trade | 5.0% | 3-10% |
| `MIN_EV_THRESHOLD` | Minimum expected value after fees | $0.01 | $0.01-$0.10 |
| `MAX_CONTRACTS_PER_MARKET` | Hard cap on contracts per market | 25 | 10-50 |
| `MAX_DOLLARS_PER_MARKET` | Hard cap on dollars per market | $3.00 | $1-$10 |
| `MAX_DAILY_LOSS` | Daily loss limit (bot stops trading) | $500 | $200-$1000 |
| `LONGSHOT_MAX_PRICE` | Max price to consider longshot | 10¢ | 5-15¢ |
| `LONGSHOT_MIN_EDGE` | Min edge for longshot trades | 30% | 25-40% |

---

<a id="quick-start"></a>
## 🏃 Quick Start

### Option 1: Clean Start Script (Recommended)

Use the clean start script to ensure fresh Python environment:

```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
bash clean_start.sh
```

This script:
- Stops any existing bot instances
- Clears Python cache to prevent stale bytecode issues
- Removes old logs
- Starts bot with optimized environment
- Shows real-time status and log output

### Option 2: Direct Start

```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
export PYTHONPATH=.
python3 -B -u src/bot.py > bot_output.log 2>&1 &
```

### Option 3: Persistent Background Operation

For long-running operation (survives terminal close):

```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
nohup caffeinate -i env PYTHONPATH=. python3 -B -u src/bot.py > bot_output.log 2>&1 &
```

### Option 4: Scheduled Execution (Cron)

For daytime-only operation (6am-10pm):

```bash
# Edit crontab
crontab -e

# Add this line (adjust path):
0 6 * * * cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot" && bash clean_start.sh >> cron.log 2>&1
0 22 * * * pkill -f "python.*bot.py"
```

---

<a id="trading-strategies"></a>
## 🎯 Trading Strategies

### Conservative Strategy

**Criteria:**
- Edge ≥ 5%
- Expected Value ≥ $0.01 (after fees)
- High confidence (multiple sources agree)

**Position Sizing (Hybrid Approach):**

*Path 1: HIGH CONFIDENCE (2+ sources, 70%+ probability, CI outside market price)*
- **Kelly Criterion** with fractional=0.25 (quarter Kelly, ultra-safe)
- Formula: `position = 0.25 × kelly_fraction × portfolio_value / price`
- Range: 10-20 contracts (1x-2x base)

*Path 2: LOWER CONFIDENCE (1 source, <70% probability, or CI overlaps price)*
- **Confidence Scoring** based on edge, CI width, forecast agreement, and EV
- Formula: `multiplier = 0.5 + (confidence × 1.0)`, position = 10 × multiplier
- Range: 5-15 contracts (0.5x-1.5x base)

*Always capped at MIN(25 contracts, $3.00 / price)*

**Example:**
```
Market: "Will NYC get >1 inch of rain tomorrow?"
Our Probability: 68% (3 sources agree within 5%)
Market Price: 55¢ (implies 55% probability)
Edge: 13% → TRADE YES
Position: 15 contracts @ 55¢ = $8.25 risk
Expected Value: $2.08
```

### Longshot Strategy

Identifies undervalued low-probability events where the market significantly underprices an outcome.

**Criteria:**
- Market price ≤ 10¢
- Our estimated probability ≥ 50%
- Edge ≥ 30%
- **Timing**: Only trades before the extreme (high/low) has likely occurred
  - HIGH markets: Disabled after 4 PM local or when observed high ≈ forecasted high
  - LOW markets: Disabled after 8 AM local or when observed low ≈ forecasted low
  - Longshot value is in early-day uncertainty; after the extreme occurs, uncertainty collapses

**Position Sizing (Hybrid Approach):**

*Path 1: HIGH CONFIDENCE (2+ sources, CI doesn't overlap market price)*
- **Kelly Criterion** with fractional=0.5 (half Kelly)
- Formula: `position = 0.5 × kelly_fraction × portfolio_value / price`
- Range: Up to 50 contracts (5x base)

*Path 2: LOWER CONFIDENCE (1 source or CI overlaps price)*
- **Confidence Scoring** based on edge, CI width, forecast agreement, and EV
- Formula: `multiplier = 1 + (confidence × 4)`, position = 10 × multiplier
- Range: 10-50 contracts (1x-5x base)
- Emphasizes edge (40%) and EV (20%) for aggressive longshot plays

*Always capped at MIN(25 contracts, $3.00 / price)*

**Example:**
```
Market: "Will Denver high be >50°F today?"
Time: 10:00 AM (before 4 PM cutoff)
Our Probability: 60% (unusual warm pattern detected)
Market Price: 8¢ (implies 8% probability)
Edge: 52% → TRADE YES (Longshot)
Position: 22 contracts @ 8¢ = $1.76 risk
Potential Profit: 22 × (100¢ - 8¢) = $20.24 (+1150%)

Later at 5:00 PM:
Observed high: 52°F (already exceeded threshold)
Action: ⏸️ Longshots disabled (high already occurred, outcome certain)
```

### Position Exit Logic

Positions are automatically exited when:

1. **Take Profit**: 20% gain from entry price
2. **Stop Loss**: 30% loss from entry price
3. **Edge Disappears**: Re-evaluation shows edge has reversed or vanished

**Example Exit:**
```
Entry: Bought 15 YES @ 55¢ = $8.25
Current: 67¢ (+21.8% gain)
Action: SELL → Lock in ~$1.80 profit
```

---

<a id="risk-management"></a>
## 🛡️ Risk Management

### Multi-Layer Protection

1. **Position Limits**
   - Per-market contract cap: 25 contracts (tracks filled + resting orders)
   - Per-market dollar cap: $3.00 (tracks total exposure per market)
   - Max position size: 10 contracts (base)
   - **Per-Market Exposure Tracking**: Bot checks existing positions and resting orders before each trade to prevent exceeding limits across multiple orders

2. **Daily Loss Limit**
   - Bot automatically stops trading if daily P&L < -$500
   - Resets at midnight
   - Sends notification on limit hit

3. **Market Quality Filters**
   - Minimum volume: 15 contracts (default, configurable via `MIN_MARKET_VOLUME`)
   - Only trades "open" or "active" status markets
   - Markets are filtered by volume and status before evaluation
   - **Outcome-Determined Check**: For today's markets, checks NWS observed high/low temperature and skips trades if outcome is already certain (prevents trading on predetermined results)
   - **Longshot Timing Cutoff**: 
     - HIGH markets: Disables longshots after 4 PM local (high typically occurs 2-5 PM) or when observed high ≈ forecasted high
     - LOW markets: Disables longshots after 8 AM local (low typically occurs 4-7 AM) or when observed low ≈ forecasted low
     - Longshot value is in early-day uncertainty; after the extreme occurs, uncertainty collapses

4. **Forecast Quality Requirements**
   - Requires multiple data sources for high-confidence trades
   - Outlier detection and filtering
   - Age-weighted forecasts (newer = more weight)
   - Confidence interval calculation

5. **API Rate Limiting**
   - Automatic retry with exponential backoff
   - Respects Kalshi rate limits
   - Circuit breaker on persistent errors

---

<a id="architecture"></a>
## 🏗️ Architecture

### Project Structure

```
kalshi-trader-bot/
├── src/
│   ├── bot.py                 # Main bot orchestration
│   ├── strategies.py          # Trading strategy implementations
│   ├── kalshi_client.py       # Kalshi API client
│   ├── weather_data.py        # Weather data aggregation
│   ├── config.py              # Configuration management
│   └── logger.py              # Logging setup
├── scripts/
│   ├── start_bot.sh           # Production startup script
│   └── clean_start.sh         # Fresh startup with cache clearing
├── .env                       # Environment variables (not in repo)
├── .env.example               # Example configuration
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── TROUBLESHOOTING.md         # Troubleshooting guide
└── CODE_IMPROVEMENTS.md       # Development notes
```

### Key Components

#### 1. Bot (`src/bot.py`)
Main orchestration layer that:
- Manages trading loop and market scanning
- Coordinates between strategies and API client
- Handles portfolio tracking and daily P&L
- Implements heartbeat and health monitoring

#### 2. Strategies (`src/strategies.py`)
Trading logic including:
- `WeatherDailyStrategy`: Main weather market strategy
- Position tracking and exit logic
- Edge and EV calculations
- Kelly Criterion position sizing

#### 3. Kalshi Client (`src/kalshi_client.py`)
API wrapper with:
- Authentication and session management
- Order placement and management
- Portfolio and market data fetching
- Response caching (orderbook, portfolio)
- Rate limit handling

#### 4. Weather Data (`src/weather_data.py`)
Forecast aggregation featuring:
- **10+ Weather Data Sources**: NWS, NWS MOS, Open-Meteo (GFS/ECMWF/ICON), GEFS Ensemble (31 members), ECMWF Ensemble (51 members), Pirate Weather (HRRR), Tomorrow.io, Visual Crossing, Weatherbit
- **Ensemble-Based Uncertainty**: Real uncertainty from 82 physics-based weather models instead of synthetic estimates
- **Model-Specific Bias Correction**: Learns from historical errors and auto-corrects model biases
- Probability distribution modeling with dynamic standard deviation
- Outlier detection and filtering
- Source weighting by age and reliability
- Confidence interval calculation via bootstrap sampling
- **Real-time observation tracking**: Gets today's observed high/low from NWS stations
- **Smart timing logic**: Determines if extreme (high/low) has likely occurred for longshot cutoff

#### 5. Configuration (`src/config.py`)
Centralized configuration:
- Environment variable loading
- Trading parameters
- API credentials
- Cache TTL settings

#### 6. Logger (`src/logger.py`)
Structured logging:
- Console and file output
- Rotating file handler (10MB, 5 backups)
- Configurable log levels
- Trade audit trail

---

<a id="monitoring"></a>
## 📊 Monitoring

### Real-Time Monitoring

```bash
# Watch live bot activity
tail -f bot_output.log

# Watch trade executions
tail -f trades.log

# Check bot status
ps aux | grep "[p]ython.*bot"
```

### Log Files

| File | Contents | Retention |
|------|----------|-----------|
| `bot_output.log` | Main bot activity, market scanning, decisions | 10MB × 5 files |
| `trades.log` | Trade executions, order details, P&L | Forever |
| `bot.log` | Detailed debug info (if LOG_LEVEL=DEBUG) | 10MB × 5 files |

### Key Metrics to Monitor

```bash
# Daily P&L
grep "Daily P&L" bot_output.log | tail -1

# Recent trades
tail -20 trades.log

# Error rate
grep -c "ERROR" bot_output.log

# Markets scanned today
grep -c "Scanning markets" bot_output.log
```

### Health Checks

The bot emits heartbeat messages every 30 minutes:
```
[INFO] ❤️ Heartbeat: Bot alive, scanning markets...
```

If no heartbeat for >45 minutes, the bot may have crashed.

---

<a id="troubleshooting"></a>
## 🔧 Troubleshooting

### Bot Won't Start

**Symptoms:**
- `TypeError: object.__init__() takes exactly one argument`
- Error references non-existent line numbers

**Cause:** Python cached bytecode from old code version

**Solution:**
```bash
# Use clean start script (recommended)
bash clean_start.sh

# Or manually clear cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete
python3 -B -u src/bot.py
```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more details.

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `ModuleNotFoundError: No module named 'src'` | Python path not set | Run with `PYTHONPATH=.` or use start script |
| `401 Unauthorized` | Invalid Kalshi credentials | Check `.env` file |
| `429 Too Many Requests` | API rate limit hit | Bot automatically retries with backoff |
| No trades executing | Insufficient edge/EV | Lower `MIN_EDGE_THRESHOLD` or `MIN_EV_THRESHOLD` |
| Bot stops after short time | Daily loss limit hit | Check `MAX_DAILY_LOSS` setting |

### Getting Help

1. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Review `bot_output.log` for error messages
3. Enable debug logging: `LOG_LEVEL=DEBUG` in `.env`
4. Open an issue on GitHub with log excerpts

---

<a id="development"></a>
## 👨‍💻 Development

### Code Quality

- **Python 3.9+** with type hints
- **Black** code formatter
- **Comprehensive logging** at all levels
- **Error handling** with specific exception types
- **Docstrings** for all public methods

### Testing

```bash
# Verify imports
python3 -c "from src.bot import KalshiTradingBot; print('✅ OK')"

# Test weather data fetching
python3 -c "from src.weather_data import WeatherDataAggregator; w=WeatherDataAggregator(); print(w.get_forecasts('New York', datetime.now() + timedelta(days=1)))"

# Test Kalshi connection
python3 -c "from src.kalshi_client import KalshiClient; c=KalshiClient(); print(c.get_portfolio())"
```

### Recent Improvements

✅ **v2.4.0 (January 2026)**
- **🌐 Major Weather Data Expansion**: Added 7 new weather data sources
  - Open-Meteo: Free multi-model support (GFS, ECMWF, ICON, GEM, JMA)
  - Pirate Weather: HRRR-based, excellent for short-term US forecasts
  - Visual Crossing: Historical data support
  - NWS MOS: Model Output Statistics, bias-corrected forecasts
  - GEFS Ensemble: 31 members for real uncertainty quantification
  - ECMWF Ensemble: 51 members, world's most accurate model
- **📊 Ensemble-Based Uncertainty**: Replaces synthetic time-based estimates with real ensemble spread from 82 weather models
- **🎯 Model-Specific Bias Correction**: Learns from historical errors and auto-corrects model biases per city/month
- **🚀 Parallel Fetching**: Fetches from multiple sources simultaneously for speed
- **🔒 Enhanced Position Limits**: Added `MAX_CONTRACTS_PER_MARKET` and `MAX_DOLLARS_PER_MARKET` to prevent over-trading individual markets

✅ **v2.3.0 (January 2026)**
- **🧮 Hybrid Position Sizing**: Automatic selection between Kelly Criterion and confidence scoring
  - Kelly Criterion (math-based optimal) for high confidence: 2+ sources, CI doesn't overlap market
  - Confidence scoring (heuristic) for lower confidence: considers edge, CI width, forecast agreement, EV
  - Longshot: Kelly@50% or confidence (1x-5x base), Conservative: Kelly@25% or confidence (0.5x-1.5x base)
- **🚫 Determined Outcome Exclusion**: Markets with determined outcomes are added to exclusion list
  - Skipped in all future scans for performance and API rate limit reduction
  - Automatically cancels resting orders when outcome is detected
- **Enhanced Logging**: Debug logs show which sizing method (Kelly vs Confidence) was used and why

✅ **v2.2.0 (January 2026)**
- **Smart Longshot Timing**: Disables longshots after extreme (high/low) likely occurred
  - HIGH markets: After 4 PM local or when observed high ≈ forecasted high
  - LOW markets: After 8 AM local or when observed low ≈ forecasted low
  - Prevents wasting capital on near-certain outcomes late in the day
- **LOW Temperature Market Support**: Full support for low temperature markets with outcome validation
- Added `get_todays_observed_low()` for tracking low temperature observations
- Enhanced outcome-determined check to handle both HIGH and LOW markets

✅ **v2.1.0 (January 2026)**
- **Critical Fix**: Per-market position limit enforcement (prevents over-trading same market)
- **Critical Fix**: Outcome-determined check using NWS observations (skips trades on already-known results)
- Added outcome tracking and forecast learning system
- Added support for range temperature markets (e.g., "51-52°F")
- Improved scan completion logging

✅ **v2.0.0 (January 2026)**
- Removed all Bitcoin/crypto logic (550+ lines)
- Fixed critical bid price access bug
- Added position exit logic with take-profit/stop-loss
- Implemented portfolio caching (10s TTL)
- Migrated from print() to professional logging
- Added Kelly Criterion position sizing
- Moved all magic numbers to Config class
- Created clean startup scripts

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

<a id="license"></a>
## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## ⚠️ Disclaimer

**THIS SOFTWARE IS PROVIDED FOR EDUCATIONAL PURPOSES ONLY.**

Trading involves substantial risk of loss. This bot is experimental software and should not be used with funds you cannot afford to lose. Past performance does not guarantee future results. 

The authors and contributors:
- Make no warranties about the bot's performance
- Are not responsible for any financial losses
- Do not provide financial advice
- Recommend starting with small position sizes and thorough testing

Use at your own risk. Always understand your risk exposure and comply with applicable laws and regulations.

---

## 🙏 Acknowledgments

- [Kalshi](https://kalshi.com/) for providing the prediction market platform and API
- Weather data providers: NWS, NOAA, Open-Meteo, Tomorrow.io, Pirate Weather, Visual Crossing, Weatherbit, ECMWF, and GEFS ensemble teams
- Open source Python community

---

## 📞 Support

- **Documentation**: This README and [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- **Issues**: [GitHub Issues](https://github.com/yourusername/kalshi-trader-bot/issues)
- **Kalshi API**: [Kalshi API Docs](https://trading-api.readme.io/reference/getting-started)

---

<div align="center">

**Built with ❤️ for algorithmic weather trading**

</div>
