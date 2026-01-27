#!/usr/bin/env python3
"""
Kalshi Weather Trading Bot
Main entry point for the trading bot
"""
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.kalshi_client import KalshiClient
from src.strategies import StrategyManager
from src.config import Config

sys.path.insert(0, project_root)

from src.kalshi_client import KalshiClient
from src.strategies import StrategyManager
from src.config import Config

