#!/bin/bash
# Clean Start Script - Forces fresh Python environment
# Use this if the bot won't start due to cached bytecode

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧹 CLEAN START - Kalshi Trading Bot"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Kill any existing bot processes
echo "1. Stopping any existing bot processes..."
pkill -9 -f "python.*bot" 2>/dev/null
pkill -9 -f "python.*force_start" 2>/dev/null
sleep 2
echo "   ✅ Stopped"

# Remove ALL Python cache files
echo ""
echo "2. Removing ALL Python cache files..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null
find . -name "*.pyo" -delete 2>/dev/null
rm -rf src/__pycache__ 2>/dev/null
rm -rf __pycache__ 2>/dev/null
echo "   ✅ Cache cleared"

# Remove old logs
echo ""
echo "3. Removing old log files..."
rm -f bot_output.log nohup.out 2>/dev/null
echo "   ✅ Logs cleared"

# Verify the fix is in place
echo ""
echo "4. Verifying code fix..."
if grep -q "# Don't call super() - this is the base class" src/strategies.py; then
    echo "   ✅ Fix verified: TradingStrategy doesn't call super()"
else
    echo "   ⚠️  Warning: Fix may not be in place"
fi

# Start bot with fresh Python (no bytecode)
echo ""
echo "5. Starting bot with clean Python environment..."
echo "   Using PYTHONDONTWRITEBYTECODE=1 to prevent cache"
echo ""

# Set environment to prevent bytecode caching
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH=.

# Change to project directory
cd "$(dirname "$0")"

# Start the bot
nohup caffeinate -i env PYTHONPATH=. python3 -B -u src/bot.py > bot_output.log 2>&1 &
BOT_PID=$!

echo "   🚀 Bot started with PID: $BOT_PID"
echo ""

# Wait for startup
echo "6. Waiting for bot to initialize (8 seconds)..."
sleep 8

# Check if bot is running
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 STARTUP STATUS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ps -p $BOT_PID > /dev/null 2>&1; then
    echo "✅ Bot process is running (PID: $BOT_PID)"
else
    echo "⚠️  Bot process may have exited"
    echo "    Checking for active Python bot processes..."
    if pgrep -f "python.*bot" > /dev/null 2>&1; then
        ACTUAL_PID=$(pgrep -f "python.*bot" | head -1)
        echo "✅ Found bot running with PID: $ACTUAL_PID"
    else
        echo "❌ No bot process found - check log for errors"
    fi
fi

echo ""
echo "📝 Last 20 lines of log:"
echo "─────────────────────────────────────────────────────────────────────"
tail -20 bot_output.log 2>/dev/null || echo "(No log file yet)"
echo "─────────────────────────────────────────────────────────────────────"
echo ""

# Check for errors
if grep -q "TypeError\|Traceback" bot_output.log 2>/dev/null; then
    echo "⚠️  ERROR DETECTED in log file"
    echo ""
    echo "   If you see 'TypeError: object.__init__()' error:"
    echo "   1. Close ALL terminal windows"
    echo "   2. Open a NEW terminal"
    echo "   3. Run this script again"
    echo ""
    echo "   This forces Python to reload all modules fresh."
elif grep -q "Starting Kalshi Trading Bot\|Scanning markets" bot_output.log 2>/dev/null; then
    echo "🎉 SUCCESS! Bot is running and working!"
    echo ""
    echo "📝 Monitor with: tail -f bot_output.log"
    echo "🛑 Stop with:    pkill -f bot.py"
else
    echo "⏳ Bot is starting... check log in a few seconds:"
    echo "   tail -f bot_output.log"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
