# Advanced Weather Trading Strategy

## Overview

This implementation follows the weather trading edge guide, using multi-source forecasts, probability distributions, and Edge/EV calculations to identify profitable trading opportunities.

## How It Works

### 1. Multi-Source Data Collection

The bot aggregates forecasts from multiple weather APIs:
- **National Weather Service (NWS)** - Free, no API key needed
- **OpenWeather** - Free tier available
- **Tomorrow.io** - Free tier available
- **AccuWeather** - Free tier available
- **Weatherbit** - Free tier available

### 2. Probability Distribution Building

Instead of using a single forecast, the bot:
- Collects all available forecasts
- Calculates mean and standard deviation
- Builds a probability distribution over 2-degree temperature ranges
- Models uncertainty around the mean forecast

Example:
```
Forecasts: [72°F, 73°F, 74°F]
Mean: 73°F, Std: 1.0°F

Distribution:
- 70-72°F: 15%
- 72-74°F: 68%
- 74-76°F: 15%
- 76-78°F: 2%
```

### 3. Edge Calculation

**Edge = (Our Probability - Market Price) × 100**

Example:
- Our model shows 5% probability for "Above 75°F"
- Market prices YES at 15¢ (15% probability)
- Edge on NO side: (85% - 85¢) = 0% edge
- Edge on YES side: (5% - 15¢) = -10% edge (no trade)

Better example:
- Our model shows 2% probability for "Above 75°F"
- Market prices YES at 25¢ (25% probability)
- Edge on NO side: (98% - 75¢) = +23% edge ✅
- This is a trade!

### 4. Expected Value (EV) Calculation

**EV = (Win Prob × Payout) - (Loss Prob × Stake)**

Example:
- Win probability: 98%
- Payout if we win: $1.00
- Loss probability: 2%
- Stake (price we pay): $0.75
- EV = (0.98 × $1.00) - (0.02 × $0.75) = $0.98 - $0.015 = **+$0.965**

This is a highly positive EV trade!

### 5. Trading Logic

The bot only trades when:
- Edge ≥ 5% (configurable via `min_edge_threshold`)
- EV ≥ $0.001 (configurable via `min_ev_threshold`)

## Configuration

### Minimum Requirements

The bot works with just **NWS (free)** - no API keys needed!

### Optional API Keys

Add to your `.env` file for more forecast sources:
```env
OPENWEATHER_API_KEY=your_key_here
TOMORROWIO_API_KEY=your_key_here
ACCUWEATHER_API_KEY=your_key_here
WEATHERBIT_API_KEY=your_key_here
```

Get free API keys:
- OpenWeather: https://openweathermap.org/api
- Tomorrow.io: https://www.tomorrow.io/weather-api/
- AccuWeather: https://developer.accuweather.com/
- Weatherbit: https://www.weatherbit.io/api

### Strategy Parameters

In `strategies.py`, you can adjust:
- `min_edge_threshold`: Minimum edge % to trade (default: 5%)
- `min_ev_threshold`: Minimum EV in dollars to trade (default: $0.001)

## Example Trade Flow

1. **Market**: "Will NYC high temp be above 75°F tomorrow?"
2. **Forecasts collected**: [72°F, 73°F, 74°F] from NWS, OpenWeather, Tomorrow.io
3. **Probability distribution built**: 
   - 70-72°F: 15%
   - 72-74°F: 68%
   - 74-76°F: 15%
   - 76-78°F: 2%
4. **Our probability for "Above 75°F"**: 2% (sum of 76-78°F range)
5. **Market price**: YES at 25¢ (25% probability)
6. **Edge calculation**: 
   - YES edge: (2% - 25%) = -23% ❌
   - NO edge: (98% - 75%) = +23% ✅
7. **EV calculation**:
   - NO side: (0.98 × $1.00) - (0.02 × $0.75) = +$0.965 ✅
8. **Trade**: Buy NO at 75¢ (or slightly above best bid)

## Advantages

1. **Data-driven**: Uses actual weather forecasts, not guessing
2. **Multi-source**: Reduces reliance on single forecast source
3. **Probabilistic**: Models uncertainty, not just point estimates
4. **Edge-based**: Only trades when there's clear mathematical edge
5. **EV-optimized**: Ensures positive expected value

## Limitations

1. Requires weather API access (NWS is free, others optional)
2. Market title parsing must correctly extract temperature thresholds
3. Forecast accuracy depends on weather service quality
4. Distribution modeling assumes normal distribution (may not always be accurate)

## Next Steps

1. **Add more weather sources** - More forecasts = better consensus
2. **Improve distribution modeling** - Use historical forecast accuracy to weight sources
3. **Add caching** - Cache forecasts to reduce API calls
4. **Backtesting** - Test strategy on historical data
5. **Risk management** - Adjust position sizing based on edge magnitude
