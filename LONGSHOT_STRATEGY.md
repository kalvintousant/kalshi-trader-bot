# Longshot Weather Trading Strategy

## Concept: Buy Cheap Certainty

Inspired by a successful Polymarket weather bot that turned $27 → $63,853 using asymmetric longshot trades.

## Core Principle

**Hunt for extreme mispricings where:**
- Market price is very low (1-10 cents = 1-10% odds)
- But forecasts show much higher probability (50-80%+)
- Result: Cheap shares with massive upside (10-100x return)

## Strategy Parameters

### Longshot Mode (NEW)
```python
longshot_max_price = 10¢     # Only buy if ≤ 10¢ (cheap shares)
longshot_min_edge = 30%      # Require massive edge (not just 5%)
longshot_min_prob = 50%      # Our forecast must show ≥50% (certainty)
position_multiplier = 3x     # Trade 3x normal size (asymmetric bet)
```

### Conservative Mode (EXISTING)
```python
min_edge = 5%               # Standard quality threshold
min_ev = $0.01             # Minimum expected value
position_size = 1          # Normal size
```

## Why This Works

### Math Example

**Scenario:** Market says 10% chance, forecasts say 80% chance

```
Cost per contract: $0.10
Payout if right: $1.00
Return: 10x

Position: 3 contracts = $0.30 risk

Over 3 similar trades (33% win rate):
  • Loss: -$0.30, -$0.30 = -$0.60
  • Win: +$3.00 (3 contracts × $1.00)
  • Net: +$2.40 profit (400% return)
```

### Key Insight

**You don't need a high win rate when payouts are asymmetric!**

- Conservative: Win 70% of time, 1.2x payout → steady gains
- Longshot: Win 33% of time, 10x payout → explosive gains

## Real-World Example

```
Market: "Austin high above 85°F tomorrow?"
Market price: 8¢ (8% probability)
Forecasts: 73°F, 74°F, 75°F → prob ~5% actually

❌ NO TRADE (our prob is LOWER than market)

Market: "Austin high below 65°F tomorrow?"
Market price: 5¢ (5% probability)  
Forecasts: 73°F, 74°F, 75°F → prob ~95% below won't happen
Wait... this is inverted.
Market asking if BELOW 65°F (NO should be 95%)
NO price: 5¢ → Should be 95¢!

✅ LONGSHOT: Buy NO at 5¢
  • Cost: $0.05 per contract
  • Our probability: 95%
  • Edge: 90% (95% - 5%)
  • If right: $1.00 payout = 20x return
  • Position: 3 contracts = $0.15 total risk
```

## Trade Execution

### Longshot Criteria (ALL must be met):
1. ✅ Market price ≤ 10¢
2. ✅ Our probability ≥ 50%
3. ✅ Edge ≥ 30%
4. ✅ Volume ≥ 15 contracts

### Position Sizing:
- Longshot: 3 contracts (3x normal)
- Conservative: 1 contract
- Max daily loss: $20 (applies to both)

## Risk Management

**Even with lower win rates, asymmetric payouts create positive expectancy:**

```
Expected Value = (Win Prob × Payout) - (Loss Prob × Cost)
EV = (0.33 × $3.00) - (0.67 × $0.30)
EV = $0.99 - $0.20
EV = +$0.79 per trade set
```

## Combined Strategy

The bot now runs BOTH modes simultaneously:

1. **Longshot mode** checks first (priority for big wins)
2. **Conservative mode** as fallback (consistent gains)

Result: Best of both worlds!
- Steady income from conservative trades
- Explosive upside from longshot trades
- Diversified risk profile

## Success Metrics

**Longshot performance indicators:**
- Win rate: 25-40% (lower is OK)
- Average return per win: 5-20x
- Position size: 3x normal
- Expected profit: High variance, high reward

**Conservative performance indicators:**
- Win rate: 60-80% (higher expected)
- Average return per win: 1.2-1.5x
- Position size: 1x normal
- Expected profit: Steady, predictable

## Why Weather Markets Are Perfect

1. **Highly modeled**: Multiple professional APIs
2. **Fast updates**: Forecasts change hourly
3. **Market lag**: Prediction markets slower to adjust
4. **Low competition**: Most traders avoid weather
5. **Clear settlement**: Objective temperature reading

The combination of cheap mispricings and forecast certainty creates the perfect asymmetric opportunity.
