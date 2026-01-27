# Project Structure

## Directory Layout

```
kalshi-trader-bot/
├── src/                          # Core application code
│   ├── __init__.py              # Package marker
│   ├── bot.py                   # Main bot orchestrator
│   ├── strategies.py            # Trading strategies (weather)
│   ├── kalshi_client.py         # Kalshi API client
│   ├── weather_data.py          # Multi-source weather aggregation
│   └── config.py                # Configuration management
│
├── scripts/                      # Utility scripts
│   ├── start_daytime.sh         # Daytime startup (6am-10pm)
│   ├── start_bot.sh             # 24/7 startup
│   └── setup_schedule.sh        # Cron setup guide
│
├── docs/                         # Documentation
│   ├── strategies/              # Strategy documentation
│   │   ├── weather_strategy.md
│   │   ├── longshot_strategy.md
│   │   └── improvements.md
│   ├── setup/                   # Setup guides
│   │   ├── daytime_schedule.md
│   │   ├── laptop_setup.md
│   │   └── quick_start.md
│   └── optimization/            # Optimization docs
│       ├── weather_optimization.md
│       ├── performance.md
│       └── final_optimization.md
│
├── .env.example                 # Environment template
├── requirements.txt             # Python dependencies
├── README.md                    # Main documentation
└── .gitignore                   # Git ignore rules
```

## File Organization Principles

1. **Separation of Concerns**: Code, scripts, and docs are separated
2. **Standard Python Structure**: `src/` for application code
3. **Logical Grouping**: Documentation organized by purpose
4. **Clean Root**: Only essential files at root level

## Running the Bot

From project root:
```bash
python3 src/bot.py
```

Or use scripts:
```bash
./scripts/start_daytime.sh
```
