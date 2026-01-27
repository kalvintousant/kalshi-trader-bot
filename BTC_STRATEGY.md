# BTC Latency Arbitrage Strategy

## Overview

This strategy implements the exact loop described: tracking real-time BTC moves from Binance and trading during the lag window when Kalshi pricing hasn't caught up.

## How It Works

### 1. Read Real-Time BTC Moves

The bot continuously tracks Binance's 5-minute candle momentum and reacts the moment volatility appears:
- Fetches real-time BTC price from Binance API
- Gets 5-minute candles for momentum calculation
- Calculates momentum and volatility
- Detects significant moves (configurable thresholds)

### 2. Check Kalshi's Delayed Pricing

Compares the fresh Binance move to Kalshi's slower-updating odds:
- Gets current Kalshi market prices
- Calculates expected price based on BTC move
- Identifies desynchronization (mispricing)

### 3. Enter During Lag Window

If BTC pumps → buys YES before Kalshi adjusts.
If BTC dumps → buys NO before the market wakes up.

**Entry Conditions:**
- BTC momentum > 0.3% (configurable)
- Volatility > 0.2% (ensures real move)
- Mispricing > 3 cents (Kalshi hasn't caught up)

### 4. Exit Once Pricing Catches Up

Automatically exits when:
- Pricing moves towards expected value (mispricing closes)
- Position becomes profitable
- Minimum hold time of 30 seconds (prevents immediate exits)

## Strategy Flow

```
1. BTC Price Update (Binance)
   ↓
2. Calculate Momentum & Volatility
   ↓
3. Detect Significant Move?
   ├─ NO → Wait
   └─ YES → Continue
   ↓
4. Calculate Expected Kalshi Price
   ↓
5. Compare to Actual Kalshi Price
   ↓
6. Mispricing Detected?
   ├─ NO → Wait
   └─ YES → Trade
   ↓
7. Enter Position
   ↓
8. Monitor for Exit Signal
   ↓
9. Exit When Pricing Catches Up
```

## Example Trade

**Scenario: BTC Pumps**

1. **Binance**: BTC moves +0.5% in last 15 minutes
2. **Momentum detected**: 0.5% move, volatility 0.3%
3. **Expected Kalshi price**: YES should be ~55¢ (50 + 0.5% × 10)
4. **Actual Kalshi price**: YES at 48¢ (hasn't caught up)
5. **Mispricing**: 7 cents (55 - 48)
6. **Action**: Buy YES at 49¢
7. **Exit**: When YES price moves to ~53¢ or higher (pricing caught up)

## Configuration

### Strategy Parameters (in `strategies.py`)

```python
self.momentum_threshold = 0.3  # Minimum momentum % to trigger (0.3%)
self.volatility_threshold = 0.2  # Minimum volatility % (0.2%)
self.mispricing_threshold = 3  # Minimum price difference in cents (3¢)
```

### Adjusting Thresholds

- **Lower momentum_threshold**: More trades, but may catch noise
- **Higher momentum_threshold**: Fewer trades, but higher quality
- **Lower mispricing_threshold**: More opportunities, but smaller edge
- **Higher mispricing_threshold**: Fewer trades, but larger edge

## Advantages

1. **Speed advantage**: Uses real-time Binance data vs Kalshi's delayed pricing
2. **Data-driven**: Based on actual BTC price movements, not guessing
3. **Automated exit**: Exits when pricing catches up, locking in profits
4. **Volatility filter**: Only trades on significant moves, not noise

## Limitations

1. **Lag window is brief**: Must act quickly before Kalshi catches up
2. **Requires active monitoring**: BTC data must be fresh (< 30 seconds)
3. **Market timing**: Works best during volatile periods
4. **Position tracking**: Must correctly track active positions for exit logic

## Technical Details

### BTC Data Source
- **Binance API**: Free, no API key needed
- **Update frequency**: Every 30 seconds (or when stale)
- **Data kept**: Last 100 price points, last 20 candles

### Price Calculation
- **Expected YES probability**: `50 + (BTC_change_15m × 10)`
- **Scaling**: 1% BTC move = 10% probability change
- **Clamped**: Between 1-99% to stay within valid range

### Exit Logic
- **Minimum hold**: 30 seconds (prevents immediate exits)
- **Exit conditions**:
  - Price moved to expected value (within 2 cents)
  - Position is profitable (price > entry + 2 cents)

## Next Steps

1. **Optimize thresholds**: Backtest to find optimal momentum/volatility/mispricing thresholds
2. **Add position sizing**: Scale position size based on mispricing magnitude
3. **Improve exit timing**: Fine-tune exit conditions for better profit capture
4. **Add stop-loss**: Exit if move reverses before pricing catches up
5. **Multiple markets**: Track multiple 15-min BTC markets simultaneously
