# 24/7 Operation - Weather Bot

## Why 24/7 Operation?

Weather markets require **continuous monitoring** because:

### Low Temperature Markets
- **Low temperatures occur early morning** (typically 4-7 AM local time)
- NWS Daily Climate Report covers **12:00 AM - 11:59 PM** (full calendar day)
- Must monitor overnight to catch low temp opportunities
- Markets can settle based on minimum temperature reached during the night/early morning

### High Temperature Markets
- **High temperatures occur afternoon** (typically 2-5 PM local time)
- Still need monitoring throughout the day
- Markets settle based on maximum temperature during the full day

### Market Settlement
- Kalshi uses NWS Daily Climate Report data
- Statistical period: **12:00 AM to 11:59 PM Local Standard Time**
- Settlement occurs after data is released (typically 3+ hours after period ends)
- Trading can happen throughout the entire 24-hour period

---

## Setup

### Automatic Startup (Recommended)

The bot is configured to start automatically on system reboot:

```bash
# Check cron jobs
crontab -l

# Should see:
# @reboot /path/to/scripts/start_bot.sh
```

### Manual Startup

```bash
# Start bot (24/7 mode)
./scripts/start_bot.sh
```

### Manual Stop

```bash
# Stop bot
pkill -f "python.*bot.py"
```

---

## Monitoring

### Check Status
```bash
# Is bot running?
ps aux | grep bot.py

# View live output
tail -f bot_output.log

# View trades
cat trades.log
```

### Heartbeat
- Bot logs heartbeat every 30 minutes
- Shows: running time, balance, daily P&L
- Confirms bot is alive and functioning

---

## Benefits of 24/7 Operation

### Complete Coverage
- ✅ Catches low temp opportunities (early morning)
- ✅ Catches high temp opportunities (afternoon)
- ✅ Monitors all market movements throughout the day
- ✅ No missed opportunities due to timing

### Market Dynamics
- Markets can move at any time based on:
  - Forecast updates (NWS, Tomorrow.io, Weatherbit)
  - Market repricing as new information arrives
  - Settlement approaching (increased activity)

---

## System Requirements

### Laptop Setup
- **Keep laptop plugged in** (prevents battery drain)
- **Screen can sleep** (bot runs in background)
- **System must stay awake** (use `caffeinate -i` in script)
- **Network connection required** (for API calls)

### Power Management
The `start_bot.sh` script uses:
- `nohup` - Survives terminal close
- `caffeinate -i` - Prevents Mac from sleeping
- Background execution - Doesn't block terminal

---

## Troubleshooting

### Bot Not Starting
```bash
# Check if cron job exists
crontab -l

# Check cron logs
tail -f cron.log

# Manually start
./scripts/start_bot.sh
```

### Bot Stopped Unexpectedly
```bash
# Check logs for errors
tail -100 bot_output.log

# Restart manually
./scripts/start_bot.sh
```

### System Sleep Issues
- Ensure laptop is plugged in
- Check System Preferences > Energy Saver
- Script uses `caffeinate -i` to prevent sleep
- If issues persist, disable sleep entirely for trading machine

---

## Current Status

**Mode:** 24/7 Continuous Operation
**Auto-start:** Enabled via cron (@reboot)
**Monitoring:** Heartbeat every 30 minutes
**Coverage:** Full 24-hour period for all temperature markets
