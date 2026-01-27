# Kalshi Trading Bot

Automated trading bot for Kalshi prediction markets, supporting 15-minute BTC markets and daily weather markets.

## Features

- **15-Minute BTC Markets**: Automated trading on Bitcoin price movement predictions
- **Daily Weather Markets**: Trading on temperature predictions for NYC, Chicago, Miami, and Austin
- **Real-time Market Data**: WebSocket support for live orderbook and ticker updates
- **Multiple Strategies**: Modular strategy system for easy extension
- **Risk Management**: Daily loss limits and position sizing controls

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Get Kalshi API credentials**:
   - Create a Kalshi account at https://kalshi.com
   - Generate API keys in Account & Security settings
   - Download your private key (you can only download it once!)

3. **Configure environment**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your API credentials:
   ```
   KALSHI_API_KEY_ID=your_api_key_id
   KALSHI_PRIVATE_KEY_PATH=/path/to/private_key.pem
   ```

4. **Test with demo environment first**:
   Update `.env` to use demo URLs:
   ```
   KALSHI_BASE_URL=https://demo-api.kalshi.co/trade-api/v2
   KALSHI_WS_URL=wss://demo-api.kalshi.co/trade-api/ws/v2
   ```

## Usage

Run the bot:
```bash
python bot.py
```

The bot will:
- Scan open markets every 15 seconds
- Evaluate markets using enabled strategies
- Place trades when opportunities are identified
- Monitor positions and manage risk

## Configuration

Edit `.env` to customize:
- `MAX_POSITION_SIZE`: Maximum contracts per trade (default: 10)
- `MAX_DAILY_LOSS`: Stop trading if daily loss exceeds this (default: $100)
- `ENABLED_STRATEGIES`: Comma-separated list (e.g., `btc_15m,weather_daily`)

## Strategies

### BTC 15-Minute Strategy
- Trades on 15-minute Bitcoin price movement markets
- Uses mean reversion/arbitrage approach
- Looks for price discrepancies between YES and NO sides

### Weather Daily Strategy
- Trades on daily temperature prediction markets
- Can be enhanced with weather API integration
- Currently uses simple contrarian approach

## Extending the Bot

To add a new strategy:
1. Create a class inheriting from `TradingStrategy`
2. Implement `should_trade()` and `get_trade_decision()` methods
3. Add it to `StrategyManager` in `strategies.py`

## Important Notes

- **Start with demo environment**: Always test in demo mode first
- **Risk management**: Set appropriate position sizes and loss limits
- **Rate limits**: The bot includes rate limiting, but be mindful of API limits
- **Market hours**: Some markets only trade during specific hours

## Disclaimer

This bot is for educational purposes. Trading involves risk. Always:
- Test thoroughly in demo environment
- Start with small position sizes
- Monitor the bot closely
- Understand the markets you're trading

## Resources

- [Kalshi API Documentation](https://docs.kalshi.com/)
- [Kalshi Trading Console](https://kalshi.com)
- [Kalshi Academy](https://help.kalshi.com/)
