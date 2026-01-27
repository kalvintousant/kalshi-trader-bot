# Forecast and EV Accuracy Improvements

## Current Implementation Analysis

### Forecast Aggregation
- **Current**: Simple mean and standard deviation of all forecasts
- **Limitation**: Treats all sources equally, no reliability weighting
- **Limitation**: Fixed 2.0°F std when only one forecast available
- **Limitation**: No historical accuracy tracking

### Probability Distribution
- **Current**: Normal distribution with mean/std from forecasts
- **Limitation**: Assumes symmetric distribution (may not be accurate)
- **Limitation**: Fixed temperature range brackets (2-degree increments)
- **Limitation**: No consideration of forecast model differences

### EV Calculation
- **Current**: Basic EV = (Win Prob × Payout) - (Loss Prob × Stake)
- **Limitation**: Doesn't account for transaction fees
- **Limitation**: No consideration of market depth/slippage
- **Limitation**: No position sizing optimization (Kelly Criterion)

---

## Recommended Improvements

### 1. Source Reliability Weighting ⭐ HIGH PRIORITY

**Problem**: All forecast sources are treated equally, but some are more accurate than others.

**Solution**: Weight forecasts by historical accuracy:
```python
# Track accuracy per source over time
source_weights = {
    'nws': 1.0,        # Most reliable (government source)
    'tomorrowio': 0.9, # Very reliable
    'weatherbit': 0.8  # Good but less reliable
}

# Weighted mean instead of simple mean
weighted_mean = sum(forecast * weight for forecast, weight in zip(forecasts, weights)) / sum(weights)
```

**Impact**: More accurate probability estimates, better EV calculations

**Implementation Difficulty**: Medium (requires tracking historical accuracy)

---

### 2. Forecast Age/Recency Weighting ⭐ HIGH PRIORITY

**Problem**: Older forecasts are less accurate than recent ones, but all are weighted equally.

**Solution**: Apply exponential decay based on forecast age:
```python
# Weight = exp(-age_hours / half_life_hours)
# Example: 6-hour half-life means forecast loses 50% weight after 6 hours
forecast_age_hours = (now - forecast_time).total_seconds() / 3600
weight = np.exp(-forecast_age_hours / 6.0)  # 6-hour half-life
```

**Impact**: More accurate near-term forecasts, better edge detection

**Implementation Difficulty**: Low (just need to track forecast timestamps)

---

### 3. Dynamic Standard Deviation ⭐ HIGH PRIORITY

**Problem**: Fixed 2.0°F std when only one forecast, doesn't account for forecast agreement.

**Solution**: Calculate std based on:
- Forecast spread (when multiple forecasts)
- Historical forecast error for that city/season
- Time until event (uncertainty increases with time)

```python
if len(forecasts) > 1:
    std_temp = np.std(forecasts)
    # Add base uncertainty based on forecast horizon
    days_until = (target_date - datetime.now()).days
    base_uncertainty = 1.0 + (days_until * 0.5)  # +0.5°F per day
    std_temp = max(std_temp, base_uncertainty)
else:
    # Use historical forecast error for this city/season
    std_temp = get_historical_forecast_error(series_ticker, target_date.month)
```

**Impact**: More accurate probability distributions, better risk assessment

**Implementation Difficulty**: Medium (requires historical data collection)

---

### 4. Skewed Distribution Models ⭐ MEDIUM PRIORITY

**Problem**: Normal distribution assumes symmetry, but temperature distributions can be skewed.

**Solution**: Use skewed normal or beta distribution:
```python
from scipy.stats import skewnorm

# Estimate skewness from forecast spread
skew = calculate_skewness(forecasts)
distribution = skewnorm(skew, mean_temp, std_temp)
```

**Impact**: More accurate tail probabilities (important for extreme events)

**Implementation Difficulty**: Medium (requires understanding of distribution shapes)

---

### 5. Historical Forecast Error Tracking ⭐ HIGH PRIORITY

**Problem**: No learning from past forecast accuracy.

**Solution**: Track actual vs predicted temperatures:
```python
# After market settles, compare actual temp to our forecast
actual_temp = get_settled_temperature(market)
forecast_error = abs(actual_temp - mean_forecast)

# Update historical error database
update_forecast_error_history(series_ticker, forecast_error, target_date.month)
```

**Impact**: Continuously improving accuracy, adaptive learning

**Implementation Difficulty**: Medium (requires database/storage)

---

### 6. Outlier Detection and Filtering ⭐ MEDIUM PRIORITY

**Problem**: One bad forecast can skew the entire distribution.

