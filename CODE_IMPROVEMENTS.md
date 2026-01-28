# Code Review & Improvement Suggestions

## 🔴 Critical Issues

### 1. **Orderbook Bid Price Access (CRITICAL BUG)**
**Location:** `src/strategies.py` lines 805-806

**Issue:** Using `[0][0]` to get best bid, but Kalshi arrays are sorted **ascending** (lowest to highest). The best bid is the **last** element, not first.

**Current Code:**
```python
best_yes_bid = yes_orders[0][0] if yes_orders else yes_market_price
best_no_bid = no_orders[0][0] if no_orders else no_market_price
```

**Fix:**
```python
# Arrays are sorted ASCENDING, so best bid (highest) is LAST element
best_yes_bid = yes_orders[-1][0] if yes_orders else yes_market_price
best_no_bid = no_orders[-1][0] if no_orders else no_market_price
```

**Impact:** Edge calculations are using the **lowest** bid instead of **highest** bid, which makes opportunities look worse than they are.

---

### 2. **Incorrect Orderbook Comment**
**Location:** `src/strategies.py` lines 785-787

**Issue:** Comment says "sorted by price descending" but Kalshi docs confirm arrays are **ascending**.

**Fix:** Update comment to reflect ascending order.

---

## 🟡 Important Improvements

### 3. **Series Name Mismatch**
**Location:** `src/config.py` vs `src/weather_data.py`

**Issue:** Config has `KXHIGHCHI`, `KXHIGHMIA`, `KXHIGHAUS` but need to verify these match actual Kalshi series names.

**Action:** Verify actual Kalshi series tickers match these names. If they're `KXHIGHCH`, `KXHIGHMI`, `KXHIGHAU`, update config.

---

### 4. **Missing Position Exit Logic for Weather Strategy**
**Location:** `src/strategies.py` - `WeatherDailyStrategy`

**Issue:** Weather strategy doesn't track positions or exit logic like BTC strategies do. Once a trade is placed, there's no mechanism to:
- Exit profitable positions early
- Exit if edge disappears
- Track filled positions

**Suggestion:** Add position tracking similar to BTC strategies:
```python
self.active_positions = {}  # Track filled positions
def _check_exit(self, market, orderbook, market_ticker):
    # Exit logic for weather positions
```

---

### 5. **Bare Exception Clauses**
**Location:** `src/bot.py` line 105

**Issue:** Bare `except:` clause catches all exceptions including system exits.

**Current:**
```python
except:
    pass  # If we can't parse time, check anyway
```

**Fix:**
```python
except (ValueError, AttributeError, KeyError) as e:
    # Log specific error but continue
    pass
```

---

### 6. **Logging Instead of Print Statements**
**Location:** Throughout codebase

**Issue:** Using `print()` instead of proper logging module makes it hard to:
- Control log levels
- Route logs to files
- Filter by component

**Suggestion:** Replace with Python `logging` module:
```python
import logging
logger = logging.getLogger(__name__)
logger.info("Message")
logger.error("Error", exc_info=True)
```

---

## 🟢 Code Quality Improvements

### 7. **Remove Commented BTC Code**
**Location:** `src/strategies.py` lines 107-550

**Issue:** Large blocks of commented-out BTC strategy code make file harder to read.

**Suggestion:** Remove entirely or move to separate file if you want to keep for reference.

---

### 8. **Error Handling in Order Cancellation**
**Location:** `src/bot.py` line 218

**Issue:** Generic exception handling in `check_and_cancel_stale_orders` could hide important errors.

**Suggestion:** Be more specific about which errors to catch and log.

---

### 9. **Date Extraction Edge Cases**
**Location:** `src/strategies.py` `_extract_market_date()`

**Issue:** Date parsing has multiple fallbacks but could fail silently.

**Suggestion:** Add validation that extracted date is reasonable (not 1900 or 2100).

---

### 10. **Orderbook Cache TTL**
**Location:** `src/kalshi_client.py` line 30

**Issue:** 5-second cache might be too long for fast-moving markets.

**Suggestion:** Consider reducing to 2-3 seconds or make it configurable.

---

### 11. **Portfolio API Calls**
**Location:** Multiple places calling `get_portfolio()`

**Issue:** Portfolio is fetched multiple times per scan (in strategy, in bot, etc.).

**Suggestion:** Cache portfolio data with short TTL (5-10 seconds) to reduce API calls.

---

### 12. **Market Date Validation**
**Location:** `src/strategies.py` line 722

**Issue:** Allows markets up to 7 days in future, but weather forecasts degrade quickly.

