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

### 1. Forecast Caching (24/7 Free-Tier Safe)
- **Cache TTL**: **3 hours (10,800 s)** — default; minimum **156 min (9,360 s)** for all APIs in free tier
- **Benefit**: Keeps Pirate Weather (333/day), Tomorrow.io (500/day), Visual Crossing (1k/day), Open-Meteo (10k/day) within limits
- **Impact**: 36 keys × 8 refreshes/day = 288 calls/day per paid API (~8,640/month for Pirate Weather, under 10k)

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

### 24/7 Free-Tier Safe Configuration
- **Series**: 12 (6 cities × High/Low)
- **Cache keys**: up to 36 (12 series × 3 target dates)
- **FORECAST_CACHE_TTL**: **≥ 9,360 s (156 min)** required; **10,800 s (3 h)** recommended (default)
- **Refreshes per key per day**: 86,400 ÷ 10,800 = 8
- **Calls per day per paid API**: 36 × 8 = **288** (under Tomorrow.io 500, Pirate 333, Visual Crossing 1,000, Open-Meteo 10k)

### Why 3 Hours?
- **Pirate Weather** free tier: **10,000/month** (no daily reset — use ~333/day to stay under 10k for the month).
- 36 keys × (86,400 ÷ TTL) ≤ 333 → TTL ≥ **9,341 s (~156 min)**.
- Default **10,800 s (3 h)** gives a safety margin and keeps all APIs in free tier for 24/7 operation.

### Actual Usage (Typical)
- **Cache Hit Rate**: High (forecasts refreshed every 3 hours)
- **Weatherbit**: Emergency fallback only (when primary sources return zero)

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

### Current Status: ✅ Optimal for 24/7
- All APIs within free tier with **FORECAST_CACHE_TTL=10800** (3 hours)
- Weatherbit emergency-only usage keeps us safe
- 3-hour forecast cache keeps Pirate Weather (10k/month) and Tomorrow.io (500/day) in free tier
- 30-second Kalshi scans catch market movements; forecasts refresh every 3 h

### If Limits Are Approached
1. **Increase FORECAST_CACHE_TTL** (e.g. 14400 = 4 h) to reduce calls further
2. **Disable a source** via env: `ENABLE_PIRATE_WEATHER=false` or `ENABLE_VISUAL_CROSSING=false` if needed
3. **Reduce cities** only if adding more series would exceed limits

### Future Scaling
- Can add 1-2 more cities within free tier limits
- Tomorrow.io has 4% buffer remaining
- Weatherbit has 52% buffer remaining
- NWS has unlimited capacity
