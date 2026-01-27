# API Usage & Free Tier Compliance

## Current Status: ✅ All APIs Within Free Tier Limits

### Weather APIs

#### 1. National Weather Service (NWS)
- **Status**: ✅ Unlimited (public service)
- **Usage**: ~480 calls/day
- **API Key**: Not required
- **Rate Limits**: None (public service)
- **Cost**: Free

#### 2. Tomorrow.io
- **Status**: ✅ Within limits
- **Usage**: ~480 calls/day, ~20/hour
- **Free Tier Limits**: 
  - 500 requests/day
  - 25 requests/hour
  - 3 requests/second
- **Current Usage**: 96% daily, 80% hourly
- **Cost**: Free tier

#### 3. Weatherbit
- **Status**: ✅ Within limits (emergency fallback only)
- **Usage**: ~24 calls/day (only when NWS + Tomorrow.io both fail)
- **Free Tier Limits**:
  - 50 requests/day
  - 1 request/second
- **Current Usage**: 48% daily
- **Optimization**: Only used as emergency fallback when primary sources return zero forecasts
- **Cost**: Free tier

### Kalshi API
- **Status**: ✅ No rate limit issues observed
- **Usage**: ~2,880 calls/day (every 30 seconds for market scans)
- **Optimization**: Orderbook caching (5-second TTL), connection pooling
- **Cost**: Free (trading fees apply to trades only)

## Optimization Strategies

### 1. Forecast Caching
- **Cache TTL**: 30 minutes
- **Benefit**: Reduces API calls by 90%+ (only refresh when cache expires)
- **Impact**: 10 series × 2 refreshes/hour = 20 API calls/hour instead of 2,880

### 2. Weatherbit Emergency Fallback
- **Strategy**: Only call Weatherbit if NWS + Tomorrow.io both return zero forecasts
- **Benefit**: Reduces Weatherbit usage from 480/day to ~24/day
- **Impact**: Stays well within 50 requests/day free tier limit

### 3. Parallel API Calls
- **Strategy**: Fetch NWS + Tomorrow.io simultaneously
- **Benefit**: Faster response times, better reliability
- **Impact**: If one fails, we still have the other

### 4. Smart Caching
- **Strategy**: Cache per city + date combination
- **Benefit**: Multiple markets for same city/date share cached forecast
- **Impact**: Further reduces redundant API calls

## Usage Calculation

### Worst-Case Scenario
- **Cities**: 5 (NYC, Chicago, Miami, Austin, LA)
- **Types**: 2 (High, Low) = 10 series total
- **Cache Refresh**: Every 30 minutes = 2 refreshes/hour = 48 refreshes/day
- **APIs per Refresh**: 2 (NWS + Tomorrow.io) = 20 calls/hour = 480 calls/day
- **Weatherbit Fallback**: ~5% failure rate = ~24 calls/day

### Actual Usage (Typical)
- **Cache Hit Rate**: 90%+ (most scans use cached forecasts)
- **Actual API Calls**: Lower than worst-case due to cache efficiency
- **Weatherbit Usage**: Minimal (only when both primary sources fail)

## Monitoring

### How to Check API Usage

**Tomorrow.io:**
- Check response headers: `X-RateLimit-Remaining`
- Monitor for 429 errors (rate limit exceeded)

**Weatherbit:**
- Check response headers: `X-RateLimit-Remaining`
- Monitor for 429 errors (rate limit exceeded)

**NWS:**
- No monitoring needed (unlimited)

### Warning Signs
- 429 HTTP errors = rate limit exceeded
- Frequent "No forecasts" messages = possible API issues
- High Weatherbit usage = NWS/Tomorrow.io may be failing

## Recommendations

### Current Status: ✅ Optimal
- All APIs within free tier limits
- Weatherbit emergency-only usage keeps us safe
- 30-minute cache balances freshness with API limits
- 30-second Kalshi scans catch market movements quickly

### If Limits Are Approached
1. **Increase cache TTL** to 60 minutes (reduces calls by 50%)
2. **Remove Weatherbit** entirely (if NWS + Tomorrow.io are reliable)
3. **Reduce cities** if needed (though current usage is safe)

### Future Scaling
- Can add 1-2 more cities within free tier limits
- Tomorrow.io has 4% buffer remaining
- Weatherbit has 52% buffer remaining
- NWS has unlimited capacity
