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
- **Advanced Forecast Accuracy**:
  - Multi-source aggregation (NWS, Tomorrow.io, Weatherbit) with reliability weighting
  - Outlier detection filters bad forecasts automatically
  - Forecast age weighting (recent forecasts weighted more heavily)
  - Dynamic standard deviation based on forecast agreement and time horizon
  - Historical forecast error tracking for adaptive learning
  - Confidence intervals via bootstrap sampling (only trades when high confidence)
- **Enhanced EV Calculation**:
  - Includes Kalshi transaction fees (5% on winnings) for realistic EV
  - Market depth/slippage estimation for accurate fill prices
  - Kelly Criterion for optimal position sizing (long-term growth)
- **24/7 Operation**: Runs continuously to monitor both high and low temperature markets (low temps occur early morning)
- **Contract Compliance**: All locations verified against NWS official weather station coordinates
- **Smart Date Handling**: Correctly identifies today vs tomorrow markets and uses appropriate forecasts
- **Risk Management**: 
  - $10 daily loss limit (tracks total portfolio P&L: cash + positions, trading pauses if reached)
  - $3 OR 25 contracts max per market (whichever is hit first)
  - Automatic order cancellation when edge/EV no longer valid
  - Position sizing controls with Kelly Criterion optimization
- **Market Coverage**: NYC, Chicago, Miami, Austin, Los Angeles, Denver (high & low temp markets)
- **Real-Time Monitoring**: 30-second Kalshi odds checks (weather forecasts cached 30 min)
- **Smart Notifications**: Only notify when orders actually fill (not when placed)
- **API Optimization**: All weather APIs within free tier limits (NWS unlimited, Tomorrow.io 500/day, Weatherbit 50/day as emergency fallback)

## Documentation

- **Setup**: See `docs/setup/` for installation and scheduling
- **Strategies**: See `docs/strategies/` for trading logic and forecast/EV improvements
- **Optimization**: See `docs/optimization/` for performance details and API usage

## Forecast & EV Accuracy Improvements

The bot implements 12 advanced improvements for forecast and EV accuracy:

**Phase 1 (Quick Wins)**:
- Transaction costs included in EV (5% Kalshi fees)
- Outlier detection (IQR method)
- Forecast age weighting (6-hour half-life)

**Phase 2 (Medium-Term)**:
- Source reliability weighting (NWS 1.0, Tomorrow.io 0.9, Weatherbit 0.8)
- Dynamic standard deviation (based on forecast agreement and time horizon)
- Historical forecast error tracking (adaptive learning per city/month)

**Phase 3 (Advanced)**:
- Confidence intervals (bootstrap sampling, 95% CI)
- Market depth/slippage estimation
- Kelly Criterion for optimal position sizing

**Expected Impact**: +30-50% forecast accuracy, +40-60% EV accuracy

See `docs/strategies/forecast_ev_improvements.md` and `docs/strategies/implementation_summary.md` for details.

## Disclaimer

**This software is for educational and research purposes only.**

- Trading involves substantial risk of loss
- Past performance does not guarantee future results
- Users are responsible for compliance with all applicable laws and exchange terms
- The authors are not responsible for any trading losses

## License

Private repository - All rights reserved.
