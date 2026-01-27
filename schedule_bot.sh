#!/bin/bash
# Smart scheduling for Kalshi Weather Bot
# Runs during optimal hours when forecasts update most

HOUR=$(date +%H)

# Convert to integer
HOUR=$((10#$HOUR))

# Optimal hours: 6am (06) to 10pm (22)
if [ $HOUR -ge 6 ] && [ $HOUR -lt 22 ]; then
    # Check if bot is already running
    if ! pgrep -f "python.*bot.py" > /dev/null; then
        echo "[$(date)] Starting bot (daytime hours 6am-10pm)"
        cd "$(dirname "$0")"
        nohup caffeinate -i python3 -u bot.py > bot_output.log 2>&1 &
        echo "[$(date)] Bot started with PID: $!"
    else
        echo "[$(date)] Bot already running"
    fi
else
    # Stop bot during off-hours
    if pgrep -f "python.*bot.py" > /dev/null; then
        echo "[$(date)] Stopping bot (off-hours)"
        pkill -f "python.*bot.py"
        echo "[$(date)] Bot stopped"
    else
        echo "[$(date)] Bot not running (off-hours)"
    fi
fi
