# Running the Weather Trader Bot

## Start (kills any existing bot first)

```bash
cd "/Users/kalvintousant/Documents/Cursor Projects/Weather Trader Bot" && pkill -f "bot\.py" 2>/dev/null; sleep 1 && caffeinate -i env PYTHONPATH=. python3 -B -u src/bot.py
```

## Start in background (with log file)

```bash
cd "/Users/kalvintousant/Documents/Cursor Projects/Weather Trader Bot" && pkill -f "bot\.py" 2>/dev/null; sleep 1 && nohup caffeinate -i env PYTHONPATH=. python3 -B -u src/bot.py > bot_output.log 2>&1 &
```

## Monitor

```bash
# Watch live log
tail -f bot.log

# Filter for key events
tail -f bot.log | grep -E "Trade executed|OBSERVATION|Cross-threshold|CONTRADICTORY|DRAWDOWN"

# Watch background output
tail -f bot_output.log
```

## Web Dashboard

Open `http://localhost:8050` after starting the bot (enabled by default via `WEB_DASHBOARD_ENABLED=true` in `.env`).

Charts: cumulative P&L, daily P&L, city performance. Live event feed via SSE. Account stats, positions, recent trades.

```bash
# Remote access via ngrok
ngrok http 8050
```

Config env vars:
- `WEB_DASHBOARD_ENABLED` — `true`/`false` (default: `false`)
- `WEB_DASHBOARD_HOST` — bind address (default: `0.0.0.0`)
- `WEB_DASHBOARD_PORT` — port (default: `8050`)

## Stop

```bash
pkill -f "bot\.py"
```

## Analysis tools

```bash
python3 tools/performance_dashboard.py      # Full performance report
python3 tools/check_exposure.py             # Current positions and exposure
python3 tools/review_trades_today.py        # Today's trades
python3 tools/analyze_forecast_accuracy.py  # Forecast accuracy by source
python3 tools/analyze_data_sources.py       # Data source reliability
python3 tools/view_performance.py           # Historical performance
```
