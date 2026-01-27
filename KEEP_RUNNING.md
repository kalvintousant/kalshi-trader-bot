# Keeping the Bot Running Overnight

## ⚠️ Important: Laptop Sleep Will Stop the Bot

If your laptop goes to sleep, the bot process will pause and stop trading.

## Solutions

### Option 1: Prevent Sleep (Recommended for Testing)

**macOS Settings:**
1. System Settings → Battery → Options
2. Set "Prevent automatic sleeping when display is off" to ON
3. Or set "Turn display off after" to Never

**Or use caffeinate command:**
```bash
# Prevent sleep while bot runs (keeps system awake)
caffeinate -d python3 bot.py
```

### Option 2: Run on a Server/Cloud (Best for Production)

- **AWS EC2** (free tier available)
- **DigitalOcean Droplet** ($5/month)
- **Google Cloud Run** (pay per use)
- **Heroku** (free tier limited)
- **Raspberry Pi** (if you have one)

### Option 3: Keep Laptop Plugged In + Awake

1. Plug in your laptop
2. Set display to never sleep
3. Close the lid (if MacBook, it may still sleep - check settings)
4. Run bot in terminal

### Option 4: Use Screen/Tmux (For Remote Access)

```bash
# Install tmux (if not installed)
brew install tmux

# Start tmux session
tmux new -s kalshi-bot

# Run bot inside tmux
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
python3 bot.py

# Detach: Press Ctrl+B, then D
# Reattach later: tmux attach -t kalshi-bot
```

## Quick Fix: Prevent Sleep Now

Run this command to keep your Mac awake:
```bash
caffeinate -d
```

Then in another terminal, run the bot. Your Mac will stay awake as long as caffeinate runs.

## Check Current Sleep Settings

```bash
# Check current sleep settings
pmset -g
```

## Recommended Setup for Overnight

1. **Plug in laptop** (don't let battery die)
2. **Prevent sleep**: System Settings → Battery → Prevent sleep
3. **Run bot**: `python3 bot.py`
4. **Optional**: Use `caffeinate -d` for extra protection

## Alternative: Run in Background with Logging

```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
nohup python3 bot.py > bot.log 2>&1 &
```

Then check logs:
```bash
tail -f bot.log
```
