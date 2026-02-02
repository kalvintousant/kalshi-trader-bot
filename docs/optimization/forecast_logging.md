# Data Source Forecast Logging & Analysis

## How It Works

### 1. Automatic Logging (No Extra API Calls)
When the bot evaluates a market, it:
- Fetches forecasts from all enabled sources (as it already does)
- **NEW:** Logs each source's forecast to `data/source_forecasts.csv`
- Uses these forecasts for trading decisions (normal behavior)

**File: `data/source_forecasts.csv`**
```csv
timestamp,series_ticker,target_date,source,forecast_temp,market_type
2026-01-31T13:00:00,KXHIGHNY,2026-02-01,nws,72.50,high
2026-01-31T13:00:00,KXHIGHNY,2026-02-01,open_meteo_ecmwf,73.20,high
2026-01-31T13:00:00,KXHIGHNY,2026-02-01,tomorrowio,71.80,high
...
```

### 2. Automatic Outcome Tracking
When markets settle:
- `check_settled_markets.py` (run daily) records actual NWS temperatures to `data/outcomes.csv`
- Or use `backfill_historical.py` to backfill past trades

**File: `data/outcomes.csv`**
```csv
market_ticker,city,date,actual_temp,...
KXHIGHNY-26FEB01-T22,KXHIGHNY,2026-02-01,74.2,...
```

### 3. Analysis (No API Calls)
Run `analyze_forecast_accuracy.py` anytime to see:
- Which sources are most accurate
- Which combinations perform best
- Recommendations for improvement

```bash
python3 analyze_forecast_accuracy.py
```

**Example Output:**
```
SOURCE ACCURACY ANALYSIS
================================================================================

#1: open_meteo_ecmwf
  Mean Absolute Error: 1.23°F
  Within ±2°F: 87.5%
  Samples: 45

#2: nws
  Mean Absolute Error: 1.45°F
  Within ±2°F: 82.3%
  Samples: 45

#3: tomorrowio
  Mean Absolute Error: 1.67°F
  Within ±2°F: 78.9%
  Samples: 45

COMBINATION ANALYSIS
================================================================================

All Sources (10):
  MAE: 1.85°F
  Within ±2°F: 75.0%

Top 3: open_meteo_ecmwf, nws, tomorrowio:
  MAE: 1.15°F
  Within ±2°F: 91.2%

RECOMMENDATION
================================================================================
💡 Using Top 3 would be 37.8% more accurate than using all sources
   Consider disabling underperforming sources to reduce noise
```

## Timeline

### Day 1-2 (Now)
- Bot starts logging forecasts automatically ✅
- No analysis results yet (need markets to settle)

### Day 3
- Yesterday's markets settle
- Run `analyze_forecast_accuracy.py`
- See which sources were most accurate for those markets

### Week 1
- 7 days of data
- More reliable accuracy statistics
- Can start making optimization decisions

### Month 1
- 30+ days of data
- Very reliable accuracy metrics
- Clear patterns emerge (e.g., "ECMWF best for NYC, GFS best for Miami")

## Free Tier Friendly

✅ **No extra API calls** - logs forecasts we already fetch for trading
✅ **Stays under limits** - only fetches when trading (normal bot operation)
✅ **Analysis is instant** - uses logged data, no API calls needed

## Usage

### Check Current Status
```bash
# How many forecasts logged?
wc -l data/source_forecasts.csv

# How many outcomes recorded?
wc -l data/outcomes.csv

# Run analysis
python3 analyze_forecast_accuracy.py
```

### Daily Routine (Automated)
```bash
# 1. Bot runs and logs forecasts automatically
# 2. Check for settled markets once per day
python3 check_settled_markets.py

# 3. Analyze accuracy (optional, whenever you want)
python3 analyze_forecast_accuracy.py
```

### Optimization (After 1+ Weeks)
Based on analysis results, you can:

1. **Disable underperforming sources** in `.env`:
   ```env
   ENABLE_WEATHERBIT=false
   ENABLE_VISUAL_CROSSING=false
   ```

2. **Adjust source weights** in `weather_data.py`:
   ```python
   self.source_weights = {
       'open_meteo_ecmwf': 1.0,  # Best performer
       'nws': 0.95,
       'tomorrowio': 0.9,
       'weatherbit': 0.7,  # Underperformer
   }
   ```

3. **Enable bias correction** (learns each source's systematic errors):
   ```env
   ENABLE_BIAS_CORRECTION=true
   MIN_SAMPLES_FOR_BIAS=10
   ```

## Files Created

- `data/source_forecasts.csv` - Logged forecasts (auto-created)
- `data/outcomes.csv` - Actual temperatures (auto-created)
- `analyze_forecast_accuracy.py` - Analysis script (new)
- `check_settled_markets.py` - Daily outcome checker (existing)
- `backfill_historical.py` - Backfill past trades (utility)

## Next Steps

1. ✅ **Done:** Modified weather_data.py to log forecasts
2. 📋 **Next:** Let bot run normally - it will log forecasts automatically
3. ⏰ **Tomorrow:** Run `check_settled_markets.py` to record today's actual temps
4. 📊 **Day 3:** Run `analyze_forecast_accuracy.py` to see results
5. 🎯 **Week 1:** Make optimization decisions based on real data
