#!/usr/bin/env python3
"""Force start bot with clean module cache"""
import sys
import os

# Set working directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

# Clear any cached modules
modules_to_clear = [m for m in list(sys.modules.keys()) if m.startswith('src.')]
for mod in modules_to_clear:
    del sys.modules[mod]

print("Starting bot with fresh imports...")
print("=" * 70)

try:
    from src.bot import KalshiTradingBot
    
    print("✅ Bot class imported")
    print("Creating bot instance...")
    
    bot = KalshiTradingBot()
    
    print("✅ Bot created successfully!")
    print("=" * 70)
    print("🎉 Bot is now running!")
    print("=" * 70)
    
    # Run the bot
    bot.run()
    
except Exception as e:
    print(f"\n❌ ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
