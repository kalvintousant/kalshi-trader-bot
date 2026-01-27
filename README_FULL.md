# Kalshi Weather Trading Bot

Automated trading bot for Kalshi **daily weather markets** using advanced multi-source forecast aggregation and dual-strategy approach (longshot + conservative).

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Start bot (daytime schedule: 6am-10pm)
./scripts/start_daytime.sh
```

## Project Structure

```
kalshi-trader-bot/
├── src/                    # Core application code
│   ├── bot.py             # Main bot orchestrator
│   ├── strategies.py      # Trading strategies
│   ├── kalshi_client.py   # Kalshi API client
│   ├── weather_data.py    # Weather forecast aggregation
│   └── config.py          # Configuration management
├── scripts/                # Utility scripts
│   ├── start_daytime.sh   # Daytime startup (6am-10pm)
│   ├── start_bot.sh       # 24/7 startup
│   └── setup_schedule.sh  # Cron setup guide
├── docs/                   # Documentation
│   ├── strategies/        # Strategy documentation
│   ├── setup/             # Setup guides
│   └── optimization/      # Optimization docs
├── .env.example           # Environment template
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Features

- **Dual Strategy**: Longshot mode (asymmetric payouts) + Conservative mode (steady gains)
- **Multi-Source Forecasts**: Aggregates from NWS, Tomorrow.io, and Weatherbit
- **Automatic Scheduling**: Runs 6am-10pm via cron (optimal for weather markets)
- **Contract Compliance**: Optimized for all weather contract rules
- **Risk Management**: Daily loss limits and position sizing controls

## Documentation

- **Setup**: See `docs/setup/` for installation and scheduling
- **Strategies**: See `docs/strategies/` for trading logic
- **Optimization**: See `docs/optimization/` for performance details

## License

Private repository - All rights reserved.
