#!/usr/bin/env python3
"""Check current exposure by base market"""

from src.kalshi_client import KalshiClient
from src.config import Config

Config.validate()
client = KalshiClient()

# Get current positions
positions = client.get_positions()
print('=== CURRENT POSITIONS ===')
for pos in positions:
    ticker = pos.get('ticker', '')
    contracts = pos.get('position', 0)
    exposure = pos.get('market_exposure', 0) / 100.0
    print(f'{ticker}: {contracts} contracts, ${exposure:.2f} exposure')

# Get resting orders
print('\n=== RESTING ORDERS ===')
orders = client.get_orders(status='resting', use_cache=False)
for order in orders:
    ticker = order.get('ticker', '')
    side = order.get('side', '')
    remaining = order.get('remaining_count', 0)
    price = order.get('yes_price', 0) if side == 'yes' else order.get('no_price', 0)
    dollars = (remaining * price) / 100.0
    print(f'{ticker}: {remaining} {side.upper()} @ {price}¢ = ${dollars:.2f}')

# Group by base market
print('\n=== EXPOSURE BY BASE MARKET ===')
base_markets = {}
for pos in positions:
    ticker = pos.get('ticker', '')
    parts = ticker.split('-')
    if len(parts) >= 2:
        base = '-'.join(parts[:2])
    else:
        base = ticker
    
    if base not in base_markets:
        base_markets[base] = {'contracts': 0, 'dollars': 0.0}
    
    contracts = abs(pos.get('position', 0))
    base_markets[base]['contracts'] += contracts
    # Use estimated cost basis (47¢ per contract average, based on actual trade data)
    estimated_cost = contracts * 0.47
    base_markets[base]['dollars'] += estimated_cost

for order in orders:
    ticker = order.get('ticker', '')
    parts = ticker.split('-')
    if len(parts) >= 2:
        base = '-'.join(parts[:2])
    else:
        base = ticker
    
    if base not in base_markets:
        base_markets[base] = {'contracts': 0, 'dollars': 0.0}
    
    side = order.get('side', '')
    remaining = order.get('remaining_count', 0)
    price = order.get('yes_price', 0) if side == 'yes' else order.get('no_price', 0)
    
    base_markets[base]['contracts'] += remaining
    base_markets[base]['dollars'] += (remaining * price) / 100.0

print(f'\nMAX_DOLLARS_PER_MARKET limit: ${Config.MAX_DOLLARS_PER_MARKET:.2f}')
print(f'MAX_CONTRACTS_PER_MARKET limit: {Config.MAX_CONTRACTS_PER_MARKET}\n')

for base, exp in sorted(base_markets.items()):
    status = ''
    if exp['dollars'] > Config.MAX_DOLLARS_PER_MARKET:
        status = f'  ⚠️  EXCEEDS ${Config.MAX_DOLLARS_PER_MARKET:.2f} LIMIT!'
    print(f'{base}: {exp["contracts"]} contracts, ${exp["dollars"]:.2f}{status}')
