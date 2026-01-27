# Exit Strategy Notes

## Current Status: No Exit Strategies

**Decision Date:** January 27, 2026

### Rationale
- **Testing Phase:** Volume is small, still validating strategy performance
- **Longshot Strategy:** Should hold until settlement to capture full asymmetric payout (10x-100x potential)
- **Conservative Strategy:** Exit logic can be implemented later once we have more data

### Current Behavior
- Bot places buy orders at ASK prices
- Positions are held until market settlement
- No automatic closing of positions

### Future Considerations
When ready to implement exit strategies for conservative trades:
- Take profit targets (e.g., 50%+ unrealized profit)
- Stop loss limits (e.g., -30% unrealized loss)
- Time-based exits (close before settlement if profit locked in)
- Re-evaluation exits (close if edge/EV turns negative)

**Note:** Longshot strategy should remain "hold to settlement" to maximize asymmetric payouts.
