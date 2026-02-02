# Outcome Tracking & Forecast Improvement System

The bot now tracks bet outcomes and uses them to improve forecast accuracy over time.

## How It Works

### 1. **Trade Logging** (Real-time)
When the bot places a trade, it logs:
- Market details, side, price, quantity
- Our predicted probability and edge
- Strategy mode (conservative/longshot)
- Expected value calculation

**Files:**
- `trades.log` - Human-readable trade log
- `data/trades.csv` - Structured CSV for analysis

### 2. **Outcome Checking** (Every hour)
The bot checks for settled markets:
- Fetches filled orders from Kalshi API
- Identifies markets that have closed/finalized
- Extracts actual temperature outcomes
- Compares with our forecasts

### 3. **Forecast Learning** (Automatic)
When a market settles with actual data:
- Calculates forecast error: `|predicted - actual|`
- Updates historical error database by city/month
- Adjusts future probability distributions
- Stores up to 100 recent errors per city/month

**The model gets better over time!**

### 4. **Performance Tracking**
Comprehensive analytics on:
- Win rate overall and by city
- Profit/loss by strategy type
- Forecast accuracy by location
- Edge calibration (predicted edge vs actual)

## Files Created

```
data/
├── trades.csv           # All trades placed
├── outcomes.csv         # Real Kalshi API results only (markets officially settled)
└── performance.json     # Performance analytics
```

**Note:** `outcomes.csv` (results) contains only real Kalshi API data: rows are written when a market has officially closed/settled on the API. NWS-inferred outcomes are not written here; today's P&L may still use NWS inference for same-day reporting when the outcome is known but the market has not closed yet.

## View Performance

```bash
# View comprehensive report
python3 view_performance.py

# Check recent settled positions
tail -50 data/outcomes.csv

# Monitor outcome checks in real-time
tail -f bot_output.log | grep "outcome\|settled\|Forecast accuracy"
```

## What Gets Logged

### When Trade Placed:
```
✅ Scan complete in 44.2s
🔄 TRADE EXECUTED: BUY 3 NO @ 5¢
   Edge: 77.9% | EV: $0.738 | Mode: longshot
```

### When Market Settles (Hourly Check):
```
🔍 Checking for settled positions...
Found 3 settled position(s) to process
✅ Logged outcome: KXHIGHCHI-26JAN28-B17.5 | NO | WON | P&L: $2.85
   Forecast accuracy: Predicted 14.5°, Actual 15.2° (error: 0.7°)
📊 Updated forecast error for KXHIGHCHI (month 1): 0.70°F
📊 Performance Update: 12W-3L (80.0%) | P&L: $18.45
```

## Forecast Improvement Logic

The bot adjusts its uncertainty estimates based on historical accuracy:

**Initial State:**
- Default uncertainty: 2.0°F standard deviation
- Conservative probability distributions

**After Learning:**
- City-specific uncertainty from actual errors
- Month-specific adjustments (some months more predictable)
- Weighted average: 70% current std + 30% historical error

**Result:** More accurate probabilities → Better edge detection → Higher win rate

## Performance Metrics

The system tracks:

1. **Win Rate**: % of trades that profit
2. **Profit Factor**: Gross profit / Gross loss
3. **Forecast RMSE**: Root mean squared error per city
4. **Edge Accuracy**: Predicted edge vs realized edge
5. **Strategy Performance**: Conservative vs Longshot success rates

## Checking Outcomes Manually

To force an outcome check (normally runs every hour):

```python
from src.bot import KalshiTradingBot
bot = KalshiTradingBot()
bot.outcome_tracker.run_outcome_check()
```

## Data Persistence

- Outcome data persists across bot restarts
- Historical errors stored in memory + can be saved/loaded
- Performance JSON updated after each settled batch
- CSV files append-only (safe for analysis while running)

## Future Enhancements

Potential improvements:
- [ ] Multi-market triangulation for exact temperature extraction
- [ ] Weather source accuracy tracking (NWS vs Tomorrow.io vs Weatherbit)
- [ ] Time-of-day forecast decay (older forecasts less accurate)
- [ ] Volatility-adjusted position sizing based on historical errors
- [ ] Cross-city correlation analysis
- [ ] Seasonal adjustment factors

## Troubleshooting

**No outcomes showing up?**
- Markets need 24-48 hours to settle after close
- Check `data/outcomes.csv` exists (created on first settled position)
- Verify bot has been running during market resolution times

**Forecast errors seem high?**
- Early days have default 2°F uncertainty
- Accuracy improves after ~20-30 settled positions per city
- Winter months may be more volatile than summer

**Want to reset learning?**
- Delete `data/` folder to start fresh
- Bot will revert to default uncertainty estimates
- Useful if forecast sources change significantly
