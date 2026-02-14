# Kalshi Weather Trading Bot

> **Production-ready automated trading system for Kalshi weather prediction markets with autonomous self-learning**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Sophisticated algorithmic trading bot that leverages multi-source weather forecasting, probability analysis, and **autonomous learning** to identify and execute profitable trades on Kalshi's daily weather markets. The bot learns from its own performance and automatically optimizes its behavior over time.

---

## Key Features

### Core Trading
- **Multi-Source Data Aggregation**: Combines forecasts from 10+ weather sources including NWS, Open-Meteo, GEFS/ECMWF ensembles (82 members total), Pirate Weather, Tomorrow.io, and more
- **Dual Trading Strategies**: Conservative edge-based trading + longshot opportunity detection
- **Smart Timing**: Longshots disabled after temperature extreme (high/low) has likely occurred
- **Hybrid Position Sizing**: Kelly Criterion for high confidence, confidence scoring for lower confidence

### Autonomous Learning (NEW)
- **Adaptive City Management**: Automatically disables cities with poor win rates (<40%)
- **Performance-Based Position Sizing**: Scales positions 0.5x-1.5x based on historical city performance
- **Persistent Learning**: Model biases, forecast errors, and city stats survive bot restarts
- **Source Reliability Tracking**: Identifies and deprioritizes unreliable forecast sources
- **Trial Re-enable**: Disabled cities re-enter trial mode after cooldown period

### Risk Management
- **Daily Loss Limits**: Bot stops trading when limit reached
- **Per-Market Caps**: Contract and dollar limits per market
- **Outcome Validation**: Skips trades on already-determined outcomes via NWS observations
- **Correlation Adjustment**: Reduces exposure when holding correlated positions