**Suggestion:** Consider limiting to 2-3 days for better forecast accuracy.

---

### 13. **Confidence Interval Usage**
**Location:** `src/strategies.py` lines 942-943

**Issue:** Conservative mode requires confidence interval to not overlap with market price, which might be too strict.

**Suggestion:** Consider allowing trades if CI is mostly above/below market (e.g., 80% of CI).

---

### 14. **Fill Price Estimation**
**Location:** `src/strategies.py` lines 826-829

**Issue:** `estimate_fill_price` uses wrong array direction (assumes descending).

**Fix:** Since arrays are ascending, iterate from end (highest prices first for asks).

---

### 15. **Rate Limiting**
**Location:** `src/kalshi_client.py`

**Issue:** No tracking of API call frequency to prevent hitting rate limits.

**Suggestion:** Add rate limit tracking and automatic throttling.

---

## 📊 Performance Optimizations

### 16. **Parallel Market Evaluation**
**Location:** `src/bot.py` `scan_and_trade()`

**Issue:** Markets are evaluated sequentially.

**Suggestion:** Use `ThreadPoolExecutor` to evaluate multiple markets in parallel (with rate limiting).

---

### 17. **Orderbook Caching Strategy**
**Location:** `src/kalshi_client.py`

**Issue:** Orderbook cache is per-market but fetched once per scan.

**Suggestion:** Pre-fetch orderbooks for all markets in parallel before evaluation.

---

### 18. **Forecast Cache Optimization**
**Location:** `src/weather_data.py`

**Issue:** Forecast cache TTL is 30 minutes, but forecasts might update more frequently.

**Suggestion:** Consider shorter TTL (15-20 minutes) or cache invalidation on new forecasts.

---

## 🛡️ Risk Management

### 19. **Position Size Validation**
**Location:** `src/strategies.py` position sizing logic

**Issue:** Multiple caps (contracts, dollars, Kelly) but no validation that final size is reasonable.

**Suggestion:** Add sanity check: `position_size = max(1, min(position_size, reasonable_max))`

---

### 20. **Daily Loss Limit Check Frequency**
**Location:** `src/bot.py` line 239

**Issue:** Only checked once per scan (every 30 seconds).

**Suggestion:** Check more frequently or after each trade to stop immediately if limit hit.

---

### 21. **Order Status Monitoring**
**Location:** `src/bot.py` `check_filled_orders()`

**Issue:** Only checks filled orders, doesn't monitor for partial fills or order rejections.

**Suggestion:** Track all order statuses and handle partial fills, rejections, etc.

---

## 🔧 Code Organization

### 22. **Constants Should Be in Config**
**Location:** Various files

**Issue:** Magic numbers scattered throughout code (e.g., `longshot_max_price = 10`, `min_edge_threshold = 5.0`).

**Suggestion:** Move all strategy parameters to `Config` class or separate config file.

---

### 23. **Type Hints**
**Location:** Throughout codebase

**Issue:** Missing type hints make code harder to understand and maintain.

**Suggestion:** Add type hints to all function signatures.

---

### 24. **Docstrings**
**Location:** Some methods missing docstrings

**Issue:** Complex methods like `build_probability_distribution` need better documentation.

**Suggestion:** Add comprehensive docstrings explaining algorithms and parameters.

---

## 🚀 Feature Enhancements

### 25. **Position Exit Strategy**
**Suggestion:** Add logic to exit weather positions:
- If market price moves against us significantly
- If edge disappears (re-evaluate periodically)
- Take profit at certain thresholds

---

### 26. **Market Settlement Tracking**
**Suggestion:** Track when markets settle and update forecast error history automatically.

---

### 27. **Performance Metrics**
**Suggestion:** Track and log:
- Win rate
- Average edge
- Average EV
- Fill rate
- Slippage

---

### 28. **Alert System**
**Suggestion:** Add alerts for:
- Large losses
- API errors
- Missing forecasts
- Unusual market conditions

---

## Priority Ranking

1. **🔴 CRITICAL:** Fix bid price access (issue #1)
2. **🔴 CRITICAL:** Fix fill price estimation (issue #14)
3. **🟡 HIGH:** Add position exit logic (issue #4)
4. **🟡 HIGH:** Fix series name consistency (issue #3)
5. **🟡 MEDIUM:** Replace print with logging (issue #6)
6. **🟡 MEDIUM:** Fix bare except clauses (issue #5)
7. **🟢 LOW:** Code cleanup and organization (issues #7, #22, #23)
