#!/bin/bash
# Restart the trading bot with the fixed protection rules

echo "========================================="
echo "Restarting Trading Bot with Fixed Protection Rules"
echo "========================================="

# Kill all existing bot processes
echo ""
echo "1. Stopping all existing bot processes..."
pkill -f "python.*src/bot.py"
pkill -f "caffeinate.*bot.py"
sleep 2

# Verify all processes are stopped
REMAINING=$(ps aux | grep -E "python.*src/bot.py" | grep -v grep | wc -l)
if [ "$REMAINING" -gt 0 ]; then
    echo "   ⚠️  Warning: $REMAINING bot process(es) still running"
    echo "   Forcing termination..."
    pkill -9 -f "python.*src/bot.py"
    sleep 1
fi

echo "   ✅ All bot processes stopped"

# Start the bot with the fixed code
echo ""
echo "2. Starting bot with fixed protection rules..."
cd /Users/kalvintousant/Desktop/Kalshi\ Trader\ Bot

# Use nohup to run in background
nohup caffeinate -i env PYTHONPATH=. python3 -B -u src/bot.py > bot_output.log 2>&1 &
BOT_PID=$!

sleep 2

# Verify bot started
if ps -p $BOT_PID > /dev/null; then
    echo "   ✅ Bot started successfully (PID: $BOT_PID)"
    echo ""
    echo "========================================="
    echo "Bot is now running with FIXED protection rules!"
    echo "========================================="
    echo ""
    echo "The $3 per base market limit will now be correctly enforced."
    echo ""
    echo "To monitor the bot:"
    echo "  tail -f bot_output.log"
    echo ""
    echo "To check exposure:"
    echo "  python3 check_exposure.py"
    echo ""
    echo "To stop the bot:"
    echo "  pkill -f 'python.*src/bot.py'"
else
    echo "   ❌ Failed to start bot"
    echo "   Check bot_output.log for errors"
    exit 1
fi
