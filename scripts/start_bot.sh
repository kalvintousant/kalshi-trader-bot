#!/bin/bash
# Kalshi Trading Bot - Optimized Startup Script
# Designed for persistent overnight execution

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🤖 KALSHI TRADING BOT - PRODUCTION STARTUP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Stop existing bot instance
if pgrep -f "python.*bot.py" > /dev/null; then
    echo "⚠️  Stopping existing bot..."
    pkill -f "python.*bot.py"
    sleep 2
fi

# Clean old logs
rm -f bot_output.log nohup.out
echo "✅ Cleaned old logs"
echo ""

# Start bot with full persistence
cd "$(dirname "$0")/.."
nohup caffeinate -i env PYTHONPATH=. python3 -u src/bot.py > bot_output.log 2>&1 &
BOT_PID=$!

echo "🚀 Bot started successfully!"
echo ""
echo "📊 Status:"
echo "  PID: $BOT_PID"
echo "  Log: bot_output.log"
echo "  Trades: trades.log"
echo ""
echo "✅ Optimizations:"
echo "  • Dual strategy (Longshot + Conservative)"
echo "  • Heartbeat every 30 minutes"
echo "  • Auto-retry on network errors"
echo "  • Survives terminal close (nohup)"
echo "  • Prevents Mac sleep (caffeinate)"
echo ""
echo "📝 Monitoring Commands:"
echo "  tail -f bot_output.log  # Watch live"
echo "  cat trades.log          # View trades"
echo "  ps aux | grep bot.py    # Check status"
echo "  pkill -f bot.py         # Stop bot"
echo ""
echo "Waiting 8 seconds for startup..."
sleep 8

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 INITIAL OUTPUT:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
tail -20 bot_output.log
echo ""
echo "✅ Bot is running! Close this terminal safely - bot will continue."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