---

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Trading Strategies](#trading-strategies)
- [Adaptive Learning System](#adaptive-learning-system)
- [Risk Management](#risk-management)
- [Architecture](#architecture)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

---

## Installation

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
   git clone https://github.com/kalvintousant/kalshi-trader-bot.git
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
   python3 -c "from src.bot import KalshiTradingBot; print('Installation successful')"
   ```

---

## Configuration

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
MAX_POSITION_SIZE=10                           # Base contracts per order
MAX_CONTRACTS_PER_MARKET=15                    # Max contracts per market
MAX_DOLLARS_PER_MARKET=3.00                    # Max $ per market
MAX_DAILY_LOSS=10                              # Daily loss limit ($)
MAX_BUY_PRICE_CENTS=40                         # Never buy above 40 cents
PAPER_TRADING=true                             # Paper trade mode (no real orders)

# Strategy Parameters
MIN_EDGE_THRESHOLD=15.0               # Minimum edge percentage (%)
MIN_EV_THRESHOLD=0.05                 # Minimum expected value ($)
LONGSHOT_ENABLED=false                # Disabled until validated
LONGSHOT_MAX_PRICE=10                 # Maximum price for longshots (cents)
LONGSHOT_MIN_EDGE=30                  # Minimum edge for longshots (%)
LONGSHOT_MIN_PROB=50                  # Minimum estimated probability (%)

# Adaptive Learning
ADAPTIVE_ENABLED=true                 # Enable auto-disable of poor cities
ADAPTIVE_MIN_TRADES=10                # Min trades before evaluating
ADAPTIVE_DISABLE_WIN_RATE=0.50        # Disable if win rate < 50%
ADAPTIVE_DISABLE_HOURS=72             # How long to disable (hours)
PERSIST_LEARNING=true                 # Save learned state across restarts
MAX_SOURCE_RMSE=4.0                   # Max RMSE before marking source unreliable

# Position Sizing Enhancements
TIME_DECAY_ENABLED=true               # Reduce size far from temperature extreme
CORRELATION_ADJUSTMENT_ENABLED=true   # Reduce size when holding correlated positions
LIQUIDITY_CAP_ENABLED=true            # Don't take more than 50% of visible liquidity
EV_PROPORTIONAL_ENABLED=true          # Size proportionally to expected value

# Market Making
MARKET_MAKING_ENABLED=true            # Post limit orders at better prices
MM_MIN_SPREAD_TO_MAKE=3               # Min spread to post maker orders

# Performance
ORDERBOOK_CACHE_TTL=3                 # Seconds
PORTFOLIO_CACHE_TTL=10                # Seconds
FORECAST_CACHE_TTL=10800              # Seconds (3 hours)
```

### Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `MIN_EDGE_THRESHOLD` | Minimum edge to trigger trade | 15.0% |
| `MIN_EV_THRESHOLD` | Minimum expected value per trade | $0.05 |
| `MAX_BUY_PRICE_CENTS` | Never buy above this price | 40 |
| `PAPER_TRADING` | Paper trade mode (no real orders) | true |
| `ADAPTIVE_ENABLED` | Enable autonomous city management | true |
| `ADAPTIVE_DISABLE_WIN_RATE` | Disable city if win rate below | 50% |
| `ADAPTIVE_MIN_TRADES` | Trades before evaluating city | 10 |
| `PERSIST_LEARNING` | Save learning across restarts | true |
| `MAX_SOURCE_RMSE` | Max forecast error before unreliable | 4.0°F |

---

## Quick Start

### Recommended: Restart Script

```bash
./restart_bot.sh
```

This script:
- Stops any existing bot instances
- Clears Python bytecode cache
- Starts bot with fresh code
- Uses `caffeinate` to prevent sleep

### Background Operation

```bash
nohup ./restart_bot.sh > bot_output.log 2>&1 &
```

### Monitor Logs

```bash
tail -f bot_output.log
```

---

## Trading Strategies

### Conservative Strategy

**Criteria:**
- Edge >= 15% (scaled higher for expensive contracts)
- Expected Value >= $0.05 (after 5% fees)
- Multiple forecast sources agree

**Position Sizing:**
- Kelly Criterion (0.25 fractional) for high confidence
- Confidence scoring for lower confidence
- Scaled by time decay, correlation, and city performance

### Longshot Strategy

**Criteria:**
- Market price <= 10 cents
- Our estimated probability >= 50%
- Edge >= 30%
- Before temperature extreme has occurred

**Position Sizing:**
- Kelly Criterion (0.5 fractional) for high confidence
- Up to 5x base position for exceptional opportunities
- Scaled by same factors as conservative

### Position Exit Logic

Positions automatically exit when:
1. **Take Profit**: 30% gain from entry
2. **Edge Disappears**: Re-evaluation shows edge reversed
3. **Market Closes**: Settlement handled by Kalshi

---

## Adaptive Learning System

The bot implements autonomous self-optimization through several interconnected systems:

### 1. Adaptive City Manager

**Location:** `src/adaptive_manager.py`

Tracks per-city performance and makes real-time trading decisions:

```
City Performance Tracking:
- NY:  62% win rate (45 trades) -> 1.12x multiplier, ENABLED
- CHI: 55% win rate (38 trades) -> 1.05x multiplier, ENABLED
- DEN: 35% win rate (28 trades) -> DISABLED (24h cooldown)
- MIA: 48% win rate (12 trades) -> 1.0x multiplier (insufficient data)
```

**Features:**
- Auto-disables cities with <40% win rate after 20+ trades
- Disabled cities enter 24-hour cooldown
- After cooldown, cities re-enable for 10-trade trial period
- Trial must achieve >40% win rate or gets re-disabled

**Logs:**
```
[INFO] City DEN disabled: 35% win rate (28 trades, -$46.53 P&L)
[INFO] Will re-evaluate at 2026-02-05 10:15:00
[INFO] Re-enabling city DEN for trial period
```

### 2. Performance-Based Position Sizing

Position sizes scale based on historical city performance:

| Win Rate | Multiplier | Effect |
|----------|------------|--------|
| 60%+ | 1.1x - 1.5x | Larger positions on proven cities |
| 50% | 1.0x | Neutral (baseline) |
| 40-50% | 0.9x - 1.0x | Slightly reduced |
| <40% | DISABLED | No trading |

### 3. Persistent Learning State

**Files:**
- `data/adaptive_state.json` - City enable/disable state, win rates, P&L
- `data/learned_state.json` - Model biases, forecast error history

Learning survives bot restarts:
```
[INFO] Loaded adaptive state: 5 cities tracked
[INFO] Loaded learned state (saved at 2026-02-04T10:15:00): 42 bias corrections
```

### 4. Model Bias Correction

Learns systematic forecast biases per source/city/month:

```
Source: open_meteo_gfs
City: NY, Month: February
Historical bias: +1.2°F (model runs warm)
Correction: Subtract 1.2°F from forecasts
```

### 5. Source Reliability Tracking

Identifies unreliable forecast sources based on RMSE:

```python
# Source marked unreliable if RMSE > 4.0°F
is_source_reliable("nws", "NY")  # True (RMSE: 1.8°F)
is_source_reliable("weatherbit", "DEN")  # False (RMSE: 5.2°F)
```

---

## Risk Management

### Multi-Layer Protection

1. **Position Limits**
   - Per-market contract cap (default: 15)
   - Per-market dollar cap (default: $3.00)
   - Tracks both filled positions AND resting orders
   - Contradictory position blocker (prevents YES+NO on same market)

2. **Daily Loss Limit**
   - Stops trading if daily P&L < -$10 (configurable)
   - Tracks weather markets only (not other activity)
   - Works in both real and paper trading modes
   - Resets at midnight

3. **Drawdown Protection**
   - Progressive position reduction on consecutive losses (3/5/8/10)
   - Automatic recovery when streak breaks
   - Persists across bot restarts

4. **Settlement Tracking**
   - Tracks forecast vs actual outcome divergence per city
   - Identifies systematic forecast errors by region
   - Feeds back into adaptive city management

5. **Market Quality Filters**
   - Minimum volume: 15 contracts
   - Skips determined outcomes (NWS observation check)
   - Smart timing cutoffs (HIGH: 4PM, LOW: 8AM local)

6. **Adaptive Risk**
   - Cities with poor performance auto-disabled
   - Position sizes reduced for uncertain cities
   - Correlation adjustment for related positions

7. **API Protection**
   - Automatic retry with exponential backoff
   - Global rate limiter across all API calls
   - Cache invalidation on order changes

---

## Architecture

### Project Structure

```
kalshi-trader-bot/
├── src/
│   ├── bot.py                 # Main orchestration, trading loop
│   ├── strategies.py          # Trading strategies, position sizing
│   ├── kalshi_client.py       # Kalshi API client with caching
│   ├── weather_data.py        # Multi-source forecast aggregation
│   ├── adaptive_manager.py    # Autonomous city performance management
│   ├── outcome_tracker.py     # Settlement tracking, learning updates
│   ├── drawdown_protector.py  # Progressive drawdown protection
│   ├── settlement_tracker.py  # Forecast vs outcome divergence tracking
│   ├── dashboard.py           # Live console dashboard (color-coded)
│   ├── market_maker.py        # Limit order posting, requoting
│   ├── portfolio_risk.py      # Correlation-aware risk management
│   ├── config.py              # Configuration management
│   └── logger.py              # Structured logging
├── data/
│   ├── adaptive_state.json    # City performance state (auto-generated)
│   ├── learned_state.json     # Model biases, errors (auto-generated)
│   ├── outcomes.csv           # Trade outcome history (real mode)
│   ├── paper_outcomes.csv     # Trade outcome history (paper mode)
│   └── source_forecasts.csv   # Per-source forecast log
├── tools/                     # 13 diagnostic/analysis scripts
├── restart_bot.sh             # Production restart script
├── clean_start.sh             # Fresh start with cache clear
├── .env                       # Environment variables (not in repo)
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

### Key Components

#### Bot (`src/bot.py`)
- Main trading loop with 30-second scan interval
- Coordinates strategies, outcome tracking, adaptive manager
- Daily P&L tracking (weather markets only)
- Heartbeat logging every 30 minutes

#### Strategies (`src/strategies.py`)
- `WeatherDailyStrategy`: Main weather market strategy
- Dual-mode: Conservative + Longshot
- Integrates adaptive manager for city enable/disable checks
- Position sizing with time decay, correlation, and adaptive multipliers

#### Adaptive Manager (`src/adaptive_manager.py`)
- Tracks win/loss/P&L per city
- Auto-disables poor performers
- Trial mode for re-enabled cities
- Persists state to JSON

#### Weather Data (`src/weather_data.py`)
- 10+ forecast sources with parallel fetching
- Ensemble-based uncertainty (GEFS + ECMWF = 82 members)
- Model-specific bias correction
- Source reliability tracking
- Persistent learning state

#### Outcome Tracker (`src/outcome_tracker.py`)
- Processes settled positions from Kalshi API
- Updates forecast model with actual temperatures
- Triggers adaptive manager updates
- Returns settlement results to dashboard for live P&L tracking
- Generates performance reports

#### Dashboard (`src/dashboard.py`)
- Live console dashboard with color-coded output
- Real-time P&L, win/loss, and per-city stats
- Trade and settlement event feed
- Scan metrics and strategy status
- Paper mode indicator and persistence across restarts

#### Drawdown Protector (`src/drawdown_protector.py`)
- Progressive position reduction on consecutive losses
- Four loss levels: 3, 5, 8, 10 consecutive losses
- Automatic recovery and multiplier adjustment

#### Settlement Tracker (`src/settlement_tracker.py`)
- Forecast vs outcome divergence tracking per city
- Identifies systematic regional forecast errors

---

## Monitoring

### Real-Time Logs

```bash
# Main activity
tail -f bot_output.log

# Recent trades
tail -20 data/trades.csv

# Adaptive state
cat data/adaptive_state.json | python3 -m json.tool
```

### Key Log Messages

```bash
# Startup - Adaptive learning active
[INFO] AdaptiveCityManager initialized: 5 cities tracked
[INFO] Adaptive city management ENABLED

# City disabled
[INFO] City DEN disabled: 35% win rate (28 trades, -$46.53 P&L)

# Trade skipped due to disabled city
[INFO] SKIP KXHIGHDEN-26FEB04-T45: city DEN adaptively disabled

# Position sizing with adaptive multiplier
[DEBUG] Adaptive multiplier: 1.15x, adjusted position=12

# Learning state saved
[DEBUG] Saved learned state to data/learned_state.json
```

### Health Checks

```bash
# Bot running?
ps aux | grep "python.*bot" | grep -v grep

# Recent activity?
tail -1 bot_output.log

# Heartbeat (every 30 min)
grep "Heartbeat" bot_output.log | tail -1
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Bot won't start | Stale bytecode | Run `./restart_bot.sh` |
| `ModuleNotFoundError` | Python path | Use `PYTHONPATH=.` |
| No trades | All cities disabled | Check `data/adaptive_state.json` |
| City stuck disabled | Win rate too low | Wait for cooldown or reset state |

### Reset Adaptive State

To re-enable all cities and start fresh:

```bash
rm data/adaptive_state.json
./restart_bot.sh
```

### Reset All Learning

To clear all learned data:

```bash
rm data/adaptive_state.json data/learned_state.json
./restart_bot.sh
```

### Debug Mode

```bash
export LOG_LEVEL=DEBUG
./restart_bot.sh
```

---

## Development

### Recent Changes

**v2.6.0 (February 2026)** - Safety Systems & Dashboard
- Live console dashboard with P&L, W/L, per-city stats
- Paper trading mode with full P&L tracking and settlement recovery
- Drawdown protector with progressive loss levels
- Settlement tracker for forecast divergence analysis
- Contradictory position blocker
- Tightened thresholds: edge 15%, EV $0.05, max buy 40c
- Global API rate limiter
- Denver disabled due to poor forecast accuracy

**v2.5.0 (February 2026)** - Autonomous Learning
- Adaptive City Manager with auto-disable/enable
- Performance-based position sizing (0.5x-1.5x)
- Persistent learning state across restarts
- Source reliability tracking based on RMSE
- Trial mode for re-enabled cities

**v2.4.0 (January 2026)** - Weather Data Expansion
- Added 7 new weather data sources
- Ensemble-based uncertainty (82 members)
- Model-specific bias correction
- Parallel forecast fetching

**v2.3.0 (January 2026)** - Hybrid Position Sizing
- Kelly Criterion for high confidence
- Confidence scoring for lower confidence
- Determined outcome exclusion

**v2.2.0 (January 2026)** - Smart Timing
- Longshot timing cutoffs
- LOW temperature market support
- NWS observation tracking

### Testing

```bash
# Test adaptive manager
python3 -c "
from src.adaptive_manager import AdaptiveCityManager
am = AdaptiveCityManager('data/test.json')
am.record_outcome('NY', True, 0.50)
print(am.get_city_stats('NY'))
import os; os.remove('data/test.json')
"

# Test weather data with persistence
python3 -c "
from src.weather_data import WeatherDataAggregator
w = WeatherDataAggregator()
print('Loaded learned state successfully')
"
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Disclaimer

**THIS SOFTWARE IS PROVIDED FOR EDUCATIONAL PURPOSES ONLY.**

Trading involves substantial risk of loss. This bot is experimental software and should not be used with funds you cannot afford to lose. Past performance does not guarantee future results.

The authors and contributors:
- Make no warranties about the bot's performance
- Are not responsible for any financial losses
- Do not provide financial advice
- Recommend starting with small position sizes and thorough testing

Use at your own risk.

---

## Acknowledgments

- [Kalshi](https://kalshi.com/) for the prediction market platform
- Weather data providers: NWS, NOAA, Open-Meteo, ECMWF, GEFS, Pirate Weather, Tomorrow.io, Visual Crossing, Weatherbit
- Open source Python community

---

<div align="center">

**Built with autonomous learning for algorithmic weather trading**

</div>
