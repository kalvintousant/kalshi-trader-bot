#!/usr/bin/env python3
"""Show positions that exceed the $3 per base market limit"""

from src.kalshi_client import KalshiClient
from src.config import Config

Config.validate()
client = KalshiClient()

# Get current positions
positions = client.get_positions()

# Group by base market
base_markets = {}
for pos in positions:
    ticker = pos.get('ticker', '')
    parts = ticker.split('-')
    if len(parts) >= 2:
        base = '-'.join(parts[:2])
    else:
        base = ticker
    
    if base not in base_markets:
        base_markets[base] = []
    
    contracts = abs(pos.get('position', 0))
    if contracts > 0:  # Only include non-zero positions
        estimated_cost = contracts * 0.47
        base_markets[base].append({
            'ticker': ticker,
            'contracts': contracts,
            'cost': estimated_cost,
            'market_value': abs(pos.get('market_exposure', 0) / 100.0)
        })

# Show markets that exceed limit
print('=' * 80)
print(f'POSITIONS EXCEEDING ${Config.MAX_DOLLARS_PER_MARKET:.2f} LIMIT')
print('=' * 80)

for base, positions_list in sorted(base_markets.items()):
    total_cost = sum(p['cost'] for p in positions_list)
    total_contracts = sum(p['contracts'] for p in positions_list)
    
    if total_cost > Config.MAX_DOLLARS_PER_MARKET:
        total_market_value = sum(p['market_value'] for p in positions_list)
        excess = total_cost - Config.MAX_DOLLARS_PER_MARKET
        
        print(f'\n{base}:')
        print(f'  Total: {total_contracts} contracts, ${total_cost:.2f} cost (${total_market_value:.2f} current value)')
        print(f'  EXCESS: ${excess:.2f} over limit')
        print(f'  Positions:')
        
        for p in sorted(positions_list, key=lambda x: x['cost'], reverse=True):
            pnl = p['market_value'] - p['cost']
            pnl_pct = (pnl / p['cost'] * 100) if p['cost'] > 0 else 0
            print(f'    {p["ticker"]}: {p["contracts"]} contracts, ${p["cost"]:.2f} cost, ${p["market_value"]:.2f} value ({pnl_pct:+.1f}%)')

print('\n' + '=' * 80)
print('NOTE: These positions were accumulated before protection rules were fixed.')
print('The bot will NOT add more to these markets (protection is now working).')
print('=' * 80)
