"""
Backfill Historical Outcomes - Fetch actual temperatures for past trades

This script:
1. Fetches actual fills from Kalshi API (authoritative source)
2. For markets dated in the past, fetches actual observed temperatures from NWS
3. Matches fills with actual outcomes to populate outcomes.csv
4. This builds historical data for data source analysis

NOTE: Uses API fills, not trades.csv (which logs order attempts, not actual fills)
"""

import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import re
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

from src.weather_data import WeatherDataAggregator, extract_threshold_from_market
from src.kalshi_client import KalshiClient
from src.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HistoricalBackfiller:
    """Backfill outcomes.csv with actual temperatures from past dates using API fills"""

    def __init__(self):
        self.weather_agg = WeatherDataAggregator()
        self.client = KalshiClient()
        self.outcomes_file = Path("data/outcomes.csv")
        
    def parse_date_from_ticker(self, ticker: str) -> Optional[datetime]:
        """Parse date from ticker format like KXHIGHNY-26JAN31-B22.5"""
        try:
            # Extract date part: 26JAN31
            match = re.search(r'-(\d{2})([A-Z]{3})(\d{2})-', ticker)
            if not match:
                return None
            
            year_str, month_str, day_str = match.groups()
            
            # Map month abbreviations
            month_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
            
            year = 2000 + int(year_str)
            month = month_map[month_str.upper()]
            day = int(day_str)
            
            return datetime(year, month, day)
        except Exception as e:
            logger.debug(f"Error parsing date from {ticker}: {e}")
            return None
    
    def get_series_ticker_from_market_ticker(self, market_ticker: str) -> Optional[str]:
        """Extract series ticker (e.g., KXHIGHNY) from market ticker"""
        # Market ticker format: KXHIGHNY-26JAN31-B22.5
        # Series ticker: KXHIGHNY
        if '-' in market_ticker:
            return market_ticker.split('-')[0]
        return None
    
    def get_actual_temp_for_date(self, series_ticker: str, target_date: datetime) -> Optional[float]:
        """Get actual observed temperature from NWS for a past date"""
        try:
            is_low_market = 'LOW' in series_ticker
            
            if is_low_market:
                result = self.weather_agg.get_observed_low_for_date(series_ticker, target_date)
            else:
                result = self.weather_agg.get_observed_high_for_date(series_ticker, target_date)
            
            if result:
                temp, timestamp = result
                logger.debug(f"Got actual temp for {series_ticker} on {target_date.date()}: {temp:.1f}°F")
                return temp
            return None
        except Exception as e:
            logger.debug(f"Error getting actual temp for {series_ticker} on {target_date.date()}: {e}")
            return None
    
    def get_market_outcome(self, market_ticker: str) -> Optional[str]:
        """Check if a market has settled and get its outcome (yes/no)"""
        try:
            market = self.client.get_market(market_ticker, use_cache=False)
            status = market.get('status', '').lower()
            
            if status in ['closed', 'finalized', 'settled']:
                result = market.get('result', '').lower()
                if result in ['yes', 'no']:
                    return result
            return None
        except Exception as e:
            logger.debug(f"Could not get market outcome for {market_ticker}: {e}")
            return None
    
    def determine_winner_from_temp(self, market_ticker: str, actual_temp: float) -> Optional[str]:
        """
        Determine if YES or NO won based on actual temperature
        
        Args:
            market_ticker: Market ticker (contains threshold in format like T75 or B71.5)
            actual_temp: Actual observed temperature
            
        Returns:
            'yes' or 'no' or None
        """
        try:
            # Parse threshold from ticker
            # Format: KXHIGHNY-26JAN31-T22 or KXHIGHNY-26JAN31-B22.5
            # T = "temp will be ABOVE this" (above market)
            # B = "temp will be BELOW this" (below market)
            
            # Extract last part after final dash
            threshold_part = market_ticker.split('-')[-1]
            
            if threshold_part.startswith('T'):
                # Above market: YES if actual >= threshold
                threshold = float(threshold_part[1:])
                return 'yes' if actual_temp >= threshold else 'no'
            elif threshold_part.startswith('B'):
                # Below market: YES if actual <= threshold
                threshold = float(threshold_part[1:])
                return 'yes' if actual_temp <= threshold else 'no'
            else:
                logger.debug(f"Unknown threshold format: {threshold_part}")
                return None
        except Exception as e:
            logger.debug(f"Error determining winner for {market_ticker}: {e}")
            return None
    
    def backfill_outcomes(self, days_back: int = 7):
        """
        Backfill outcomes.csv with historical data from API fills (not trades.csv).

        Uses Kalshi API fills as the authoritative source of actual trades,
        avoiding duplicates from order attempts that never filled.

        Args:
            days_back: How many days back to look for historical fills
        """
        logger.info("Fetching fills from Kalshi API...")

        # Get fills from API (authoritative source)
        try:
            Config.validate()
            fills = self.client.get_fills()
        except Exception as e:
            logger.error(f"Could not fetch fills from API: {e}")
            return

        logger.info(f"Found {len(fills)} total fills from API")

        # Filter to weather markets only
        weather_series = set(Config.WEATHER_SERIES)
        weather_fills = []
        for fill in fills:
            ticker = fill.get('ticker', '')
            series = ticker.split('-')[0] if '-' in ticker else None
            if series in weather_series:
                weather_fills.append(fill)

        logger.info(f"Found {len(weather_fills)} weather market fills")

        # Read existing outcomes to avoid duplicates
        # Use (market_ticker, entry_price, contracts, side) as key for deduplication
        existing_outcomes = set()
        if self.outcomes_file.exists():
            with open(self.outcomes_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (
                        row.get('market_ticker', ''),
                        row.get('entry_price', ''),
                        row.get('contracts', ''),
                        row.get('side', ''),
                    )
                    existing_outcomes.add(key)

        logger.info(f"Found {len(existing_outcomes)} existing outcomes in CSV")

        # Filter to past markets (not today or future) and not already logged
        today = datetime.now().date()
        cutoff_date = today - timedelta(days=days_back)

        # Group fills by market ticker
        fills_by_market: Dict[str, List[Dict]] = defaultdict(list)
        for fill in weather_fills:
            market_ticker = fill.get('ticker', '')
            if not market_ticker:
                continue

            target_date = self.parse_date_from_ticker(market_ticker)
            if not target_date:
                continue

            # Only process past markets (settled)
            if not (cutoff_date <= target_date.date() < today):
                continue

            # Check if already logged (using fill details as key)
            side = fill.get('side', '').lower()
            price = fill.get('yes_price') if side == 'yes' else fill.get('no_price')
            contracts = fill.get('count', 0)
            key = (market_ticker, str(price), str(contracts), side)

            if key in existing_outcomes:
                continue

            fills_by_market[market_ticker].append(fill)

        logger.info(f"Processing {len(fills_by_market)} unique markets with new fills...")

        if not fills_by_market:
            logger.info("No new fills to backfill")
            return

        # Process each market
        outcomes_to_write = []
        processed = 0

        for market_ticker, market_fills in fills_by_market.items():
            processed += 1
            if processed % 10 == 0:
                logger.info(f"  Processed {processed}/{len(fills_by_market)} markets...")

            # Parse market info
            series_ticker = self.get_series_ticker_from_market_ticker(market_ticker)
            target_date = self.parse_date_from_ticker(market_ticker)

            if not series_ticker or not target_date:
                continue

            # Get actual temperature
            actual_temp = self.get_actual_temp_for_date(series_ticker, target_date)

            if actual_temp is None:
                logger.debug(f"Could not get actual temp for {market_ticker}")
                continue

            # Try to get official market outcome (if settled)
            outcome = self.get_market_outcome(market_ticker)

            # If market not settled yet, infer outcome from actual temp
            if outcome is None:
                outcome = self.determine_winner_from_temp(market_ticker, actual_temp)

            if outcome is None:
                continue

            # Process each fill on this market
            for fill in market_fills:
                side = fill.get('side', '').lower()
                contracts = fill.get('count', 0)
                entry_price = fill.get('yes_price') if side == 'yes' else fill.get('no_price')

                if not contracts or not entry_price:
                    continue

                # Determine win/loss
                won = (side == outcome)

                # Calculate P&L
                if won:
                    profit_loss = contracts * (100 - entry_price) / 100.0
                else:
                    profit_loss = -contracts * entry_price / 100.0

                # Build outcome row
                outcome_row = {
                    'timestamp': datetime.now().isoformat(),
                    'market_ticker': market_ticker,
                    'city': series_ticker,
                    'date': target_date.date().isoformat(),
                    'threshold': '',
                    'threshold_type': '',
                    'our_probability': '',
                    'market_price': entry_price,
                    'edge': '',
                    'ev': '',
                    'strategy_mode': '',
                    'side': side,
                    'contracts': contracts,
                    'entry_price': entry_price,
                    'outcome': outcome,
                    'actual_temp': actual_temp,
                    'predicted_temp': '',
                    'forecast_error': '',
                    'won': 'YES' if won else 'NO',
                    'profit_loss': f"{profit_loss:.2f}"
                }

                outcomes_to_write.append(outcome_row)

        # Write to outcomes.csv
        if outcomes_to_write:
            with open(self.outcomes_file, 'a', newline='') as f:
                fieldnames = [
                    'timestamp', 'market_ticker', 'city', 'date', 'threshold', 'threshold_type',
                    'our_probability', 'market_price', 'edge', 'ev', 'strategy_mode',
                    'side', 'contracts', 'entry_price', 'outcome', 'actual_temp',
                    'predicted_temp', 'forecast_error', 'won', 'profit_loss'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                for outcome in outcomes_to_write:
                    writer.writerow(outcome)

            logger.info(f"✅ Wrote {len(outcomes_to_write)} outcomes to {self.outcomes_file}")

            # Summary stats
            wins = sum(1 for o in outcomes_to_write if o['won'] == 'YES')
            losses = sum(1 for o in outcomes_to_write if o['won'] == 'NO')
            total_pnl = sum(float(o['profit_loss']) for o in outcomes_to_write)

            if wins + losses > 0:
                logger.info(f"📊 Summary: {wins}W-{losses}L ({wins/(wins+losses)*100:.1f}% win rate), Total P&L: ${total_pnl:.2f}")
        else:
            logger.info("No new outcomes to write")


def main():
    logger.info("Starting historical backfill...")
    
    backfiller = HistoricalBackfiller()
    
    # Backfill last 7 days
    backfiller.backfill_outcomes(days_back=7)
    
    logger.info("✅ Backfill complete!")


if __name__ == "__main__":
    main()
