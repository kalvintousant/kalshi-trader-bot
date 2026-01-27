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
- **Contract Compliance**: All locations verified against NWS official weather station coordinates
- **Risk Management**: 
  - $10 daily loss limit (trading pauses if reached)
  - 25 contracts max per market ($0.25 max exposure per market)
  - Position sizing controls
- **Market Coverage**: NYC, Chicago, Miami, Austin, Los Angeles (high & low temp markets)
- **Real-Time Monitoring**: 30-second Kalshi odds checks (weather forecasts cached 30 min)

## Documentation

- **Setup**: See `docs/setup/` for installation and scheduling
- **Strategies**: See `docs/strategies/` for trading logic
- **Optimization**: See `docs/optimization/` for performance details

## Disclaimer

**This software is for educational and research purposes only.**

- Trading involves substantial risk of loss
- Past performance does not guarantee future results
- Users are responsible for compliance with all applicable laws and exchange terms
- The authors are not responsible for any trading losses

## License

Private repository - All rights reserved.
