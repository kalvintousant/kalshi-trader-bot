"""
Data Source Analysis - Evaluate which combinations of weather data sources provide the most accurate forecasts

This script:
1. Loads historical outcomes from trades
2. For each historical trade, fetches what each data source would have predicted
3. Tests all possible combinations of data sources
4. Calculates accuracy metrics (MAE, RMSE, hit rate) for each combination
5. Ranks combinations by performance
"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
from itertools import combinations
import numpy as np

from src.weather_data import WeatherDataAggregator
from src.kalshi_client import KalshiClient
from src.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataSourceAnalyzer:
    """Analyze performance of different weather data source combinations"""
    
    # All available data sources
    ALL_SOURCES = [
        'nws',
        'nws_mos',
        'tomorrowio',
        'open_meteo_best',
        'open_meteo_gfs',
        'open_meteo_ecmwf',
        'open_meteo_icon',
        'pirate_weather',
        'visual_crossing',
        'weatherbit'
    ]
    
    def __init__(self):
        self.weather_agg = WeatherDataAggregator()
        self.outcomes_file = Path("data/outcomes.csv")
        self.results_file = Path("data/source_analysis.json")
        
        # Store historical forecast data per source
        # Format: {market_ticker: {source: forecast_value}}
        self.historical_forecasts: Dict[str, Dict[str, float]] = {}
    
    def load_historical_outcomes(self) -> List[Dict]:
        """Load settled trades with actual outcomes"""
        if not self.outcomes_file.exists():
            logger.error(f"No outcomes file found at {self.outcomes_file}")
            return []
        
        outcomes = []
        with open(self.outcomes_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Only include outcomes where we have actual temperature
                if row.get('actual_temp') and row.get('actual_temp').strip():
                    try:
                        row['actual_temp'] = float(row['actual_temp'])
                        outcomes.append(row)
                    except (ValueError, TypeError):
                        continue
        
        logger.info(f"Loaded {len(outcomes)} historical outcomes with actual temperatures")
        return outcomes
    
    def get_source_forecast(self, source: str, series_ticker: str, 
                           target_date: datetime, market_type: str) -> Optional[float]:
        """
        Fetch what a specific source would have forecasted
        
        Args:
            source: Data source name (e.g., 'nws', 'open_meteo_gfs')
            series_ticker: City ticker
            target_date: Date of the forecast
            market_type: 'high' or 'low' temperature market
            
        Returns:
            Forecast temperature or None if unavailable
        """
        if series_ticker not in WeatherDataAggregator.CITY_COORDS:
            return None
        
        city = WeatherDataAggregator.CITY_COORDS[series_ticker]
        lat, lon = city['lat'], city['lon']
        
        try:
            # Call the appropriate source method
            if source == 'nws':
                result = self.weather_agg.get_forecast_nws(lat, lon, target_date, series_ticker)
            elif source == 'nws_mos':
                result = self.weather_agg.get_forecast_nws_mos(lat, lon, target_date, series_ticker)
            elif source == 'tomorrowio':
                result = self.weather_agg.get_forecast_tomorrowio(lat, lon, target_date, series_ticker)
            elif source == 'open_meteo_best':
                result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, 'best_match')
            elif source == 'open_meteo_gfs':
                result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, 'gfs_seamless')
            elif source == 'open_meteo_ecmwf':
                result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, 'ecmwf_ifs04')
            elif source == 'open_meteo_icon':
                result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, 'icon_seamless')
            elif source == 'pirate_weather':
                result = self.weather_agg.get_forecast_pirate_weather(lat, lon, target_date, series_ticker)
            elif source == 'visual_crossing':
                result = self.weather_agg.get_forecast_visual_crossing(lat, lon, target_date, series_ticker)
            elif source == 'weatherbit':
                result = self.weather_agg.get_forecast_weatherbit(lat, lon, target_date, series_ticker)
            else:
                return None
            
            if result:
                temp, _, _ = result
                return temp
            return None
            
        except Exception as e:
            logger.debug(f"Error getting forecast from {source}: {e}")
            return None
    
    def analyze_source_combination(self, sources: List[str], outcomes: List[Dict]) -> Dict:
        """
        Evaluate accuracy of a specific combination of data sources
        
        Args:
            sources: List of source names to combine
            outcomes: Historical outcomes with actual temperatures
            
        Returns:
            Dict with accuracy metrics
        """
        errors = []
        hit_count = 0  # Number of times within ±2°F
        total_evaluated = 0
        
        for outcome in outcomes:
            series_ticker = outcome.get('city', '')
            actual_temp = outcome.get('actual_temp')
            
            if not series_ticker or actual_temp is None:
                continue
            
            # Try to parse date
            try:
                date_str = outcome.get('date', '')
                if date_str:
                    target_date = datetime.fromisoformat(date_str)
                else:
                    continue
            except (ValueError, TypeError):
                continue
            
            # Determine market type
            market_type = 'low' if 'LOW' in series_ticker else 'high'
            
            # Get forecasts from each source in the combination
            source_forecasts = []
            for source in sources:
                forecast = self.get_source_forecast(source, series_ticker, target_date, market_type)
                if forecast is not None:
                    source_forecasts.append(forecast)
            
            # If we don't have any forecasts from this combination, skip
            if not source_forecasts:
                continue
            
            # Calculate combined forecast (simple average)
            combined_forecast = np.mean(source_forecasts)
            
            # Calculate error
            error = abs(combined_forecast - actual_temp)
            errors.append(error)
            
            # Check if within ±2°F (good forecast)
            if error <= 2.0:
                hit_count += 1
            
            total_evaluated += 1
        
        if not errors:
            return {
                'sources': sources,
                'n_samples': 0,
                'mae': None,
                'rmse': None,
                'hit_rate': None,
                'coverage': 0.0
            }
        
        # Calculate metrics
        mae = np.mean(errors)
        rmse = np.sqrt(np.mean([e**2 for e in errors]))
        hit_rate = hit_count / total_evaluated if total_evaluated > 0 else 0
        coverage = total_evaluated / len(outcomes)  # How many outcomes this combo could forecast
        
        return {
            'sources': sources,
            'n_sources': len(sources),
            'n_samples': total_evaluated,
            'mae': mae,
            'rmse': rmse,
            'hit_rate': hit_rate,
            'coverage': coverage,
            'max_error': max(errors),
            'min_error': min(errors)
        }
    
    def analyze_all_combinations(self, outcomes: List[Dict], 
                                 max_combination_size: int = None) -> List[Dict]:
        """
        Test all possible combinations of data sources
        
        Args:
            outcomes: Historical outcomes
            max_combination_size: Maximum number of sources to combine (None = all)
            
        Returns:
            List of results sorted by accuracy
        """
        if not outcomes:
            logger.error("No outcomes to analyze")
            return []
        
        logger.info(f"Testing all combinations of {len(self.ALL_SOURCES)} data sources...")
        
        results = []
        
        # Test single sources first
        logger.info("Testing individual sources...")
        for source in self.ALL_SOURCES:
            result = self.analyze_source_combination([source], outcomes)
            if result['n_samples'] > 0:
                results.append(result)
                logger.info(f"  {source}: MAE={result['mae']:.2f}°F, RMSE={result['rmse']:.2f}°F, "
                          f"Hit Rate={result['hit_rate']:.1%}, Coverage={result['coverage']:.1%}")
        
        # Test combinations of 2+ sources
        max_size = max_combination_size or len(self.ALL_SOURCES)
        for size in range(2, max_size + 1):
            logger.info(f"Testing combinations of {size} sources...")
            combo_count = 0
            
            for combo in combinations(self.ALL_SOURCES, size):
                result = self.analyze_source_combination(list(combo), outcomes)
                if result['n_samples'] > 0:
                    results.append(result)
                    combo_count += 1
            
            logger.info(f"  Evaluated {combo_count} combinations of size {size}")
        
        # Sort by MAE (lower is better)
        results.sort(key=lambda x: x['mae'] if x['mae'] is not None else float('inf'))
        
        return results
    
    def print_top_results(self, results: List[Dict], top_n: int = 10):
        """Print the top N performing combinations"""
        logger.info("="*80)
        logger.info(f"TOP {top_n} DATA SOURCE COMBINATIONS (by Mean Absolute Error)")
        logger.info("="*80)
        
        for i, result in enumerate(results[:top_n], 1):
            sources_str = ' + '.join(result['sources'])
            logger.info(f"\n#{i}: {sources_str}")
            logger.info(f"  • MAE: {result['mae']:.3f}°F")
            logger.info(f"  • RMSE: {result['rmse']:.3f}°F")
            logger.info(f"  • Hit Rate (±2°F): {result['hit_rate']:.1%}")
            logger.info(f"  • Coverage: {result['coverage']:.1%} ({result['n_samples']} samples)")
            logger.info(f"  • Error Range: {result['min_error']:.1f}°F - {result['max_error']:.1f}°F")
        
        logger.info("\n" + "="*80)
    
    def save_results(self, results: List[Dict]):
        """Save analysis results to JSON file"""
        output = {
            'generated_at': datetime.now().isoformat(),
            'total_combinations_tested': len(results),
            'results': results
        }
        
        with open(self.results_file, 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"Results saved to {self.results_file}")
    
    def compare_with_current_config(self, results: List[Dict]):
        """Compare analysis results with current configuration"""
        logger.info("\n" + "="*80)
        logger.info("COMPARISON WITH CURRENT CONFIGURATION")
        logger.info("="*80)
        
        # Find result for "all sources" combination
        all_sources_result = None
        for result in results:
            if len(result['sources']) == len(self.ALL_SOURCES):
                all_sources_result = result
                break
        
        if all_sources_result:
            logger.info(f"\nUsing ALL sources:")
            logger.info(f"  • MAE: {all_sources_result['mae']:.3f}°F")
            logger.info(f"  • Hit Rate: {all_sources_result['hit_rate']:.1%}")
            logger.info(f"  • Coverage: {all_sources_result['coverage']:.1%}")
        
        # Compare with best single source
        best_single = next((r for r in results if r['n_sources'] == 1), None)
        if best_single:
            logger.info(f"\nBest SINGLE source ({best_single['sources'][0]}):")
            logger.info(f"  • MAE: {best_single['mae']:.3f}°F")
            logger.info(f"  • Hit Rate: {best_single['hit_rate']:.1%}")
            logger.info(f"  • Coverage: {best_single['coverage']:.1%}")
        
        # Compare with best overall
        best_overall = results[0] if results else None
        if best_overall:
            sources_str = ' + '.join(best_overall['sources'])
            logger.info(f"\nBest COMBINATION ({sources_str}):")
            logger.info(f"  • MAE: {best_overall['mae']:.3f}°F")
            logger.info(f"  • Hit Rate: {best_overall['hit_rate']:.1%}")
            logger.info(f"  • Coverage: {best_overall['coverage']:.1%}")
            
            if all_sources_result:
                mae_improvement = ((all_sources_result['mae'] - best_overall['mae']) / all_sources_result['mae']) * 100
                logger.info(f"\n💡 Potential improvement over ALL sources: {mae_improvement:.1f}% lower MAE")
        
        logger.info("\n" + "="*80)


def main():
    """Main analysis workflow"""
    logger.info("Starting data source combination analysis...")
    
    analyzer = DataSourceAnalyzer()
    
    # Load historical outcomes
    outcomes = analyzer.load_historical_outcomes()
    
    if not outcomes:
        logger.error("No historical outcomes found. You need to have some settled trades first.")
        logger.info("💡 Run the bot for a few days to accumulate trade history, then run this analysis.")
        return
    
    # Analyze combinations (limit to size 4 for performance)
    logger.info("\nNote: Testing combinations up to size 4 for performance. "
               "To test larger combinations, modify max_combination_size parameter.")
    
    results = analyzer.analyze_all_combinations(outcomes, max_combination_size=4)
    
    if not results:
        logger.error("No valid results - check that data sources are accessible")
        return
    
    # Print top results
    analyzer.print_top_results(results, top_n=15)
    
    # Compare with current config
    analyzer.compare_with_current_config(results)
    
    # Save results
    analyzer.save_results(results)
    
    logger.info("\n✅ Analysis complete!")
    logger.info(f"📊 Full results saved to: {analyzer.results_file}")


if __name__ == "__main__":
    main()
