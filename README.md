# Kalshi Weather Trading Bot

Automated trading bot for Kalshi **daily weather markets** using advanced multi-source forecast aggregation and dual-strategy approach (longshot + conservative).

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Start bot (24/7 operation - required for low temp markets that occur early morning)
./scripts/start_bot.sh

# Bot will auto-start on system reboot via cron (@reboot)
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
- **24/7 Operation**: Runs continuously to monitor both high and low temperature markets (low temps occur early morning)
- **Contract Compliance**: All locations verified against NWS official weather station coordinates
- **Risk Management**: 
  - $10 daily loss limit (trading pauses if reached)
  - $3 OR 25 contracts max per market (whichever is hit first)
  - Automatic order cancellation when edge/EV no longer valid
  - Position sizing controls
- **Market Coverage**: NYC, Chicago, Miami, Austin, Los Angeles (high & low temp markets)
- **Real-Time Monitoring**: 30-second Kalshi odds checks (weather forecasts cached 30 min)
- **Smart Notifications**: Only notify when orders actually fill (not when placed)
- **API Optimization**: All weather APIs within free tier limits (NWS unlimited, Tomorrow.io 500/day, Weatherbit 50/day as emergency fallback)

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
