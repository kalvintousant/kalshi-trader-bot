# Laptop Setup - Screen Sleep, Computer Awake

## Your Setup ✅

- **Laptop**: Open and plugged in
- **Screen**: Can sleep (saves power)
- **Computer**: Stays awake

## What Happens

✅ **Cron jobs WILL run** (computer is awake)
✅ **Bot WILL auto-start at 6:00 AM**
✅ **Bot WILL keep running all day**
✅ **Screen sleep doesn't affect bot**

## Verification

**Check if computer is set to stay awake:**
1. System Settings → Battery
2. When plugged in, ensure:
   - "Prevent automatic sleeping" is enabled
   - Computer doesn't sleep when plugged in

**Default behavior:**
- Most Macs stay awake when plugged in
- Screen can sleep (doesn't affect cron)
- Cron jobs run normally

## Tomorrow at 9 AM

**Bot will ALREADY be running** (started at 6am)

**Just check:**
```bash
ps aux | grep bot.py
tail -f bot_output.log
```

**No action needed!** Bot is already trading.

## Troubleshooting

**If bot didn't start at 6am:**
- Check cron logs: `tail -f cron.log`
- Verify cron is running: `crontab -l`
- Manually start: `./start_daytime.sh`

**To ensure computer stays awake:**
- System Settings → Battery → Options
- Uncheck "Put hard disks to sleep when possible"
- Enable "Prevent automatic sleeping" when plugged in

## Summary

Your setup is perfect! Screen can sleep, computer stays awake, cron runs, bot starts automatically. 🚀