**Solution**: Use statistical methods to detect and downweight outliers:
```python
from scipy import stats

# Z-score method
z_scores = np.abs(stats.zscore(forecasts))
outlier_threshold = 2.5  # 2.5 standard deviations
valid_forecasts = [f for f, z in zip(forecasts, z_scores) if z < outlier_threshold]

# Or use IQR method
Q1, Q3 = np.percentile(forecasts, [25, 75])
IQR = Q3 - Q1
lower_bound = Q1 - 1.5 * IQR
upper_bound = Q3 + 1.5 * IQR
valid_forecasts = [f for f in forecasts if lower_bound <= f <= upper_bound]
```

**Impact**: More robust probability estimates, less sensitive to bad data

**Implementation Difficulty**: Low

---

### 7. Confidence Intervals ⭐ MEDIUM PRIORITY

**Problem**: Current system gives point probabilities, but doesn't express confidence.

**Solution**: Calculate confidence intervals around probabilities:
```python
# Bootstrap sampling to get confidence intervals
def bootstrap_probability(forecasts, threshold, n_samples=1000):
    probs = []
    for _ in range(n_samples):
        # Resample forecasts with replacement
        sample = np.random.choice(forecasts, size=len(forecasts), replace=True)
        prob = calculate_probability(sample, threshold)
        probs.append(prob)
    
    # Return mean and 95% confidence interval
    mean_prob = np.mean(probs)
    ci_lower = np.percentile(probs, 2.5)
    ci_upper = np.percentile(probs, 97.5)
    return mean_prob, (ci_lower, ci_upper)

# Only trade if confidence interval doesn't overlap with market price
if ci_lower > market_price or ci_upper < market_price:
    # High confidence in edge
    trade()
```

**Impact**: Better risk management, only trade when confident

**Implementation Difficulty**: Medium

---

### 8. Transaction Costs in EV ⭐ HIGH PRIORITY

**Problem**: EV calculation doesn't account for Kalshi fees.

**Solution**: Include maker/taker fees in EV:
```python
# Kalshi fees: ~5% on winning trades, ~0% on losing trades (you lose your stake)
maker_fee_rate = 0.05  # 5% fee on winnings

# Adjusted EV calculation
def calculate_ev_with_fees(win_prob, payout, loss_prob, stake, fee_rate=0.05):
    # If we win: payout - stake - (payout * fee_rate)
    # If we lose: -stake (no fee on losses)
    ev = (win_prob * (payout - stake - payout * fee_rate)) - (loss_prob * stake)
    return ev

# Example: 90% win prob, $1 payout, $0.10 stake
# Old EV: (0.9 * 1.0) - (0.1 * 0.1) = 0.9 - 0.01 = $0.89
# New EV: (0.9 * (1.0 - 0.1 - 0.05)) - (0.1 * 0.1) = (0.9 * 0.85) - 0.01 = $0.755
```

**Impact**: More realistic EV, prevents overestimating profitability

**Implementation Difficulty**: Low (just update EV formula)

---

### 9. Market Depth/Slippage Consideration ⭐ MEDIUM PRIORITY

**Problem**: EV assumes we can fill at the ask price, but large orders may experience slippage.

**Solution**: Estimate fill price based on orderbook depth:
```python
def estimate_fill_price(orderbook, side, quantity):
    """Estimate average fill price for given quantity"""
    orders = orderbook.get(side, [])
    total_cost = 0
    remaining = quantity
    
    for price, size in orders:
        if remaining <= 0:
            break
        fill_size = min(remaining, size)
        total_cost += price * fill_size
        remaining -= fill_size
    
    if remaining > 0:
        # Not enough liquidity, use worst-case price
        return orders[-1][0] if orders else 100  # Worst ask
    
    return total_cost / quantity

# Use estimated fill price instead of best ask
estimated_price = estimate_fill_price(orderbook, 'yes', position_size)
ev = calculate_ev(our_prob, 1.0, 1-our_prob, estimated_price/100.0)
```

**Impact**: More realistic EV for larger positions, better position sizing

**Implementation Difficulty**: Medium

---

### 10. Kelly Criterion for Position Sizing ⭐ MEDIUM PRIORITY

**Problem**: Fixed position sizes don't optimize for long-term growth.

