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

- **🌦️ Weather Markets Only**: Specialized focus on daily weather prediction markets
- **📊 Multi-Source Data Aggregation**: Combines forecasts from NWS, Tomorrow.io, and Weatherbit
- **🎲 Dual Trading Strategies**:
  - **Conservative**: High-confidence trades with >5% edge and positive EV
  - **Longshot**: Undervalued low-probability events (≤10¢, ≥50% estimated probability, ≥30% edge)
- **💰 Position Management**: Automatic exit logic with take-profit (20%), stop-loss (30%), and edge monitoring
- **📈 Kelly Criterion Sizing**: Intelligent position sizing for high-confidence trades
- **🔒 Risk Controls**: Daily loss limits, position caps, and per-market exposure tracking (prevents over-trading)
- **✅ Outcome Validation**: Checks NWS observations to skip trades on already-determined outcomes
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

## 🚀 Installation

### Prerequisites

- **Python 3.9+**
- **macOS** (tested on macOS 12+)
- **Kalshi API Credentials** ([Get API keys](https://kalshi.com/))
- **Weather API Keys**:
  - [Tomorrow.io API](https://www.tomorrow.io/) (optional)
  - [Weatherbit API](https://www.weatherbit.io/) (optional)

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

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# Kalshi API (Required)
KALSHI_EMAIL=your-email@example.com
KALSHI_PASSWORD=your-password
KALSHI_API_BASE=https://trading-api.kalshi.com/trade-api/v2

# Weather APIs (At least one recommended)
TOMORROW_API_KEY=your-tomorrow-api-key       # Optional
WEATHERBIT_API_KEY=your-weatherbit-api-key   # Optional

# Trading Configuration
ENABLED_STRATEGIES=weather_daily
MAX_POSITION_SIZE=10
MAX_DAILY_LOSS=500

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
| `MAX_DOLLARS_PER_MARKET` | Hard cap on dollars per market | $300 | $100-$500 |
| `MAX_DAILY_LOSS` | Daily loss limit (bot stops trading) | $500 | $200-$1000 |
| `LONGSHOT_MAX_PRICE` | Max price to consider longshot | 10¢ | 5-15¢ |
| `LONGSHOT_MIN_EDGE` | Min edge for longshot trades | 30% | 25-40% |

---

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

## 🎯 Trading Strategies

### Conservative Strategy

**Criteria:**
- Edge ≥ 5%
- Expected Value ≥ $0.01 (after fees)
- High confidence (multiple sources agree)

**Position Sizing:**
- Kelly Criterion for high-confidence trades (>70% probability, 2+ sources)
- Standard position size otherwise
- Capped at MIN(MAX_CONTRACTS_PER_MARKET, MAX_DOLLARS_PER_MARKET / price)

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

**Position Sizing:**
- 1.5x standard position size (higher upside justifies risk)
- Capped at position limits

**Example:**
```
Market: "Will Boston get >8 inches of snow tomorrow?"
Our Probability: 60% (unusual storm pattern detected)
Market Price: 8¢ (implies 8% probability)
Edge: 52% → TRADE YES (Longshot)
Position: 22 contracts @ 8¢ = $1.76 risk
Potential Profit: 22 × (100¢ - 8¢) = $20.24 (+1150%)
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

## 🛡️ Risk Management

### Multi-Layer Protection

1. **Position Limits**
   - Per-market contract cap: 25 contracts (tracks filled + resting orders)
   - Per-market dollar cap: $300 (tracks total exposure per market)
   - Max position size: 10 contracts (base)
   - **Per-Market Exposure Tracking**: Bot checks existing positions and resting orders before each trade to prevent exceeding limits across multiple orders

2. **Daily Loss Limit**
   - Bot automatically stops trading if daily P&L < -$500
   - Resets at midnight
   - Sends notification on limit hit

3. **Market Quality Filters**
   - Minimum volume: 50 contracts
   - Only trades "open" status markets
   - Excludes markets expiring in <24 hours
   - **Outcome-Determined Check**: For today's markets, checks NWS observed high temperature and skips trades if outcome is already certain (prevents trading on predetermined results)

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
- Multi-source API integration (NWS, Tomorrow.io, Weatherbit)
- Probability distribution modeling
- Outlier detection
- Source weighting by age and reliability
- Confidence interval calculation

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
- Weather data providers: NWS, Tomorrow.io, Weatherbit
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
