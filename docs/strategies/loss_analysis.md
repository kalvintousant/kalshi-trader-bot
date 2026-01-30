# Loss Analysis & Prediction Accuracy

## What we learned from the Jan 29 losses

From the NWS-based review, **14 losing bets** vs **16 winning**. Many losses shared a pattern:

### 1. **Losses were often "close to threshold"**

| Market | Our side | Actual (NWS) | Threshold | Miss by |
|--------|----------|--------------|-----------|---------|
| Chicago B18.5 | NO | 17.6° | 18.5° | 0.9° |
| LA B81.5 | NO | 80.6° | 81.5° | 0.9° |
| Denver B47.5 | NO | 46.4° | 47.5° | 1.1° |
| Austin T70 | NO | 72° | 70° | 2° (wrong side) |
| Chicago B14.5 | YES | 17.6° | 14.5° | 3.1° (forecast too low) |

When the **mean forecast is within 1–2° of the threshold**, outcome is highly uncertain; small forecast error flips the result. Those are "coin flip" markets.

### 2. **Were they low confidence?**

We don’t store confidence per fill. We can infer:

- **Longshot vs conservative:** Review script infers from fill price (≤10¢ → longshot). Check the WRONG section for "(longshot)" vs "(conservative)".
- **Longshot losses are acceptable** — we’re buying cheap optionality; some will lose.
- **Conservative losses** — we require 5%+ edge and positive EV; if the CI overlapped the market (REQUIRE_HIGH_CONFIDENCE=false), we were taking marginal edges. Tightening helps.

### 3. **Criteria you can change**

| Goal | Option | Effect |
|------|--------|--------|
| Fewer "coin flip" losses | `MIN_DEGREES_FROM_THRESHOLD=2` | Skip single-threshold markets when \|forecast − threshold\| < 2° |
| Stricter conservative | `REQUIRE_HIGH_CONFIDENCE=true` | Only trade when CI does not overlap market price (fewer trades, higher bar) |
| Higher bar for edge | `MIN_EDGE_THRESHOLD=7` or `8` | Fewer trades, only stronger edges |
| Less longshot size | Lower `LONGSHOT_POSITION_MULTIPLIER` or require higher `LONGSHOT_MIN_EDGE` | Same number of longshot bets, smaller size |

### 4. **Is it too early to tell?**

- **One day** is not enough to judge strategy. 16W–14L is close to 50%; with more days we’ll see if win rate and EV hold.
- **Use the review script** after each day: `python3 review_trades_today.py` — check whether wrongs are mostly longshot (ok) or conservative (consider MIN_DEGREES_FROM_THRESHOLD or REQUIRE_HIGH_CONFIDENCE).
- **Optional:** set `MIN_DEGREES_FROM_THRESHOLD=2` now to avoid the clearest "forecast right on the boundary" trades; you can set it back to 0 after more data.

## Summary

- Many losses were **close to threshold** (forecast ~1–2° from boundary). Optional **MIN_DEGREES_FROM_THRESHOLD** skips those.
- **Longshot losses** are expected; **conservative losses** are the ones to reduce with higher confidence or distance-from-threshold.
- **Too early to tell** overall; use the review output (right/wrong + longshot vs conservative) and the options above to tune as more data comes in.