**Solution**: Use Kelly Criterion to optimize position size:
```python
def kelly_fraction(win_prob, payout_ratio):
    """
    Kelly Criterion: f = (p * b - q) / b
    where:
    - p = win probability
    - q = loss probability (1 - p)
    - b = payout ratio (payout / stake)
    """
    if payout_ratio <= 0:
        return 0
    
    q = 1 - win_prob
    f = (win_prob * payout_ratio - q) / payout_ratio
    
    # Use fractional Kelly (50% of full Kelly) for safety
    return max(0, min(0.5 * f, 0.25))  # Cap at 25% of bankroll

# Example: 80% win prob, $1 payout, $0.20 stake
# Payout ratio = 1.0 / 0.20 = 5.0
# Kelly = (0.8 * 5.0 - 0.2) / 5.0 = (4.0 - 0.2) / 5.0 = 0.76
# Fractional Kelly (50%) = 0.38 = 38% of bankroll (too high, use cap)
# Position size = min(kelly_fraction * bankroll, max_position_size)
```

**Impact**: Optimal long-term growth, better risk-adjusted returns

**Implementation Difficulty**: Medium (requires careful implementation)

---

### 11. Seasonal/Time-of-Day Adjustments ⭐ LOW PRIORITY

**Problem**: Forecast accuracy varies by season and time of day.

**Solution**: Apply seasonal and temporal adjustments:
```python
# Seasonal adjustment factors (based on historical data)
seasonal_factors = {
    'winter': {'std_multiplier': 1.2},  # More uncertainty in winter
    'spring': {'std_multiplier': 1.0},
    'summer': {'std_multiplier': 0.9},  # More predictable in summer
    'fall': {'std_multiplier': 1.0}
}

# Time-of-day adjustment (forecasts more accurate closer to event)
hours_until = (target_date - datetime.now()).total_seconds() / 3600
if hours_until < 12:
    time_adjustment = 0.9  # Very recent forecast
elif hours_until < 24:
    time_adjustment = 1.0  # Standard
else:
    time_adjustment = 1.1  # Further out, more uncertainty

adjusted_std = base_std * seasonal_factors[season]['std_multiplier'] * time_adjustment
```

**Impact**: More accurate uncertainty estimates

**Implementation Difficulty**: Low (but requires historical analysis)

---

### 12. Ensemble Model Averaging ⭐ MEDIUM PRIORITY

**Problem**: Single distribution model may not capture all uncertainty.

**Solution**: Average multiple distribution models:
```python
# Use multiple distribution types and average
models = {
    'normal': stats.norm(mean, std),
    'skewed': stats.skewnorm(skew, mean, std),
    't_dist': stats.t(df=5, loc=mean, scale=std)  # Heavier tails
}

# Average probabilities across models
prob_above = np.mean([
    model.cdf(threshold) for model in models.values()
])
```

**Impact**: More robust probability estimates, less model-dependent

**Implementation Difficulty**: Medium

---

## Implementation Priority

### Phase 1 (Quick Wins - High Impact):
1. ✅ **Transaction Costs in EV** - Easy, immediate impact
2. ✅ **Outlier Detection** - Easy, improves robustness
3. ✅ **Forecast Age Weighting** - Medium, significant accuracy gain

### Phase 2 (Medium Term - High Impact):
4. ✅ **Source Reliability Weighting** - Medium, requires tracking
5. ✅ **Dynamic Standard Deviation** - Medium, requires historical data
6. ✅ **Historical Forecast Error Tracking** - Medium, requires database

### Phase 3 (Advanced - Medium Impact):
7. ✅ **Confidence Intervals** - Medium, better risk management
8. ✅ **Market Depth/Slippage** - Medium, better for larger positions
9. ✅ **Kelly Criterion** - Medium, optimal position sizing

### Phase 4 (Research - Lower Priority):
10. ✅ **Skewed Distributions** - Medium, marginal gains
11. ✅ **Seasonal Adjustments** - Low, requires research
12. ✅ **Ensemble Models** - Medium, complexity vs benefit

---

## Expected Impact Summary

| Improvement | Accuracy Gain | EV Accuracy Gain | Difficulty |
|------------|---------------|------------------|------------|
| Transaction Costs | - | +15-20% | Low |
| Source Weighting | +10-15% | +5-10% | Medium |
| Forecast Age | +5-10% | +3-5% | Low |
| Dynamic Std Dev | +5-10% | +3-5% | Medium |
| Outlier Detection | +3-5% | +2-3% | Low |
| Historical Tracking | +10-20% | +8-15% | Medium |
| Confidence Intervals | +5% | +5% | Medium |
| Market Depth | - | +5-10% | Medium |
| Kelly Criterion | - | +10-15% | Medium |

**Total Potential Improvement**: 
- Forecast Accuracy: +30-50%
- EV Accuracy: +40-60%

---

## Next Steps

1. **Start with Phase 1** - Implement transaction costs, outlier detection, and forecast age weighting
2. **Build historical database** - Start tracking forecast errors for Phase 2
3. **A/B Testing** - Compare old vs new methods on paper trading
4. **Gradual rollout** - Implement improvements incrementally and monitor results
