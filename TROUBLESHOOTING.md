# Bot Troubleshooting Guide

## Issue: Bot won't start - TypeError about object.__init__()

### Symptoms
- Error message: `TypeError: object.__init__() takes exactly one argument`
- Error references line numbers that don't exist in the file (e.g., line 1193 when file only has 783 lines)

### Root Cause
Python is using **cached bytecode** (`.pyc` files) from an old version of the code. Even after fixing the code, Python continues to use the stale cached version.

### Solution

#### Option 1: Use the Clean Start Script (RECOMMENDED)
```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
./clean_start.sh
```

This script:
- Stops any running bot
- Clears ALL Python cache
- Removes old logs
- Starts bot with fresh Python environment
- Shows status and log output

#### Option 2: Manual Clean Start
If you prefer to do it manually:

```bash
# 1. Stop existing bot
pkill -9 -f "python.*bot"

# 2. Clear ALL cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null
rm -rf src/__pycache__

# 3. Start with clean environment
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
export PYTHONDONTWRITEBYTECODE=1
python3 -B -u src/bot.py > bot_output.log 2>&1 &

# 4. Check log
tail -f bot_output.log
```

#### Option 3: Close Terminal & Start Fresh
Sometimes Python modules are cached in memory. The most reliable fix:

1. **Close ALL terminal windows**
2. **Open a NEW terminal**
3. **Run the clean_start.sh script**

This ensures Python starts completely fresh with no cached modules in memory.

## Verification

The bot is working correctly when you see in the log:
```
Starting Kalshi Trading Bot...
Scanning markets...
```

## Monitoring Commands

```bash
# Watch live log
tail -f bot_output.log

# Check if bot is running
ps aux | grep "[p]ython.*bot"

# View trades
cat trades.log

# Stop bot
pkill -f bot.py
```

## Understanding the Fix

The original code had `TradingStrategy` (base class) calling `super().__init__(client)`, which tried to pass an argument to `object.__init__()` (which doesn't accept arguments).

**Fixed code** (line 16-19 in `src/strategies.py`):
```python
def __init__(self, client: KalshiClient):
    # Don't call super() - this is the base class
    self.client = client
    self.name = self.__class__.__name__
```

The fix is correct - it's just a matter of forcing Python to reload the updated file by clearing all caches.
