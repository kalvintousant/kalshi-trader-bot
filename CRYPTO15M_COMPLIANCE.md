# Kalshi CRYPTO15M Contract Rules Compliance

## Contract Rules Summary

Based on the [Kalshi CRYPTO15M Contract Terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/CRYPTO15M.pdf):

### Key Contract Rules

1. **Underlying Asset**: CF Benchmarks Index (e.g., "Bitcoin Real-Time Index")
   - **Contract Specification**: Simple average of CF Benchmarks index for the **60 seconds prior to expiration time**
   - **Our Implementation**: Uses Binance spot price as a proxy for real-time tracking
   - **Note**: BRTI is the official index, but Binance closely tracks it and provides real-time data for latency arbitrage

2. **Price Calculation**: Simple average of CF Benchmarks index for the 60 seconds prior to expiration time
   - **Our Implementation**: Tracks 15-minute price movements to detect latency arbitrage opportunities
   - **Strategy**: Compares real-time Binance moves to Kalshi's slower-updating odds
   - **Note**: We track 15-minute moves for latency detection, but the contract settles based on 60-second average prior to expiration

3. **Market Type**: 15-minute crypto markets
   - **Series Ticker**: `KXBTC15M` (15-minute BTC markets)
   - **Market Question**: "Bitcoin price up or down in next 15 mins?"

4. **Last Trading Date/Time**: Must respect contract expiration
   - **Contract Rule**: Last Trading Date and Time will be `<time>` on `<date>`
   - **Our Implementation**: Only trades markets with `status='open'`
   - Kalshi API automatically filters out expired markets

5. **Expiration**: 
   - **Expiration Value**: Value of Underlying as documented by Source Agency on Expiration Date at Expiration time
   - **Our Implementation**: Relies on Kalshi API status filtering
   - Markets with `status='open'` are tradeable

6. **Settlement**: Settlement value is $1.00
   - **Our Implementation**: Standard contract payout handling

7. **Position Accountability Level**: $25,000 per strike, per Member
   - **Our Implementation**: Configurable via `MAX_POSITION_SIZE` (currently set to 1 contract for testing)
   - **Note**: This is different from hourly BTC contracts which have $1,000,000 position limits

8. **Minimum Tick**: $0.01
   - **Our Implementation**: Standard contract pricing

9. **Payout Criterion**: Above/below/exactly/between price on date at time
   - **Our Implementation**: For "up or down" markets, YES = price goes up, NO = price goes down

## Code Compliance Checklist

✅ **Market Selection**: Only trades `KXBTC15M` series (15-minute markets)  
✅ **Status Checking**: Only trades markets with `status='open'` (respects Last Trading Date/Time)  
✅ **Time Period**: Tracks 15-minute price changes for latency arbitrage detection  
✅ **Price Source**: Uses Binance as CF Benchmarks proxy for real-time tracking  
✅ **Position Limits**: Respects `MAX_POSITION_SIZE` configuration (well below $25,000 limit)  
✅ **Expiration Handling**: Relies on Kalshi API to filter expired markets  
✅ **Minimum Tick**: Uses standard $0.01 pricing  

## Important Notes

- **BRTI vs Binance**: The contract specifies CF Benchmarks index (BRTI), but for latency arbitrage, we use Binance spot price which closely tracks BRTI and provides real-time data
- **60-Second Average**: The contract settles based on 60-second average prior to expiration, but we track 15-minute moves to detect latency opportunities before expiration
- **Position Limits**: 15-minute contracts have $25,000 position accountability level (vs $1M for hourly BTC contracts)
- **Expiration Times**: The bot automatically respects expiration by only trading open markets
- **Last Trading Date/Time**: We rely on Kalshi API's `status='open'` filter to ensure we don't trade after Last Trading Date/Time

## Strategy Implementation

Our latency arbitrage strategy:
1. Tracks real-time BTC price from Binance (proxy for CF Benchmarks)
2. Calculates 15-minute price movements
3. Compares expected price (based on Binance move) to actual Kalshi odds
4. Enters trades when mispricing detected (>2 cents)
5. Exits when pricing catches up or position becomes profitable

This strategy exploits the lag between:
- Real-time Binance price (fast, reflects current market)
- Kalshi odds (slower to update, based on CF Benchmarks)

## Updates Made

1. Updated documentation to reference CRYPTO15M contract rules
2. Noted position accountability level ($25,000 for 15-min contracts)
3. Clarified that we track 15-minute moves for latency detection (contract settles on 60-second average)
4. Ensured all compliance checks are in place
