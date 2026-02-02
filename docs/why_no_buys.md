# Why Nothing Is Buying — Checklist

Common reasons the bot doesn’t place buys and how to check them.

---

## 1. **Daily loss limit**

- **Condition:** `daily_pnl <= -MAX_DAILY_LOSS` (e.g. -$10).
- **Effect:** Trading is paused for the rest of the day.
- **Log:** `⛔ Daily loss limit reached!` and `Pausing trading due to daily loss limit`.
- **Fix:** Wait until next day or raise `MAX_DAILY_LOSS` in `.env` (with care).

---

## 2. **Time of day — “past report time”**

- **Condition:** For **today’s** markets: high of day assumed after **4 PM local**, low after **8 AM local**.
- **Effect:** All **today’s** weather markets are skipped (no new buys).
- **Log:** `📊 SKIP {ticker}: today's market past report time — high/low of day likely already occurred`.
- **Why:** Official high/low is usually in by then; buying later is low edge.
- **Fix:** None intended; tomorrow’s markets still trade. If you want to allow today’s markets later, we’d need to relax or remove this cutoff (not recommended).

---

## 3. **Pre-filter (before strategy)**

Markets are skipped if:

- Not a weather series (not in `WEATHER_SERIES` / KXHIGH / KXLOW).
- Status not `open` or `active`.
- Volume &lt; `MIN_MARKET_VOLUME` (default 15).

**Logs:** `📊 SKIP {ticker}: not a weather series` / `status=...` / `volume X < 15`.

---

## 4. **Strategy gates (why a market doesn’t trigger a buy)**

After passing the pre-filter, a market can still not buy because of:

| Reason | Log / condition |
|--------|------------------|
| No series/date/threshold | `could not determine series` / `extract date` / `extract temp threshold` |
| Outcome already known | `outcome already determined` (e.g. observed high already above threshold) |
| No forecasts | `no forecasts for {series} on {date}` |
| Forecast too close to threshold | `forecast X° within Y° of threshold` (if `MIN_DEGREES_FROM_THRESHOLD` &gt; 0) |
| No prob dist / empty orderbook | `could not build probability distribution` / `empty orderbook` |
| At position limit | `at position limit` (e.g. $3 or 25 contracts per market) |
| **Past report time** | `today's market past report time` (today’s markets only) |
| Longshot: price &gt; 10¢ or prob &lt; 50% or edge &lt; 30% | No trade for longshot branch |
| Conservative: edge &lt; 5% or EV &lt; $0.01 or (if required) CI overlaps | `📊 SKIP {ticker}: best edge X% < 5%` or similar |
| No capacity / size &lt; min | `no capacity` / `size X < MIN_ORDER_CONTRACTS` |
| Ask &gt; 99¢ | `no value at 100¢` or `BLOCKED ... MAX_BUY_PRICE_CENTS` |

So “nothing buying” is often: **all markets are today’s and it’s past report time**, or **no market has edge/EV above threshold**, or **you’re at position/dollar limit on every candidate**.

---

## 5. **Scan cadence**

- Bot runs a scan about **every 30 seconds** (weather).
- No buys will show until at least one full scan has run and found a candidate that passes all checks.

---

## 6. **Quick checks**

1. **Time:** If it’s evening (e.g. after 4 PM local in your cities), **today’s** markets are intentionally skipped; **tomorrow’s** can still trade.
2. **Logs:** Run with default logging and search for `📊 SKIP` and `⛔` to see the exact reason per market.
3. **Config:** Confirm `MIN_EDGE_THRESHOLD`, `MIN_EV_THRESHOLD`, `REQUIRE_HIGH_CONFIDENCE`, `MIN_DEGREES_FROM_THRESHOLD`, `MIN_ORDER_CONTRACTS`, `MAX_BUY_PRICE_CENTS`, `LONGSHOT_LOW_CUTOFF_HOUR` — any of these can make the bot much pickier and reduce buys.
4. **LOW (min-temp) markets:** Today's low markets are only eligible before **8 AM local** in each city (configurable via `LONGSHOT_LOW_CUTOFF_HOUR`). After that, only tomorrow's low markets can be bought.

---

## Summary

- **Limitation that often explains “nothing buying”:** **Today’s markets are skipped after “report time” (4 PM high / 8 AM low local).** So in the evening, only **tomorrow’s** (and later) markets are eligible; if there are few of those or none with enough edge, you’ll see no buys.
- Other limits (daily loss, pre-filter, strategy gates, position/dollar caps) can also block buys; the logs and this checklist are the way to see which one is acting.
