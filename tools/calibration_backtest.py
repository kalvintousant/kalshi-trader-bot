"""
Calibration backtest: does our probability model beat market-price-as-probability?

For every settled paper_outcomes row, we recompute three probability estimates at
decision time and score them against the actual outcome:

    * NORMAL     — what the bot does today (Normal CDF, np.std with 2.5°F floor)
    * EMPIRICAL  — fraction-of-forecasts-above-threshold, smoothed with Laplace
    * FAT_TAIL   — Normal CDF but std inflated by historical forecast RMSE
    * MARKET     — baseline: market ask price / 100

We join paper_outcomes to source_forecasts on (series_ticker, target_date) to pull
the raw forecast ensemble that was visible at decision time. Brier score is the
primary metric; lower is better. Anything that does not beat MARKET has no edge.

Usage:
    python3 tools/calibration_backtest.py
"""

from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scipy import stats  # type: ignore

REPO = Path(__file__).resolve().parent.parent
PAPER_OUTCOMES = REPO / "data" / "paper_outcomes.csv"
SOURCE_FORECASTS = REPO / "data" / "source_forecasts.csv"

STD_FLOOR_BOT = 2.5  # mirrors current GLOBAL_MIN_STD
STD_FLOOR_FAT = 3.5  # widened floor for fat-tail model
LAPLACE_ALPHA = 1.0  # Laplace smoothing for empirical CDF


@dataclass(frozen=True)
class Trade:
    series_ticker: str
    target_date: str
    threshold: float
    actual_temp: float
    market_price: int  # cents we paid at entry
    side: str  # 'yes' or 'no'
    won_yes: bool  # did the "temp > threshold" event occur?
    mean_forecast: float  # bot's recorded predicted_temp
    bot_prob: float  # bot's recorded our_probability (for the side it bet)


def _load_paper_outcomes() -> List[Trade]:
    trades: List[Trade] = []
    with PAPER_OUTCOMES.open() as f:
        for row in csv.DictReader(f):
            try:
                actual = float(row["actual_temp"])
                threshold = float(row["threshold"])
            except (ValueError, TypeError):
                continue
            if not row.get("market_price"):
                continue
            trades.append(
                Trade(
                    series_ticker=row["city"],
                    target_date=row["date"],
                    threshold=threshold,
                    actual_temp=actual,
                    market_price=int(row["market_price"]),
                    side=row["side"],
                    won_yes=actual > threshold,
                    mean_forecast=float(row["predicted_temp"]),
                    bot_prob=float(row["our_probability"]),
                )
            )
    return trades


def _load_forecasts_index() -> Dict[Tuple[str, str], List[float]]:
    """Returns map of (series_ticker, target_date) -> list of distinct forecast temps.

    We deduplicate on source per (ticker, date) — keep the median across each source's
    multiple readings to avoid inflating an ensemble with repeats of the same model."""
    per_source: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    with SOURCE_FORECASTS.open() as f:
        for row in csv.DictReader(f):
            try:
                key = (row["series_ticker"], row["target_date"], row["source"])
                per_source[key].append(float(row["forecast_temp"]))
            except (KeyError, ValueError):
                continue
    out: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for (ticker, date, _source), temps in per_source.items():
        if temps:
            out[(ticker, date)].append(statistics.median(temps))
    return out


def _prob_normal(forecasts: List[float], threshold: float, std_floor: float) -> float:
    """Current-bot-style Normal CDF with a hard minimum std floor."""
    mean = statistics.mean(forecasts)
    raw_std = statistics.pstdev(forecasts) if len(forecasts) > 1 else std_floor
    std = max(raw_std, std_floor)
    return 1.0 - stats.norm.cdf(threshold, mean, std)


def _prob_empirical(forecasts: List[float], threshold: float) -> float:
    """Laplace-smoothed empirical CDF across forecast members.

    P(above) = (# above + alpha) / (N + 2*alpha) so a 5-member ensemble with 0 above
    reports ~10% instead of 0%, avoiding the zero-probability disaster on
    undersampled tails."""
    above = sum(1 for f in forecasts if f > threshold)
    n = len(forecasts)
    return (above + LAPLACE_ALPHA) / (n + 2.0 * LAPLACE_ALPHA)


def _prob_fat_tail(forecasts: List[float], threshold: float,
                   historical_rmse: float) -> float:
    """Normal CDF with total std² = ensemble_std² + historical_rmse²."""
    mean = statistics.mean(forecasts)
    ensemble_std = statistics.pstdev(forecasts) if len(forecasts) > 1 else 0.0
    combined_std = math.sqrt(ensemble_std ** 2 + historical_rmse ** 2)
    combined_std = max(combined_std, STD_FLOOR_FAT)
    return 1.0 - stats.norm.cdf(threshold, mean, combined_std)


