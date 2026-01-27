# Kalshi BTC Contract Rules Compliance

## Contract Rules Summary

Based on the [Kalshi BTC Contract Terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/BTC.pdf):

### Key Contract Rules

1. **Underlying Asset**: CF Bitcoin Real-Time Index (BRTI)
   - **Our Implementation**: Uses Binance spot price as a proxy for real-time tracking
   - **Note**: BRTI is the official index, but Binance provides real-time data for latency arbitrage

2. **Price Calculation**: Simple average of BRTI for the minute (60 seconds) prior to expiration time
   - **Our Implementation**: Tracks hourly price movements to match hourly market expiration periods
   - **Strategy**: Compares real-time Binance moves to Kalshi's slower-updating odds

3. **Market Type**: Hourly markets (not 15-minute)
   - **Series Ticker**: `KXBTC` (hourly BTC markets)
   - **Our Implementation**: Updated from `KXBTC15M` to `KXBTC`

4. **Last Trading Date/Time**: Must respect contract expiration
   - **Our Implementation**: Only trades markets with `status='open'`
   - Kalshi API automatically filters out expired markets

5. **Expiration Date**: First minute after expiration time that data is available
   - **Our Implementation**: Relies on Kalshi API status filtering
   - Markets with `status='open'` are tradeable

6. **Settlement**: Settlement value is $1.00
   - **Our Implementation**: Standard contract payout handling

7. **Position Limits**: $1,000,000 per strike, per Member
   - **Our Implementation**: Configurable via `MAX_POSITION_SIZE` (currently set to 1 contract for testing)

## Code Compliance Checklist

✅ **Market Selection**: Only trades `KXBTC` series (hourly markets)  
✅ **Status Checking**: Only trades markets with `status='open'`  
✅ **Time Period**: Uses 1-hour price change calculations (not 15-minute)  
✅ **Price Source**: Uses Binance as BRTI proxy for real-time tracking  
✅ **Position Limits**: Respects `MAX_POSITION_SIZE` configuration  
✅ **Expiration Handling**: Relies on Kalshi API to filter expired markets  

## Notes

- **BRTI vs Binance**: The contract specifies BRTI, but for latency arbitrage, we use Binance spot price which closely tracks BRTI and provides real-time data
- **Hourly Markets**: Confirmed that Kalshi BTC markets are hourly (`KXBTC`), not 15-minute (`KXBTC15M`)
- **Expiration Times**: The bot automatically respects expiration by only trading open markets

## Updates Made

1. Changed series ticker from `KXBTC15M` to `KXBTC`
2. Updated strategy to use 1-hour price changes instead of 15-minute
3. Updated strategy class name from `BTC15MinStrategy` to `BTCHourlyStrategy`
4. Added contract rules compliance documentation
5. Updated configuration to use `btc_hourly` instead of `btc_15m`
