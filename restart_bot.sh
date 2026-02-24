#!/bin/bash
# Hard restart script for Kalshi Trading Bot
# Ensures fresh code is loaded by clearing bytecode cache

set -e
cd "$(dirname "$0")"

echo "🛑 Stopping all bot processes..."
pkill -9 -f "python.*bot" 2>/dev/null || true
pkill -9 -f "python.*src" 2>/dev/null || true
# Kill any process holding the web dashboard port
lsof -ti :8050 | xargs kill -9 2>/dev/null || true
sleep 2

echo "🧹 Clearing Python bytecode cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

echo "✅ Verifying no old processes..."
if pgrep -f "python.*bot" > /dev/null; then
    echo "⚠️  Warning: Some processes still running, force killing..."
    pkill -9 -f "python.*bot" 2>/dev/null || true
    sleep 1
fi

echo "🚀 Starting bot with fresh code..."
echo "   MAX_BUY_PRICE_CENTS will be: $(python3 -c 'from src.config import Config; print(Config.MAX_BUY_PRICE_CENTS)')"
# -B flag prevents Python from writing .pyc files
# -u flag forces unbuffered output for real-time logging
caffeinate -i env PYTHONPATH=. python3 -B -u src/bot.py