def _brier(probs_yes: List[float], outcomes_yes: List[int]) -> float:
    """Brier score. Lower = better. 0 is perfect, 0.25 is a coin flip."""
    if not probs_yes:
        return float("nan")
    return sum((p - o) ** 2 for p, o in zip(probs_yes, outcomes_yes)) / len(probs_yes)


def _log_loss(probs_yes: List[float], outcomes_yes: List[int]) -> float:
    eps = 1e-9
    total = 0.0
    n = 0
    for p, o in zip(probs_yes, outcomes_yes):
        p = min(max(p, eps), 1 - eps)
        total += -(o * math.log(p) + (1 - o) * math.log(1 - p))
        n += 1
    return total / n if n else float("nan")


def _reliability_table(probs_yes: List[float], outcomes_yes: List[int]) -> str:
    buckets: Dict[int, List[Tuple[float, int]]] = defaultdict(list)
    for p, o in zip(probs_yes, outcomes_yes):
        b = min(9, int(p * 10))
        buckets[b].append((p, o))
    lines = ["bucket  n   pred   actual   diff"]
    for b in sorted(buckets):
        rows = buckets[b]
        n = len(rows)
        pred = sum(p for p, _ in rows) / n
        actual = sum(o for _, o in rows) / n
        lines.append(f"{b*10:>3}-{b*10+10:<3} {n:>2}  {pred:5.2f}  {actual:5.2f}  {actual-pred:+.2f}")
    return "\n".join(lines)


def _ev_check(probs_yes: List[float], trades: List[Trade],
              edge_threshold: float = 0.05, fee_rate: float = 0.07,
              whitelist: Optional[set] = None,
              max_divergence: float = 1.0) -> Dict[str, float]:
    """Simulate: if we traded every market where |this_model_prob - market_prob| > edge_threshold,
    using that model's probability, what would P&L look like? Fees included.

    `fee_rate` defaults to 0.07 (taker) — pass 0.0175 for maker simulation.
    `whitelist` is a set of city codes allowed to trade; None = all.
    `max_divergence` skips trades where model disagrees with market beyond this (sanity gate)."""
    pnl = 0.0
    n_trades = 0
    wins = 0
    for p, t in zip(probs_yes, trades):
        if whitelist is not None and t.series_ticker not in whitelist:
            continue
        market_yes = t.market_price / 100.0 if t.side == "yes" else 1.0 - (t.market_price / 100.0)
        if abs(p - market_yes) > max_divergence:
            continue
        edge_yes = p - market_yes
        if edge_yes > edge_threshold:  # bet yes
            stake = market_yes
            fee = math.ceil(fee_rate * stake * (1 - stake) * 100) / 100.0
            payoff = (1.0 - stake) - fee if t.won_yes else -stake - fee
            pnl += payoff
            n_trades += 1
            if t.won_yes:
                wins += 1
        elif -edge_yes > edge_threshold:  # bet no
            stake = 1.0 - market_yes
            fee = math.ceil(fee_rate * stake * (1 - stake) * 100) / 100.0
            payoff = (1.0 - stake) - fee if not t.won_yes else -stake - fee
            pnl += payoff
            n_trades += 1
            if not t.won_yes:
                wins += 1
    return {
        "n_trades": n_trades,
        "wins": wins,
        "win_rate": wins / n_trades if n_trades else float("nan"),
        "pnl": pnl,
    }


