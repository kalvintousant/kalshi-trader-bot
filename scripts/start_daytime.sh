#!/bin/bash
# Kalshi Trading Bot - Daytime Only (6am-10pm)
# Optimized for weather markets when forecasts update most

HOUR=$(date +%H)
HOUR=$((10#$HOUR))

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌤️  KALSHI WEATHER BOT - DAYTIME MODE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Current time: $(date '+%H:%M')"
echo ""

# Check if within trading hours (6am-10pm)
if [ $HOUR -ge 6 ] && [ $HOUR -lt 22 ]; then
    echo "✅ Within trading hours (6am-10pm)"
    echo ""
    
    # Check if bot is already running
    if pgrep -f "python.*bot.py" > /dev/null; then
        BOT_PID=$(pgrep -f "python.*bot.py")
        echo "✓ Bot already running (PID: $BOT_PID)"
    else
        echo "🚀 Starting bot..."
        echo ""
        
        cd "$(dirname "$0")"
        
        # Stop any existing instance
        pkill -f "python.*bot.py" 2>/dev/null
        sleep 1
        
        # Clean old logs
        rm -f bot_output.log nohup.out
        
        # Start bot
        PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
        cd "$PROJECT_ROOT"
        nohup caffeinate -i python3 -u src/bot.py > bot_output.log 2>&1 &
        BOT_PID=$!
        
        echo "✅ Bot started!"
        echo "PID: $BOT_PID"
        echo "Log: bot_output.log"
        echo ""
        
        sleep 5
        
        echo "📋 Initial output:"
        tail -10 bot_output.log
    fi
else
    echo "⏸️  Outside trading hours"
    echo "Bot runs: 6am - 10pm daily"
    echo "Current hour: ${HOUR}:00"
    echo ""
    
    # Stop bot if running
    if pgrep -f "python.*bot.py" > /dev/null; then
        echo "Stopping bot (off-hours)..."
        pkill -f "python.*bot.py"
        echo "✅ Bot stopped"
    else
        echo "✓ Bot not running (expected)"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
