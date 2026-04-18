"""
Settlement station audit.

For every active weather series, fetch the Kalshi series metadata and the first
few markets, extract any hint of the settlement source (rulebook URL, ticker-
embedded station, `settlement_source`, or the human-readable rules), and diff
against `weather_data.WeatherDataAggregator.CITY_STATIONS` / `CITY_COORDS`.

If Kalshi publishes a station we don't have mapped, or if the mapped station
disagrees with the Kalshi ticker convention, we flag it. This does NOT enforce
correctness (the rules are free text); it surfaces discrepancies for human
review.

Usage:
    python3 tools/settlement_audit.py

Writes a report to data/settlement_audit.txt as well.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.config import Config, extract_city_code  # noqa: E402
from src.kalshi_client import KalshiClient  # noqa: E402
from src.weather_data import WeatherDataAggregator  # noqa: E402


REPORT_PATH = REPO / "data" / "settlement_audit.txt"


def _extract_station_hint(text: str) -> List[str]:
    """Pull any 4-letter ICAO-looking token that starts with K out of a string."""
    import re

    if not text:
        return []
    return sorted(set(re.findall(r"\bK[A-Z]{3}\b", text)))


def _format_series(series_ticker: str, agg: WeatherDataAggregator,
                   client: KalshiClient) -> Dict[str, object]:
    result: Dict[str, object] = {
        "series": series_ticker,
        "city_code": extract_city_code(series_ticker),
        "mapped_coords": agg.CITY_COORDS.get(series_ticker),
        "mapped_station": agg.CITY_STATIONS.get(extract_city_code(series_ticker)),
        "errors": [],
        "kalshi_rules": None,
        "kalshi_tickers_sample": [],
        "kalshi_station_hints": [],
    }

    try:
        series = client.get_series(series_ticker)
        series_body = series.get("series") or series  # Kalshi returns nested
        rules = (
            series_body.get("rules_primary")
            or series_body.get("rules_secondary")
            or ""
        )
        result["kalshi_rules"] = (rules or "")[:500]
        result["kalshi_station_hints"] = _extract_station_hint(rules)
    except Exception as exc:  # pragma: no cover — network
        result["errors"].append(f"get_series failed: {exc}")

    try:
        markets = client.get_markets(series_ticker=series_ticker, limit=3)
        for m in markets[:3]:
            sample = {
                "ticker": m.get("ticker"),
                "subtitle": m.get("subtitle"),
                "rules_primary": (m.get("rules_primary") or "")[:240],
            }
            result["kalshi_tickers_sample"].append(sample)
            hints = _extract_station_hint(m.get("rules_primary") or "")
            for h in hints:
                if h not in result["kalshi_station_hints"]:
                    result["kalshi_station_hints"].append(h)
    except Exception as exc:  # pragma: no cover — network
        result["errors"].append(f"get_markets failed: {exc}")

    # Discrepancy detection
    mapped = result["mapped_station"]
    hints = result["kalshi_station_hints"]
    if mapped and hints and mapped not in hints:
        result["errors"].append(
            f"mapped station {mapped} not in Kalshi rule hints {hints}"
        )
    if not mapped:
        result["errors"].append("no CITY_STATIONS entry for this city code")
    if not hints and not result["errors"]:
        # No ICAO string in the rules is expected for some series (they use city
        # names instead of airport codes). Flag as INFO not error.
        result["errors"].append("no ICAO in Kalshi rules — cannot auto-verify (manual check)")

    return result


def main() -> int:
    client = KalshiClient()
    agg = WeatherDataAggregator()

    series_list = Config.WEATHER_SERIES
    # Deduplicate to per-city (HIGH/LOW share stations)
    seen_cities: set = set()
    unique_series: List[str] = []
    for s in series_list:
        c = extract_city_code(s)
        if c in seen_cities:
            continue
        seen_cities.add(c)
        unique_series.append(s)

    lines: List[str] = []
    lines.append(f"Settlement Audit — {len(unique_series)} unique cities\n")
    lines.append("=" * 80)
    ok = 0
    flagged = 0
    for s in unique_series:
        info = _format_series(s, agg, client)
        print(json.dumps(info, indent=2, default=str))
        lines.append("")
        lines.append(f"SERIES: {info['series']} (city_code={info['city_code']})")
        lines.append(f"  mapped station: {info['mapped_station']}")
        lines.append(f"  mapped coords:  {info['mapped_coords']}")
        lines.append(f"  kalshi hints:   {info['kalshi_station_hints']}")
        if info["kalshi_rules"]:
            lines.append(f"  kalshi rules:   {info['kalshi_rules'][:200]}…")
        for e in info["errors"]:
            lines.append(f"  ⚠️  {e}")
            flagged += 1
        if not info["errors"]:
            ok += 1
    lines.append("")
    lines.append(f"SUMMARY: {ok} clean, {flagged} flagged")

    REPORT_PATH.write_text("\n".join(lines))
    print(f"\nReport written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
