# CLAUDE.md

## Project

Kalshi Weather Trading Bot — a Python bot that trades Kalshi daily high/low temperature prediction markets by aggregating 10+ weather forecast sources, computing probability distributions, and autonomously placing trades when edge and expected value thresholds are met.

## Stack

- **Language**: Python 3.9+
- **Runtime**: CPython
- **Package manager**: pip
- **Dependencies**: requests, websockets, cryptography, python-dotenv, aiohttp, numpy, scipy (intentionally minimal)
- **Formatter**: Black

## Commands

```bash
# Run
./restart_bot.sh                                        # Recommended (clears cache, prevents zombies)
caffeinate -i env PYTHONPATH=. python3 -B -u src/bot.py # Manual start
./clean_start.sh                                        # Fresh start with full cache clear
nohup ./restart_bot.sh > bot_output.log 2>&1 &          # Background operation

# Analysis
python3 tools/performance_dashboard.py    # Comprehensive performance analytics
python3 tools/check_exposure.py           # Current positions and exposure
python3 tools/review_trades_today.py      # Today's trades
python3 tools/analyze_forecast_accuracy.py # Forecast accuracy by source
python3 tools/analyze_data_sources.py     # Data source reliability
python3 tools/view_performance.py         # Historical performance
```

## Code Style

- Python 3.9+, formatted with Black, no type checker or build step
- Classes for stateful components (strategies, managers, trackers)
- Config via environment variables with defaults in `src/config.py` (150+ parameters)
- File-based persistence (CSV for outcomes, JSON for state/learning, SQLite for history)
- Prices in cents for Kalshi contracts, temperatures in Fahrenheit

## Structure

```
src/
  bot.py              # Main orchestration, trading loop (30s scan interval)
  strategies.py       # Trading strategies, position sizing, edge/EV calculation (~111KB)
  kalshi_client.py    # Kalshi API client with caching and rate limiting
  weather_data.py     # Multi-source forecast aggregation (10+ APIs, 82 ensemble members, ~92KB)
  adaptive_manager.py # Autonomous city performance management (auto-disable/enable)
  outcome_tracker.py  # Settlement tracking, learning updates
  market_maker.py     # Limit order posting, requoting
  portfolio_risk.py   # Correlation-aware risk management
  forecast_weighting.py # Dynamic forecast accuracy tracking
  attribution.py      # Performance attribution engine
  backtester.py       # Backtesting framework
  dashboard.py        # Console UI output (color-coded)
  logger.py           # Structured logging (rotating file handler)
  config.py           # Configuration management (env vars → defaults)

tools/                # 13 diagnostic/analysis scripts (standalone, read from data/ and Kalshi API)
scripts/              # Startup scripts (start_bot.sh, setup_schedule.sh)
data/                 # Generated at runtime: outcomes.csv, adaptive_state.json, learned_state.json, *.db
docs/                 # Strategy, setup, and optimization documentation
```

## Architecture

- **Config** (`src/config.py`): All trading parameters load from environment variables with sensible defaults. This is the single source of truth for thresholds, limits, and feature flags.
- **Weather data** (`src/weather_data.py`): Aggregates 10+ forecast sources in parallel via ThreadPoolExecutor. Builds normal probability distributions over 2°F temperature bins. Ensemble-based uncertainty from 82 members (GEFS 31 + ECMWF 51). Applies per-model, per-city bias correction learned from outcomes.
- **Strategies** (`src/strategies.py`): Two modes — Conservative (edge ≥ 8%, EV ≥ $0.01, Kelly 0.25x) and Longshot (price ≤ 10¢, probability ≥ 50%, edge ≥ 30%, Kelly 0.5x). Position sizing factors in time decay, correlation, liquidity, and adaptive city multipliers.
- **Adaptive manager** (`src/adaptive_manager.py`): Auto-disables cities with <40% win rate after 20+ trades. 24h cooldown, trial mode re-enabling. Persistent state in `data/adaptive_state.json`.
- **Data directories**: All runtime data lives in `data/` — outcomes, adaptive state, learned biases, SQLite databases. Never mix with source code.

## Key Domain Concepts

- **Kalshi weather markets**: Settle daily on whether a city's high/low temperature is above/below a threshold. Uses NWS official observations.
- **Contract prices**: Expressed in cents (1-99). A 92c YES contract pays $1.00 if correct — 8c profit on 92c risk.
- **Market format**: `KXHIGHNY-26FEB04-B75.5` (series-date-threshold). HIGH = daily max, LOW = daily min.
- **Active cities**: NY, CHI, MIA, AUS, LAX. Denver is disabled (poor forecast accuracy, 19% win rate).
- **Smart timing**: HIGH markets disabled after 4 PM local (high already occurred), LOW after 8 AM local.
- **Forecast caching**: 3-hour TTL to stay within free-tier API limits across all sources.

## Workflow

1. **Plan first.** Before writing code, outline the approach. If the task touches 3+ files, create a brief plan and get confirmation before proceeding.
2. **Read before editing.** Always read the full relevant section of a file before modifying it. `strategies.py` and `weather_data.py` are large — understand the surrounding context.
3. **Trace data flow end-to-end.** When fixing a function, follow its outputs through every downstream consumer. Don't stop at the function you edited — trace through strategies → risk checks → order placement → outcome tracking.
4. **Make minimal changes.** Change only what's necessary. Don't refactor unrelated code.
5. **Review after implementing.** Re-read finished code and trace through it before marking done. Catch bugs like wrong temperature units, inverted comparisons, or broken cache invalidation.
6. **Proactively flag adjacent bugs.** If you see a problem while working nearby, call it out immediately.

## Safety

- **Never place real Kalshi orders** without verifying the trading logic through backtester or demo environment first
- **Never modify `data/outcomes.csv`** — this is an append-only trade log from real Kalshi API data
- **Never commit `.env` or `*.pem` files** — these contain API keys and private keys
- **Never change risk limits** (MAX_DAILY_LOSS, MAX_CONTRACTS_PER_MARKET, MAX_DOLLARS_PER_MARKET, circuit breaker thresholds) without explicit approval
- **Never disable safety features** (daily loss limit, position limits, exposure tracking, adaptive disabling) without explicit approval
- **Never modify adaptive_state.json or learned_state.json manually** — these are maintained by the bot's learning system
- **Test parameter changes** in the backtester or demo environment before applying to production

## Don'ts

- Don't add new pip dependencies without asking first — the bot is intentionally minimal (7 deps)
- Don't introduce type checkers, build steps, or additional frameworks
- Don't add test frameworks — the bot is validated through backtesting, paper trading on demo API, and analysis scripts
- Don't auto-generate a README unless asked
- Don't modify the dashboard rendering in `dashboard.py` unless specifically asked (it's styled to match the Crypto Trader Bot)
- Don't modify `bot.py` main loop timing or scan interval without asking — it affects rate limiting and API costs

## Additional Context

See `README.md` for how the bot works and performance stats.
See `src/config.py` for all trading limits and thresholds.
See `.env.example` for environment variable configuration.
See `docs/` for strategy documentation, setup guides, and optimization notes.
