"""
Outcome Tracker - Track bet outcomes and improve forecast accuracy over time

Writes only real Kalshi API data to data/outcomes.csv (results.csv): markets that have
officially settled (status closed/finalized/settled). No NWS-inferred outcomes are
written here; today's P&L may still use NWS inference for same-day reporting.

This module:
1. Checks for settled positions (markets that have resolved on API)
2. Extracts actual temperatures from market outcomes
3. Writes one row per market to outcomes.csv (real Kalshi results only)
4. Updates forecast model with historical accuracy data
"""

import json
import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class OutcomeTracker:
    """Track market outcomes and forecast accuracy"""

    def __init__(self, client, weather_aggregator, adaptive_manager=None):
        self.client = client
        self.weather_agg = weather_aggregator
        self.adaptive_manager = adaptive_manager

        # File paths for persistent storage
        self.outcomes_file = Path("data/outcomes.csv")
        self.performance_file = Path("data/performance.json")
        
        # Ensure data directory exists
        self.outcomes_file.parent.mkdir(exist_ok=True)
        
        # Initialize CSV if it doesn't exist
        if not self.outcomes_file.exists():
            with open(self.outcomes_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'market_ticker', 'city', 'date', 'threshold', 'threshold_type',
                    'our_probability', 'market_price', 'edge', 'ev', 'strategy_mode',
                    'side', 'contracts', 'entry_price', 'outcome', 'actual_temp',
                    'predicted_temp', 'forecast_error', 'won', 'profit_loss'
                ])
        
        # Track positions we've already logged
        self.logged_positions: set = set()
        
        # Load logged positions from file
        self._load_logged_positions()
    
    def _load_logged_positions(self):
        """Load already-logged positions from outcomes file"""
        if self.outcomes_file.exists():
            try:
                with open(self.outcomes_file, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.logged_positions.add(row['market_ticker'])
            except Exception as e:
                logger.warning(f"Could not load logged positions: {e}")
    
    def check_settled_positions(self) -> List[Dict]:
        """
        Check portfolio for settled positions (markets that have resolved).
        Groups fills by market_ticker so each market is logged once with aggregated P&L.
        Returns list of settled positions (each has 'fills' list and 'market').
        """
        try:
            fills = self.client.get_fills()
            # Group fills by market_ticker (same market can have many fill records)
            by_ticker: Dict[str, list] = defaultdict(list)
            for fill in fills:
                ticker = fill.get('ticker')
                if ticker and ticker not in self.logged_positions:
                    by_ticker[ticker].append(fill)

            settled_positions = []
            for market_ticker, ticker_fills in by_ticker.items():
                if not ticker_fills:
                    continue
                try:
                    market_response = self.client.get_market(market_ticker)
                    market = market_response.get('market', market_response)  # Unwrap nested response
                    status = market.get('status', '').lower()
                    if status in ['closed', 'finalized', 'settled']:
                        settled_positions.append({
                            'fills': ticker_fills,
                            'market': market
                        })
                        logger.info(f"Found settled position: {market_ticker} (status: {status}, {len(ticker_fills)} fill(s))")
                except Exception as e:
                    logger.debug(f"Could not fetch market {market_ticker}: {e}")
            return settled_positions
        except Exception as e:
            logger.error(f"Error checking settled positions: {e}", exc_info=True)
            return []
    
    def extract_actual_temperature(self, market: Dict) -> Optional[float]:
        """
        Extract actual temperature from settled market
        
        Kalshi markets settle based on the actual outcome. For temperature markets:
        - Range markets: "Will temp be 71-72°" -> YES if actual was in that range
        - Threshold markets: "Will temp be >75°" -> YES if actual was above 75
        
        We can infer the actual temp from which bracket won.
        """
        try:
            title = market.get('title', '')
            result = market.get('result', '').lower()
            
            if result not in ['yes', 'no']:
                logger.debug(f"Market result unclear: {result}")
                return None
            
            # Parse market to get threshold/range
            from src.weather_data import extract_threshold_from_market
            threshold = extract_threshold_from_market(market)
            
            if threshold is None:
                return None
            
            # For range markets (tuple), we know actual temp was in that range
            if isinstance(threshold, tuple):
                low, high = threshold
                if result == 'yes':
                    # Actual temp was in [low, high]
                    # Use midpoint as estimate
                    return (low + high) / 2.0
                else:
                    # Temp was NOT in range - can't determine exact value
                    # Would need to check other markets for same city/date
                    return None
            
            # For threshold markets (float), we have less info
            # "Will temp be >75?" YES means actual >= 75, NO means actual < 75
            # We'd need to cross-reference other markets to get exact value
            # For now, return None (need more sophisticated approach)
            return None
        
        except Exception as e:
            logger.warning(f"Error extracting actual temp: {e}")
            return None
    
    def get_predicted_temperature(self, market_ticker: str, target_date: datetime, series_ticker: str) -> Optional[float]:
        """
        Get what our forecast predicted for this market
        This should match what we used when placing the trade
        """
        try:
            # Get forecasts for that date
            forecasts = self.weather_agg.get_all_forecasts(series_ticker, target_date)
            
            if not forecasts:
                return None
            
            # Return mean forecast
            return sum(forecasts) / len(forecasts)
        
        except Exception as e:
            logger.warning(f"Error getting predicted temp for {market_ticker}: {e}")
            return None
    
    def log_outcome(self, settled_position: Dict):
        """
        Log outcome of a settled position to CSV (one row per market, aggregated over all fills).
        Update forecast model with actual accuracy data.
        """
        try:
            fills = settled_position.get('fills')
            if not fills:
                fill = settled_position.get('fill')
                fills = [fill] if fill else []
            if not fills:
                return
            market = settled_position['market']
            first_fill = fills[0]
            market_ticker = first_fill.get('ticker')

            from src.weather_data import extract_threshold_from_market
            threshold = extract_threshold_from_market(market)
            series_ticker = market.get('series_ticker', '')
            target_date = datetime.now()  # Placeholder
            actual_temp = self.extract_actual_temperature(market)
            predicted_temp = None
            if actual_temp and series_ticker:
                predicted_temp = self.get_predicted_temperature(market_ticker, target_date, series_ticker)
            forecast_error = None
            if actual_temp and predicted_temp:
                forecast_error = abs(actual_temp - predicted_temp)
                # Update overall forecast error tracking
                self.weather_agg.update_forecast_error(
                    series_ticker, target_date, actual_temp, predicted_temp
                )
                # Update per-model bias tracking for all sources that contributed
                self.weather_agg.update_all_model_biases(
                    series_ticker, target_date, actual_temp
                )
                logger.info(f"📊 Updated forecast model biases for {series_ticker} (actual: {actual_temp:.1f}°F)")

            result = market.get('result', '').lower()
            total_count = 0
            total_profit_loss = 0.0
            side = first_fill.get('side', '').lower()
            for fill in fills:
                count = fill.get('count', 0)
                trade_price = fill.get('yes_price', 0) if side == 'yes' else fill.get('no_price', 0)
                won = (side == result)
                if won:
                    total_profit_loss += count * (100 - trade_price) / 100.0
                else:
                    total_profit_loss -= count * trade_price / 100.0
                total_count += count
            # Use avg entry price for display (first fill's price as proxy)
            trade_price = first_fill.get('yes_price', 0) if side == 'yes' else first_fill.get('no_price', 0)
            won = (side == result)

            with open(self.outcomes_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    market_ticker,
                    series_ticker,
                    target_date.date().isoformat() if target_date else '',
                    str(threshold),
                    'range' if isinstance(threshold, tuple) else 'threshold',
                    '', '', '', '', '',
                    side,
                    total_count,
                    trade_price,
                    result,
                    actual_temp if actual_temp else '',
                    predicted_temp if predicted_temp else '',
                    forecast_error if forecast_error else '',
                    'YES' if won else 'NO',
                    f"{total_profit_loss:.2f}"
                ])

            self.logged_positions.add(market_ticker)
            outcome_symbol = "✅" if won else "❌"
            logger.info(f"{outcome_symbol} Logged outcome: {market_ticker} | {side.upper()} | {'WON' if won else 'LOST'} | P&L: ${total_profit_loss:.2f} ({total_count} contract(s))")
            if forecast_error:
                logger.info(f"   Forecast accuracy: Predicted {predicted_temp:.1f}°, Actual {actual_temp:.1f}° (error: {forecast_error:.1f}°)")

            # Update adaptive city manager with outcome
            if self.adaptive_manager and series_ticker:
                city = series_ticker.replace('KXHIGH', '').replace('KXLOW', '')
                self.adaptive_manager.record_outcome(city, won, total_profit_loss)
                logger.debug(f"Updated adaptive manager for city {city}")

        except Exception as e:
            logger.error(f"Error logging outcome: {e}", exc_info=True)
    
    def generate_performance_report(self) -> Dict:
        """
        Generate performance analytics from outcomes
        Returns dict with win rates, P&L, forecast accuracy by city/strategy
        """
        try:
            if not self.outcomes_file.exists():
                return {}
            
            # Read all outcomes
            outcomes = []
            with open(self.outcomes_file, 'r') as f:
                reader = csv.DictReader(f)
                outcomes = list(reader)
            
            if not outcomes:
                return {"message": "No settled positions yet"}
            
            # Calculate overall stats
            total_trades = len(outcomes)
            wins = sum(1 for o in outcomes if o['won'] == 'YES')
            losses = sum(1 for o in outcomes if o['won'] == 'NO')
            win_rate = wins / total_trades if total_trades > 0 else 0
            
            total_pnl = sum(float(o['profit_loss']) for o in outcomes if o['profit_loss'])
            
            # Stats by city
            by_city = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0, 'forecast_errors': []})
            
            for outcome in outcomes:
                city = outcome['city']
                if outcome['won'] == 'YES':
                    by_city[city]['wins'] += 1
                else:
                    by_city[city]['losses'] += 1
                
                if outcome['profit_loss']:
                    by_city[city]['pnl'] += float(outcome['profit_loss'])
                
                if outcome['forecast_error']:
                    by_city[city]['forecast_errors'].append(float(outcome['forecast_error']))
            
            # Calculate average forecast error per city
            city_stats = {}
            for city, stats in by_city.items():
                total = stats['wins'] + stats['losses']
                city_stats[city] = {
                    'trades': total,
                    'win_rate': stats['wins'] / total if total > 0 else 0,
                    'pnl': stats['pnl'],
                    'avg_forecast_error': sum(stats['forecast_errors']) / len(stats['forecast_errors']) if stats['forecast_errors'] else None
                }
            
            report = {
                'generated_at': datetime.now().isoformat(),
                'overall': {
                    'total_trades': total_trades,
                    'wins': wins,
                    'losses': losses,
                    'win_rate': win_rate,
                    'total_pnl': total_pnl
                },
                'by_city': city_stats
            }
            
            # Save to JSON
            with open(self.performance_file, 'w') as f:
                json.dump(report, f, indent=2)
            
            return report
        
        except Exception as e:
            logger.error(f"Error generating performance report: {e}", exc_info=True)
            return {}
    
    def run_outcome_check(self):
        """
        Main method to check for settled positions and log outcomes
        Should be called periodically (e.g., once per hour)
        """
        logger.info("🔍 Checking for settled positions...")
        
        settled = self.check_settled_positions()
        
        if not settled:
            logger.info("No new settled positions found")
            return
        
        logger.info(f"Found {len(settled)} settled position(s) to process")
        
        for position in settled:
            self.log_outcome(position)
        
        # Generate updated performance report
        report = self.generate_performance_report()
        
        if report and 'overall' in report:
            overall = report['overall']
            logger.info(f"📊 Performance Update: {overall['wins']}W-{overall['losses']}L ({overall['win_rate']:.1%}) | P&L: ${overall['total_pnl']:.2f}")
