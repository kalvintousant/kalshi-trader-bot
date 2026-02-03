"""
Analyze Source Forecast Accuracy - Uses logged forecasts (no API calls)

This script:
1. Reads source_forecasts.csv (logged when making trades)
2. Matches with outcomes.csv (actual temperatures from NWS)
3. Calculates accuracy metrics per source
4. Shows which sources/combinations perform best
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ForecastAccuracyAnalyzer:
    """Analyze logged forecast accuracy without making API calls"""
    
    def __init__(self):
        self.forecasts_file = Path("data/source_forecasts.csv")
        self.outcomes_file = Path("data/outcomes.csv")
    
    def load_forecasts(self) -> Dict:
        """Load logged source forecasts"""
        if not self.forecasts_file.exists():
            logger.error(f"No forecasts log found at {self.forecasts_file}")
            logger.info("💡 Forecasts will be logged automatically as the bot trades.")
            logger.info("   Run the bot for a day, then run this analysis again.")
            return {}
        
        forecasts = defaultdict(lambda: defaultdict(list))
        
        with open(self.forecasts_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                series_ticker = row['series_ticker']
                target_date = row['target_date']
                source = row['source']
                forecast_temp = float(row['forecast_temp'])
                
                # Key: (series_ticker, date)
                key = (series_ticker, target_date)
                forecasts[key][source].append(forecast_temp)
        
        logger.info(f"Loaded forecasts for {len(forecasts)} unique markets")
        return forecasts
    
    def load_outcomes(self) -> List[Dict]:
        """Load outcomes with actual temperatures"""
        if not self.outcomes_file.exists():
            logger.error(f"No outcomes found at {self.outcomes_file}")
            return []
        
        outcomes = []
        with open(self.outcomes_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('actual_temp'):
                    try:
                        row['actual_temp'] = float(row['actual_temp'])
                        outcomes.append(row)
                    except ValueError:
                        continue
        
        logger.info(f"Loaded {len(outcomes)} outcomes with actual temperatures")
        return outcomes
    
    def analyze(self):
        """Main analysis"""
        forecasts = self.load_forecasts()
        outcomes = self.load_outcomes()
        
        if not forecasts:
            return
        
        if not outcomes:
            logger.warning("No outcomes yet - markets need to settle first")
            return
        
        # Match forecasts with outcomes
        source_errors = defaultdict(list)
        source_samples = defaultdict(int)
        matched_count = 0
        
        for outcome in outcomes:
            series_ticker = outcome.get('city', '')
            target_date = outcome.get('date', '')
            actual_temp = outcome.get('actual_temp')
            
            if not series_ticker or not target_date or actual_temp is None:
                continue
            
            key = (series_ticker, target_date)
            
            if key not in forecasts:
                continue
            
            matched_count += 1
            
            # For each source that forecasted this market
            for source, forecast_temps in forecasts[key].items():
                # Use average if multiple forecasts (shouldn't happen often)
                forecast = np.mean(forecast_temps)
                error = abs(forecast - actual_temp)
                source_errors[source].append(error)
                source_samples[source] += 1
        
        logger.info(f"\nMatched {matched_count} outcomes with logged forecasts")
        
        if matched_count == 0:
            logger.warning("\n⚠️  No matches found between forecasts and outcomes.")
            logger.info("    This could mean:")
            logger.info("    1. Markets haven't settled yet (check back tomorrow)")
            logger.info("    2. The bot just started logging forecasts")
            return
        
        # Calculate statistics
        logger.info("\n" + "="*80)
        logger.info("SOURCE ACCURACY ANALYSIS (from logged forecasts)")
        logger.info("="*80)
        
        results = []
        for source in sorted(source_errors.keys()):
            errors = source_errors[source]
            if not errors:
                continue
            
            mae = np.mean(errors)
            rmse = np.sqrt(np.mean([e**2 for e in errors]))
            within_2 = sum(1 for e in errors if e <= 2.0) / len(errors)
            within_5 = sum(1 for e in errors if e <= 5.0) / len(errors)
            max_error = max(errors)
            min_error = min(errors)
            
            results.append({
                'source': source,
                'mae': mae,
                'rmse': rmse,
                'hit_2deg': within_2,
                'hit_5deg': within_5,
                'max_error': max_error,
                'min_error': min_error,
                'samples': len(errors)
            })
        
        # Sort by MAE
        results.sort(key=lambda x: x['mae'])
        
        # Print results
        logger.info(f"\nAnalyzed {len(results)} sources:")
        logger.info("-" * 80)
        
        for i, r in enumerate(results, 1):
            logger.info(f"\n#{i}: {r['source']}")
            logger.info(f"  Mean Absolute Error: {r['mae']:.2f}°F")
            logger.info(f"  RMSE: {r['rmse']:.2f}°F")
            logger.info(f"  Within ±2°F: {r['hit_2deg']:.1%}")
            logger.info(f"  Within ±5°F: {r['hit_5deg']:.1%}")
            logger.info(f"  Error Range: {r['min_error']:.1f}°F - {r['max_error']:.1f}°F")
            logger.info(f"  Samples: {r['samples']}")
        
        # Test combinations
        logger.info("\n" + "="*80)
        logger.info("COMBINATION ANALYSIS")
        logger.info("="*80)
        
        if len(results) < 2:
            logger.info("\nNeed at least 2 sources to test combinations")
            return
        
        # Test top 3 sources
        top_sources = [r['source'] for r in results[:min(3, len(results))]]
        
        combo_results = []
        
        # Test: All sources combined
        all_sources = [r['source'] for r in results]
        combo_errors = self._test_combination(all_sources, forecasts, outcomes)
        if combo_errors:
            combo_results.append({
                'name': f'All Sources ({len(all_sources)})',
                'mae': np.mean(combo_errors),
                'hit_2deg': sum(1 for e in combo_errors if e <= 2.0) / len(combo_errors),
                'samples': len(combo_errors)
            })
        
        # Test: Top 3 combined
        if len(top_sources) >= 3:
            combo_errors = self._test_combination(top_sources, forecasts, outcomes)
            if combo_errors:
                combo_results.append({
                    'name': f'Top 3: {", ".join(top_sources)}',
                    'mae': np.mean(combo_errors),
                    'hit_2deg': sum(1 for e in combo_errors if e <= 2.0) / len(combo_errors),
                    'samples': len(combo_errors)
                })
        
        # Test: Top 2 combined
        if len(top_sources) >= 2:
            combo_errors = self._test_combination(top_sources[:2], forecasts, outcomes)
            if combo_errors:
                combo_results.append({
                    'name': f'Top 2: {", ".join(top_sources[:2])}',
                    'mae': np.mean(combo_errors),
                    'hit_2deg': sum(1 for e in combo_errors if e <= 2.0) / len(combo_errors),
                    'samples': len(combo_errors)
                })
        
        # Print combo results
        logger.info("")
        for combo in combo_results:
            logger.info(f"\n{combo['name']}:")
            logger.info(f"  MAE: {combo['mae']:.2f}°F")
            logger.info(f"  Within ±2°F: {combo['hit_2deg']:.1%}")
            logger.info(f"  Samples: {combo['samples']}")
        
        # Recommendation
        logger.info("\n" + "="*80)
        logger.info("RECOMMENDATION")
        logger.info("="*80)
        
        best_single = results[0]
        logger.info(f"\n📊 Most Accurate Single Source: {best_single['source']}")
        logger.info(f"   MAE: {best_single['mae']:.2f}°F, Hit Rate: {best_single['hit_2deg']:.1%}")
        
        if combo_results:
            best_combo = min(combo_results, key=lambda x: x['mae'])
            logger.info(f"\n📊 Best Combination: {best_combo['name']}")
            logger.info(f"   MAE: {best_combo['mae']:.2f}°F, Hit Rate: {best_combo['hit_2deg']:.1%}")
            
            # Compare
            current = next((c for c in combo_results if c['name'].startswith('All Sources')), None)
            if current and best_combo['name'] != current['name']:
                improvement = (current['mae'] - best_combo['mae']) / current['mae'] * 100
                if improvement > 5:
                    logger.info(f"\n💡 Using {best_combo['name']} would be {improvement:.1f}% more accurate")
                    logger.info(f"   Consider disabling underperforming sources to reduce noise")
        
        logger.info("\n" + "="*80)
    
    def _test_combination(self, sources: List[str], forecasts: Dict, 
                         outcomes: List[Dict]) -> List[float]:
        """Test a combination of sources"""
        errors = []
        
        for outcome in outcomes:
            series_ticker = outcome.get('city', '')
            target_date = outcome.get('date', '')
            actual_temp = outcome.get('actual_temp')
            
            if not series_ticker or not target_date or actual_temp is None:
                continue
            
            key = (series_ticker, target_date)
            
            if key not in forecasts:
                continue
            
            # Get forecasts from sources in this combo
            combo_forecasts = []
            for source in sources:
                if source in forecasts[key]:
                    combo_forecasts.extend(forecasts[key][source])
            
            if combo_forecasts:
                combined = np.mean(combo_forecasts)
                error = abs(combined - actual_temp)
                errors.append(error)
        
        return errors


def main():
    logger.info("Analyzing source forecast accuracy...\n")
    
    analyzer = ForecastAccuracyAnalyzer()
    analyzer.analyze()
    
    logger.info("\n✅ Analysis complete!")
    logger.info("\n💡 This analysis improves over time as:")
    logger.info("   - The bot trades more markets")
    logger.info("   - Markets settle and we get actual temperatures")
    logger.info("   - We accumulate more forecast data")


if __name__ == "__main__":
    main()
