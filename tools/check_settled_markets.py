"""
Quick script to check for settled markets and populate outcomes.csv
"""
import sys
import logging
from src.kalshi_client import KalshiClient
from src.weather_data import WeatherDataAggregator
from src.outcome_tracker import OutcomeTracker
from src.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main():
    print("Checking for settled markets...")
    
    # KalshiClient will read credentials from Config automatically
    client = KalshiClient()
    
    weather_agg = WeatherDataAggregator()
    tracker = OutcomeTracker(client, weather_agg)
    
    # Check for settled positions
    tracker.run_outcome_check()
    
    # Generate performance report
    report = tracker.generate_performance_report()
    
    if report and 'overall' in report:
        print("\n" + "="*60)
        print("PERFORMANCE SUMMARY")
        print("="*60)
        overall = report['overall']
        print(f"Total Trades: {overall['total_trades']}")
        print(f"Win Rate: {overall['win_rate']:.1%}")
        print(f"Total P&L: ${overall['total_pnl']:.2f}")
        print("="*60)
    else:
        print("\n❌ No settled positions found yet.")
        print("\n💡 Markets typically settle the day after they expire.")
        print("   Yesterday's (Jan 30) markets should settle today (Jan 31).")
        print("   Check back later today or tomorrow for results.")

if __name__ == "__main__":
    main()
