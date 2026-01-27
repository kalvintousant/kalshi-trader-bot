# Strategy Improvements: If No Trades After Overnight Run

## Quick Summary

If the bot runs overnight but makes **zero trades**, the most likely fixes are:

1. **Lower thresholds** (momentum, volatility, mispricing)
2. **Lower volume requirement** (currently 20 contracts)
3. **Add debug logging** to see what's happening
4. **Check BTC data freshness**

---

## Current Thresholds (BTC15MinStrategy)

```python
momentum_threshold = 0.2%      # Minimum BTC move to trigger
volatility_threshold = 0.15%   # Minimum volatility
mispricing_threshold = 2       # Minimum price difference (cents)
volume_threshold = 20          # Minimum market volume
```

**These may be too strict for low-volatility periods.**

---

## Improvement 1: Lower Thresholds (Most Likely Fix)

### Recommended Changes

**Option A: More Aggressive (More Trades)**
```python
momentum_threshold = 0.1%      # 50% lower
volatility_threshold = 0.1%    # 33% lower  
mispricing_threshold = 1       # 50% lower
volume_threshold = 10         # 50% lower
```

**Option B: Balanced (Moderate)**
```python
momentum_threshold = 0.15%    # 25% lower
volatility_threshold = 0.12%  # 20% lower
mispricing_threshold = 1.5    # 25% lower
volume_threshold = 15         # 25% lower
```

### How to Implement

Edit `strategies.py`:

1. Find `BTC15MinStrategy.__init__()` (around line 353)
2. Change thresholds:
```python
# From:
self.momentum_threshold = 0.2
self.volatility_threshold = 0.15
self.mispricing_threshold = 2

# To (Option B example):
self.momentum_threshold = 0.15
self.volatility_threshold = 0.12
self.mispricing_threshold = 1.5
```

3. Find `BTC15MinStrategy.should_trade()` (around line 384)
4. Change volume requirement:
```python
# From:
if market.get('volume', 0) < 20:
    return False

# To:
if market.get('volume', 0) < 15:  # Lower threshold
    return False
```

---

## Improvement 2: Add Debug Logging

Add logging to see why trades aren't happening.

In `strategies.py`, find `BTC15MinStrategy.get_trade_decision()` and add:

```python
# After line 415 (if not has_move):
if not has_move:
    momentum = self.btc_tracker.calculate_momentum()
    volatility = self.btc_tracker.calculate_volatility()
    print(f"[DEBUG] No move: Momentum={momentum:.3f}% (need {self.momentum_threshold}%), Volatility={volatility:.3f}% (need {self.volatility_threshold}%)")
    return None

# After line 424 (if btc_change_15m is None):
if btc_change_15m is None:
    print(f"[DEBUG] Could not calculate 15-minute BTC change")
    return None

# After line 457 (before trade decision):
print(f"[DEBUG] BTC change: {btc_change_15m:.3f}%, Expected YES: {expected_yes_prob:.1f}¢, Market YES: {best_yes_bid}¢, Mispricing: {price_mispricing:.1f}¢")
```

This will show you:
- Why moves aren't detected (momentum/volatility too low)
- What actual BTC changes are
- Why mispricing isn't detected

---

## Improvement 3: Check BTC Data

Verify BTC data is updating correctly:

```bash
# Check if BTC data is being fetched
grep -i "btc\|binance" bot_output.log | tail -20

# Test BTC tracker manually
python3 -c "from btc_data import BTCPriceTracker; t = BTCPriceTracker(); t.update(); print(f'BTC Price: \${t.get_current_price()}'); print(f'Momentum: {t.calculate_momentum()}%'); print(f'Volatility: {t.calculate_volatility()}%')"
```

---

## Improvement 4: Adjust Price Scaling

Current scaling might not create enough mispricing for small moves.

**Current:**
```python
expected_yes_prob = 50 + (btc_change_15m * 15)
```

**More Aggressive:**
```python
expected_yes_prob = 50 + (btc_change_15m * 20)  # More sensitive
```

Find line 447 in `strategies.py` and change the multiplier.

---

## Improvement 5: Alternative Entry Logic

Current logic requires BOTH momentum AND volatility.

**Try OR instead of AND:**

Find `btc_data.py`, method `detect_significant_move()`:

```python
# Current: Requires both
if momentum >= momentum_threshold and volatility >= volatility_threshold:
    return True, direction

# Alternative: Either one is enough
if momentum >= momentum_threshold or volatility >= volatility_threshold:
    return True, direction
```

---

## Quick Implementation Checklist

1. ✅ **Add debug logging** (Improvement 2) - See what's happening
2. ✅ **Lower thresholds** (Improvement 1, Option B) - Most likely fix
3. ✅ **Lower volume requirement** (Improvement 1) - Opens more markets
4. ✅ **Test for 30 minutes** - Monitor logs
5. ✅ **Gradually adjust** if still no trades

---

## Expected Results

### After Lowering Thresholds:
- **More trades**: 5-20 per day (vs 0)
- **Smaller edge per trade**: But more opportunities
- **Need higher win rate**: Since edges are smaller

### After Adding Debug Logging:
- **Visibility**: See exactly why trades aren't happening
- **Data-driven**: Know what to adjust
- **Faster fixes**: Identify issues quickly

---

## Monitoring After Changes

```bash
# Watch for trade signals
tail -f bot_output.log | grep -i "detected\|trade\|debug"

# Count potential trades
grep -c "BTC.*detected" bot_output.log

# Check what's being filtered
grep "DEBUG\|No move" bot_output.log | tail -20
```

---

## If Still No Trades

If still no trades after these changes:

1. **Market conditions**: BTC simply not moving enough (low volatility period)
2. **Wrong hours**: Try running during US market hours (9 AM - 4 PM EST)
3. **Switch strategies**: Try hourly BTC or weather strategy
4. **Check API**: Verify BTC data is actually updating

---

## Safety Reminders

- **Start conservative**: Lower thresholds gradually
- **Monitor closely**: Watch first few trades carefully  
- **Keep position size small**: MAX_POSITION_SIZE=1
- **Set daily loss limit**: MAX_DAILY_LOSS=20

