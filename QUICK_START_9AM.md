# Quick Start Guide - 9 AM

## If Laptop Was AWAKE All Night

✅ Bot should already be running (started automatically at 6am)

**Check status:**
```bash
ps aux | grep bot.py
```

**View what happened:**
```bash
tail -20 bot_output.log
```

**View trades:**
```bash
cat trades.log
```

**No action needed!** Bot is already trading.

---

## If Laptop Was SLEEPING

⚠️ Bot did NOT start automatically (cron doesn't run when sleeping)

**Start bot now:**
```bash
./start_daytime.sh
```

**Verify it started:**
```bash
ps aux | grep bot.py
tail -f bot_output.log
```

**That's it!** Bot will run until 10pm.

---

## Quick Commands Reference

```bash
# Check if bot is running
ps aux | grep bot.py

# Watch live output
tail -f bot_output.log

# View trades
cat trades.log

# Stop bot (if needed)
pkill -f bot.py

# Restart bot
./start_daytime.sh
```

---

## What to Expect

**Bot will:**
- Scan markets every 30 minutes
- Hunt for longshot opportunities (3x position)
- Take conservative trades (1x position)
- Log heartbeat every 30 minutes
- Stop automatically at 10pm

**You'll see:**
- Market scans in `bot_output.log`
- Trade notifications (console + file + popup)
- Heartbeat status every 30 min
- Balance updates

---

## Troubleshooting

**Bot not running?**
```bash
./start_daytime.sh
```

**No trades yet?**
- Normal! Bot only trades when edge ≥ 5% (conservative) or ≥ 30% (longshot)
- Check logs: `tail -f bot_output.log`
- Bot is scanning and evaluating markets

**Want to see what markets bot found?**
```bash
grep "Found.*markets" bot_output.log | tail -5
```

---

## Summary

**9 AM Checklist:**
1. Wake up laptop (if sleeping)
2. Run `./start_daytime.sh` (if laptop was sleeping)
3. Check `tail -f bot_output.log` to see activity
4. Go about your day! Bot will trade automatically.

**That's it!** 🚀
