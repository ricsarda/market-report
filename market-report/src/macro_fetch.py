"""Fetch macroeconomic data from FRED with 6-hour local cache."""

import json
import logging
import time
from pathlib import Path

import pandas as pd
from fredapi import Fred

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent.parent / '.tmp' / 'fred_cache.json'
_CACHE_TTL  = 6 * 3600   # seconds


# ── Cache helpers ─────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    try:
        if _CACHE_FILE.exists():
            raw = json.loads(_CACHE_FILE.read_text(encoding='utf-8'))
            if time.time() - raw.get('ts', 0) < _CACHE_TTL:
                logger.info("FRED: using cached data (< 6 h old)")
                return raw.get('series', {})
    except Exception as e:
        logger.debug(f"Cache read failed: {e}")
    return {}


def _save_cache(series_dict: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({'ts': time.time(), 'series': series_dict}),
            encoding='utf-8',
        )
    except Exception as e:
        logger.debug(f"Cache write failed: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _infer_frequency(series: pd.Series) -> str:
    if len(series) < 2:
        return 'Unknown'
    avg_days = (series.index[-1] - series.index[0]).days / (len(series) - 1)
    if avg_days < 10:
        return 'Daily'
    if avg_days < 40:
        return 'Monthly'
    return 'Quarterly'


def _fmt_value(val: float) -> str:
    if val is None:
        return '—'
    a = abs(val)
    if a >= 10_000: return f"{val:,.0f}"
    if a >= 100:    return f"{val:,.1f}"
    if a >= 1:      return f"{val:.2f}"
    return f"{val:.4f}"


# ── Public entry point ────────────────────────────────────────────────────────
def fetch_macro(api_key: str, series_config: dict) -> list:
    """
    Returns one dict per FRED series:
      series_id, name, value, value_fmt, as_of, frequency, month_pct, year_pct
    """
    if not api_key or not series_config:
        return []

    # Try cache first
    cached = _load_cache()
    fred   = Fred(api_key=api_key)
    results     = []
    fresh_cache = {}

    for series_id, series_name in series_config.items():
        try:
            # Use cached raw data if available
            if series_id in cached:
                entry = cached[series_id]
                results.append(entry)
                fresh_cache[series_id] = entry
                continue

            data = fred.get_series(series_id).dropna()
            if data.empty:
                logger.warning(f"FRED {series_id}: empty response")
                continue

            latest_val  = float(data.iloc[-1])
            latest_date = data.index[-1]
            frequency   = _infer_frequency(data)

            cutoff_1m = latest_date - pd.DateOffset(months=1)
            prior_1m  = data[data.index <= cutoff_1m]
            month_pct = None
            if not prior_1m.empty:
                pv = float(prior_1m.iloc[-1])
                if pv != 0:
                    month_pct = round((latest_val - pv) / abs(pv) * 100, 2)

            cutoff_1y = latest_date - pd.DateOffset(years=1)
            prior_1y  = data[data.index <= cutoff_1y]
            year_pct  = None
            if not prior_1y.empty:
                pv = float(prior_1y.iloc[-1])
                if pv != 0:
                    year_pct = round((latest_val - pv) / abs(pv) * 100, 2)

            entry = {
                'series_id': series_id,
                'name':      series_name,
                'value':     latest_val,
                'value_fmt': _fmt_value(latest_val),
                'as_of':     latest_date.strftime('%Y-%m-%d'),
                'frequency': frequency,
                'month_pct': month_pct,
                'year_pct':  year_pct,
            }
            results.append(entry)
            fresh_cache[series_id] = entry

        except Exception as e:
            logger.error(f"Failed fetching FRED {series_id}: {e}")

    _save_cache(fresh_cache)
    logger.info(f"Macro data ready: {len(results)}/{len(series_config)} series")
    return results
