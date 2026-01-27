# Optimization Recommendations

## Critical Improvements

### 1. **Position Persistence** (High Priority)
**Issue**: Active positions are lost on bot restart
```python
# Current: self.active_positions = {} # Lost on restart
# Recommended: Persist to JSON file
```
**Impact**: Losing track of open positions on restart could lead to orphaned trades
**Solution**: Implement position persistence to JSON file

### 2. **Actual P&L Tracking** (High Priority)
**Issue**: `daily_pnl` is initialized but never updated with actual trade results
```python
# Current: self.daily_pnl = 0 # Never updated
# Recommended: Track actual trade outcomes
```
**Impact**: Daily loss limits not enforced accurately
**Solution**: Update P&L after each trade settles

### 3. **Rate Limiting Handling** (Medium Priority)
**Issue**: No explicit rate limit error handling
**Impact**: Could get temporary bans from Kalshi API
**Solution**: Add exponential backoff for 429 errors

### 4. **Parallel Market Fetching** (Medium Priority)
**Issue**: Series are fetched sequentially
```python
# Current: for series_ticker in self.relevant_series: ...
# Recommended: Use ThreadPoolExecutor for parallel fetching
```
**Impact**: ~2-3x faster market scanning
**Solution**: Fetch all series in parallel

### 5. **Stop-Loss Logic** (Medium Priority)
**Issue**: No stop-loss protection per position
**Impact**: Positions can lose more than expected
**Solution**: Add configurable stop-loss per trade

## Performance Improvements

### 6. **Volume Threshold** (Low Priority)
**Issue**: Volume check of `< 5` is very low, may lead to illiquid markets
**Current**: `if market.get('volume', 0) < 5:`
**Recommended**: Increase to 20-50 for better liquidity

### 7. **Price History Optimization** (Low Priority)
**Issue**: Price history uses linear search for some operations
**Current**: Binary search already implemented for `get_price_change_period`
**Status**: Already optimized

### 8. **Connection Reuse** (Low Priority)
**Status**: Already implemented via `requests.Session()`
**No action needed**

### 9. **Orderbook Caching** (Low Priority)
**Status**: Already implemented with 5-second TTL
**No action needed**

## Code Quality Improvements

### 10. **Error Logging** (Low Priority)
**Issue**: Errors printed to console, not logged to file
**Solution**: Add structured logging to file

### 11. **Configuration Validation** (Low Priority)
**Issue**: No validation for strategy parameters (thresholds, etc.)
**Solution**: Add validation in Config.validate()

### 12. **Metrics Dashboard** (Low Priority)
**Issue**: No easy way to view bot performance metrics
**Solution**: Add summary logging every N scans

## Implementation Priority

### Phase 1: Critical (Implement Now)
1. ✅ Position persistence
2. ✅ Actual P&L tracking
3. ✅ Rate limiting handling

### Phase 2: Performance (Implement Soon)
4. ✅ Parallel market fetching
5. ✅ Stop-loss logic
6. ✅ Volume threshold tuning

### Phase 3: Quality of Life (Implement Later)
7. Error logging to file
8. Configuration validation
9. Metrics dashboard

## Current Performance

**Strengths:**
- ✅ Connection pooling (requests.Session)
- ✅ Orderbook caching (5-second TTL)
- ✅ Binary search for price lookups
- ✅ Shared BTC tracker (update once per scan)
- ✅ Market filtering by series (reduces API calls)
- ✅ Parallel execution for weather forecasts

**Measurements:**
- Scan interval: 5 seconds (15-min strategy)
- BTC update: Every 15 seconds
- Orderbook cache: 5 seconds
- Markets scanned: ~50 per scan

## Recommended Changes

### Quick Wins (< 30 minutes)
1. Increase volume threshold to 20
2. Add rate limit error handling
3. Add P&L update after trades

### Medium Effort (1-2 hours)
4. Implement position persistence
5. Add parallel market fetching
6. Add stop-loss logic

### Future Enhancements
7. Real-time WebSocket integration (currently polling)
8. Machine learning for threshold optimization
9. Multi-exchange price aggregation
10. Backtesting framework
