# BTC 15-Minute Latency Arbitrage Strategy

## Overview

This strategy implements latency arbitrage for Kalshi's **15-minute BTC markets** (`KXBTC15M`). These markets ask: "Bitcoin price up or down in next 15 mins?"

The strategy tracks real-time BTC price movements from Binance and trades during the lag window when Kalshi pricing hasn't caught up.

## Market Details

- **Series Ticker**: `KXBTC15M`
- **Market Type**: Binary (YES = price goes up, NO = price goes down)
- **Time Period**: 15 minutes
- **Market URL**: https://kalshi.com/markets/kxbtc15m/bitcoin-price-up-down

## How It Works

### 1. Real-Time BTC Tracking

- Fetches real-time BTC price from Binance API
- Gets 5-minute candles for momentum calculation
- Calculates 15-minute price changes
- Updates every 15 seconds (faster than hourly strategy)

### 2. Latency Arbitrage Detection

Compares fresh Binance moves to Kalshi's slower-updating odds:
- Detects significant BTC moves (momentum > 0.2%, volatility > 0.15%)
- Calculates expected Kalshi price based on BTC move
- Identifies mispricing when Kalshi odds lag behind (>2 cents difference)

### 3. Entry Logic

**If BTC pumps (price goes up):**
- Expected YES probability increases
- If YES is underpriced on Kalshi → Buy YES
- Entry: When mispricing > 2 cents

**If BTC dumps (price goes down):**
- Expected NO probability increases  
- If NO is underpriced on Kalshi → Buy NO
- Entry: When mispricing > 2 cents

### 4. Exit Logic

Automatically exits when:
- Pricing moves towards expected value (mispricing closes)
- Position becomes profitable (+2 cents)
- Minimum hold time: 15 seconds (faster than hourly strategy)

## Strategy Parameters

```python
momentum_threshold = 0.2%      # Minimum BTC move to trigger (lower than hourly)
volatility_threshold = 0.15%  # Ensures real move (lower than hourly)
mispricing_threshold = 2      # Minimum price difference (cents) - more sensitive
```

**Price Scaling:**
- 1% BTC move = 15% probability change (more sensitive than hourly)
- Formula: `expected_yes_prob = 50 + (btc_change_15m * 15)`

## Performance Optimizations

- **Fast scan interval**: 5 seconds (vs 10s for hourly)
- **Frequent BTC updates**: Every 15 seconds (vs 30s for hourly)
- **Lower thresholds**: More sensitive to smaller moves
- **Quick exits**: 15-second minimum hold (vs 30s for hourly)

## Example Trade

**Scenario: BTC Pumps**

1. **Binance**: BTC moves +0.4% in last 15 minutes
2. **Momentum detected**: 0.4% move, volatility 0.2%
3. **Expected Kalshi price**: YES should be ~56¢ (50 + 0.4% × 15)
4. **Actual Kalshi price**: YES at 52¢ (hasn't caught up)
5. **Mispricing**: 4 cents (56 - 52)
6. **Action**: Buy YES at 53¢
7. **Exit**: When YES price moves to 54¢+ or mispricing closes

## Advantages

1. **Faster reaction**: 5-second scans catch moves quickly
2. **More opportunities**: 15-minute markets expire more frequently
3. **Lower thresholds**: Catches smaller moves that hourly might miss
4. **Quick exits**: Faster position turnover

## Risks

1. **More frequent trading**: Higher API usage and fees
2. **Smaller moves**: Need tighter thresholds
3. **Faster expiration**: Less time for mispricing to close
4. **Market noise**: 15-minute moves can be more volatile

## Configuration

Enable in `.env`:
```
ENABLED_STRATEGIES=btc_15m
```

Or combine with hourly:
```
ENABLED_STRATEGIES=btc_15m,btc_hourly
```

## Monitoring

The bot will:
- Scan every 5 seconds
- Update BTC data every 15 seconds
- Log all trades to `trades.log`
- Send macOS notifications for each trade

Watch for:
- `[BTC15MinStrategy] BTC PUMP detected` - Entry signal
- `[BTC15MinStrategy] BTC DUMP detected` - Entry signal
- `[BTC15MinStrategy] Exiting position` - Exit signal
