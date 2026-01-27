# Overnight Test Guide

## Pre-Flight Checklist

### 1. Deposit Funds
- Current balance: $0.23
- Recommended: Deposit $100 for testing
- Go to: https://kalshi.com → Deposit

### 2. Verify Configuration

Your current settings are **VERY SAFE**:
- ✅ Max position size: **1 contract** (~$0.01 risk per trade)
- ✅ Max daily loss: **$10** (will stop if you lose $10)
- ✅ Both strategies enabled: BTC 15-min + Weather

### 3. Test Run First (5-10 minutes)

Before running overnight, test for a few minutes:

```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
python3 test_bot.py
```

Watch for:
- ✅ Bot connects successfully
- ✅ Scans markets without errors
- ✅ BTC data updates (if BTC strategy active)
- ✅ No authentication errors

Press `Ctrl+C` to stop after 5-10 minutes.

## Running Overnight

### Option 1: Run in Terminal (Recommended)

```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
python3 test_bot.py
```

**Keep terminal open** - the bot will run until you stop it or hit daily loss limit.

### Option 2: Run in Background (Advanced)

```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
nohup python3 test_bot.py > bot.log 2>&1 &
```

Check logs:
```bash
tail -f bot.log
```

Stop the bot:
```bash
pkill -f test_bot.py
```

## Safety Features

### Automatic Stops

The bot will **automatically stop trading** if:
1. Daily loss exceeds $10 (configurable)
2. You press Ctrl+C
3. Fatal error occurs

### Risk Per Trade

- **1 contract** = ~$0.01 risk
- Even if you lose 100 trades, that's only $1
- Very safe for testing!

### What to Expect

**Normal Operation:**
- Bot scans markets every 15 seconds
- Only trades when edge/mispricing detected
- Logs all trades and decisions
- Updates BTC data every 30 seconds

**If No Trades:**
- This is normal! The bot only trades when there's clear edge
- Weather strategy needs forecasts (NWS is free)
- BTC strategy needs significant moves + mispricing

## Monitoring

### Check Portfolio

```bash
python3 -c "from kalshi_client import KalshiClient; from config import Config; client = KalshiClient(); p = client.get_portfolio(); print(f'Balance: \${p[\"balance\"]/100:.2f}, Value: \${p[\"portfolio_value\"]/100:.2f}')"
```

### Check Active Orders

```bash
python3 -c "from kalshi_client import KalshiClient; from config import Config; client = KalshiClient(); orders = client.get_orders(); print(f'Active orders: {len([o for o in orders if o.get(\"status\") == \"resting\"])}')"
```

## Adjusting Settings

### More Conservative (Safer)

Edit `.env`:
```
MAX_POSITION_SIZE=1
MAX_DAILY_LOSS=5
```

### More Aggressive (Riskier)

Edit `.env`:
```
MAX_POSITION_SIZE=2
MAX_DAILY_LOSS=20
```

**⚠️ Only increase if you understand the risks!**

## Troubleshooting

### Bot Stops Immediately
- Check daily loss limit hasn't been hit
- Check for errors in output
- Verify API credentials are correct

### No Trades Happening
- **This is normal!** Bot only trades when edge detected
- Weather: Needs weather API data (NWS is free)
- BTC: Needs significant moves + mispricing
- Check logs to see if markets are being scanned

### Connection Errors
- Check internet connection
- Verify Kalshi API is up: https://status.kalshi.com
- Check API credentials in `.env`

## Expected Results

With $100 and current settings:
- **Max risk per trade**: $0.01
- **Max daily loss**: $10
- **Expected trades**: 0-20 per day (depends on market conditions)
- **Expected P&L**: Varies, but very small per trade

## After Testing

1. Check final balance
2. Review trades in Kalshi dashboard
3. Analyze what worked/didn't work
4. Adjust strategy parameters if needed
5. Scale up gradually if results are good

## Important Notes

- ⚠️ **Start small**: Current settings are very safe
- ⚠️ **Monitor first night**: Check in the morning
- ⚠️ **Markets have hours**: Some markets only trade during specific times
- ⚠️ **Weather markets**: Launch at 10 AM day before event
- ⚠️ **BTC markets**: Trade 24/7 but need volatility

Good luck! 🚀