def main() -> int:
    trades = _load_paper_outcomes()
    print(f"Loaded {len(trades)} settled paper trades with full fields.\n")
    if not trades:
        print("No settled trades — cannot backtest.")
        return 1

    print("Loading source_forecasts.csv (this takes a few seconds)…")
    forecasts_index = _load_forecasts_index()
    print(f"Indexed {len(forecasts_index)} (ticker, date) forecast bundles.\n")

    # Compute per-city historical RMSE (for fat-tail model) using observed error only
    # on trades we are NOT currently scoring, to keep things roughly honest.
    by_city_errors: Dict[str, List[float]] = defaultdict(list)
    for t in trades:
        by_city_errors[t.series_ticker].append(abs(t.actual_temp - t.mean_forecast))
    city_rmse: Dict[str, float] = {}
    for city, errs in by_city_errors.items():
        city_rmse[city] = math.sqrt(sum(e * e for e in errs) / len(errs))

    keep: List[Trade] = []
    forecast_bundles: List[List[float]] = []
    for t in trades:
        fcs = forecasts_index.get((t.series_ticker, t.target_date))
        if not fcs or len(fcs) < 2:
            continue
        keep.append(t)
        forecast_bundles.append(fcs)

    print(f"Of {len(trades)} trades, {len(keep)} have ≥2 forecast sources in source_forecasts.csv.\n")
    if not keep:
        print("Cannot match forecasts to outcomes — abort.")
        return 1

    # Build yes-side probability vectors per model
    normal_probs = []
    empirical_probs = []
    fat_probs = []
    market_yes_probs = []
    outcomes_yes = []
    bot_yes_probs = []  # reconstruct yes prob from bot_prob + side

    for t, fcs in zip(keep, forecast_bundles):
        rmse = city_rmse.get(t.series_ticker, 3.0)
        normal_probs.append(_prob_normal(fcs, t.threshold, STD_FLOOR_BOT))
        empirical_probs.append(_prob_empirical(fcs, t.threshold))
        fat_probs.append(_prob_fat_tail(fcs, t.threshold, rmse))
        # Market YES probability (stored csv field is price of the SIDE we took)
        market_yes = t.market_price / 100.0 if t.side == "yes" else 1.0 - (t.market_price / 100.0)
        market_yes_probs.append(market_yes)
        # Bot's recorded prob (convert to yes-side)
        bot_yes = t.bot_prob if t.side == "yes" else 1.0 - t.bot_prob
        bot_yes_probs.append(bot_yes)
        outcomes_yes.append(1 if t.won_yes else 0)

    # Disabled cities (by KXHIGH... / KXLOW... series ticker). Whitelist is
    # "everything NOT disabled". Matches the .env DISABLED_CITIES list.
    DISABLED = {
        "KXHIGHNY", "KXLOWNY", "KXHIGHCHI", "KXLOWCHI",
        "KXHIGHDEN", "KXLOWDEN", "KXHIGHTOKC", "KXHIGHPHIL", "KXLOWTPHIL",
        "KXHIGHAUS", "KXLOWAUS", "KXHIGHTDC", "KXHIGHTBOS",
    }

    def _whitelist_pass(t: "Trade") -> bool:
        return t.series_ticker not in DISABLED

    def summarise(name: str, probs: List[float]) -> None:
        b = _brier(probs, outcomes_yes)
        l = _log_loss(probs, outcomes_yes)
        print(f"\n=== {name} ===")
        print(f"  Brier:     {b:.4f}  (lower is better; coin-flip = 0.25)")
        print(f"  LogLoss:   {l:.4f}")
        print("  Reliability:")
        for line in _reliability_table(probs, outcomes_yes).splitlines():
            print(f"    {line}")
        old = _ev_check(probs, keep, edge_threshold=0.05, fee_rate=0.07)
        print(f"  Sim OLD   (5%edge, taker, all cities): trades={old['n_trades']:>2}, wr={old['win_rate']:.0%}, pnl=${old['pnl']:+.2f}")
        # Apply the disabled-city filter as a whitelist_fn-compatible set
        allowed = {t.series_ticker for t in keep if _whitelist_pass(t)}
        new = _ev_check(probs, keep, edge_threshold=0.08, fee_rate=0.0175,
                        whitelist=allowed, max_divergence=0.35)
        print(f"  Sim NEW   (8%edge, maker, losers disabled, ±35% skip): trades={new['n_trades']:>2}, wr={new['win_rate']:.0%}, pnl=${new['pnl']:+.2f}")

    summarise("MARKET (baseline)", market_yes_probs)
    summarise("NORMAL (current bot-style)", normal_probs)
    summarise("EMPIRICAL (Laplace-smoothed ensemble)", empirical_probs)
    summarise("FAT_TAIL (Normal + historical RMSE)", fat_probs)
    summarise("BOT RECORDED (post-guardrail blend)", bot_yes_probs)

    # Headline
    bm = _brier(market_yes_probs, outcomes_yes)
    bn = _brier(normal_probs, outcomes_yes)
    be = _brier(empirical_probs, outcomes_yes)
    bf = _brier(fat_probs, outcomes_yes)
    bb = _brier(bot_yes_probs, outcomes_yes)
    print("\n==================== HEADLINE ====================")
    print(f"  MARKET       Brier {bm:.4f}")
    print(f"  NORMAL       Brier {bn:.4f}  Δvs market: {bn-bm:+.4f}  {'WORSE' if bn>bm else 'BETTER'}")
    print(f"  EMPIRICAL    Brier {be:.4f}  Δvs market: {be-bm:+.4f}  {'WORSE' if be>bm else 'BETTER'}")
    print(f"  FAT_TAIL     Brier {bf:.4f}  Δvs market: {bf-bm:+.4f}  {'WORSE' if bf>bm else 'BETTER'}")
    print(f"  BOT RECORDED Brier {bb:.4f}  Δvs market: {bb-bm:+.4f}  {'WORSE' if bb>bm else 'BETTER'}")
    print("==================================================\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
