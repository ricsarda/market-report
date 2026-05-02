"""Fetch CBOE volatility data: VIX term structure, SKEW, equity put/call ratio."""

import io
import json
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent.parent / '.tmp' / 'cboe_cache.json'
_CACHE_TTL  = 6 * 3600

_HEADERS = {'User-Agent': 'MarketReport/1.0', 'Accept': 'text/csv,*/*'}

# CBOE CDN CSV endpoints — all free, no auth
_VIX_URLS = {
    'VIX9D': 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv',
    'VIX3M': 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv',
    'VIX6M': 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX6M_History.csv',
    'SKEW':  'https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv',
}


# ── Cache helpers ─────────────────────────────────────────────────────────────
def _load_cache():
    try:
        if _CACHE_FILE.exists():
            raw = json.loads(_CACHE_FILE.read_text(encoding='utf-8'))
            if time.time() - raw.get('ts', 0) < _CACHE_TTL:
                logger.info("CBOE: using cached data (< 6 h old)")
                return raw.get('data')
    except Exception as e:
        logger.debug(f"CBOE cache read failed: {e}")
    return None


def _save_cache(data: list) -> None:
    try:
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({'ts': time.time(), 'data': data}),
            encoding='utf-8',
        )
    except Exception as e:
        logger.debug(f"CBOE cache write failed: {e}")


# ── Fetch helpers ─────────────────────────────────────────────────────────────
def _fetch_cboe_csv(name: str, url: str, timeout: int = 10) -> float | None:
    """Download a CBOE index history CSV and return the latest CLOSE value."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().upper() for c in df.columns]
        close_col = next((c for c in df.columns if 'CLOSE' in c), None)
        if close_col is None:
            logger.warning(f"CBOE {name}: no CLOSE column in CSV")
            return None
        val = df[close_col].dropna()
        return float(val.iloc[-1]) if not val.empty else None
    except Exception as e:
        logger.warning(f"CBOE {name} CSV fetch failed: {e}")
        return None


def _fetch_pc_ratio() -> float | None:
    """Equity put/call ratio via yfinance (^PCCE). Returns None on failure."""
    try:
        import yfinance as yf
        data = yf.download('^PCCE', period='5d', progress=False, auto_adjust=True)
        if data.empty:
            return None
        col = data['Close'] if 'Close' in data.columns else data.iloc[:, 0]
        vals = col.dropna()
        return float(vals.iloc[-1]) if not vals.empty else None
    except Exception as e:
        logger.debug(f"Put/call ratio fetch failed: {e}")
        return None


# ── Public entry point ────────────────────────────────────────────────────────
def fetch_cboe_vol() -> list:
    """
    Returns macro-compatible dicts for:
      - VIX_TS  : VIX term structure (9D / 3M / 6M with contango/backwardation label)
      - CBOE_SKEW: CBOE SKEW Index
      - CBOE_PC : Total equity put/call ratio
    Fails gracefully — on any error returns [].
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    today_str = date.today().isoformat()

    vix9d = _fetch_cboe_csv('VIX9D', _VIX_URLS['VIX9D'])
    vix3m = _fetch_cboe_csv('VIX3M', _VIX_URLS['VIX3M'])
    vix6m = _fetch_cboe_csv('VIX6M', _VIX_URLS['VIX6M'])
    skew  = _fetch_cboe_csv('SKEW',  _VIX_URLS['SKEW'])
    pc    = _fetch_pc_ratio()

    results = []

    # VIX term structure row
    term_vals = [(v, lbl) for v, lbl in [(vix9d, '9D'), (vix3m, '3M'), (vix6m, '6M')]
                 if v is not None]
    if term_vals:
        nums    = [v for v, _ in term_vals]
        # Contango: longer-dated VIX higher than shorter-dated (normal vol term structure)
        contango  = len(nums) >= 2 and nums[-1] > nums[0]
        structure = 'contango' if contango else 'backwardation'
        arrow     = '\u2191' if contango else '\u2193'
        fmt_parts = [f"{lbl}: {v:.1f}" for v, lbl in term_vals]

        results.append({
            'series_id':  'VIX_TS',
            'name':       f'VIX Term Structure ({arrow} {structure})',
            'value':      vix3m or nums[0],
            'value_fmt':  '  \u2502  '.join(fmt_parts),
            'as_of':      today_str,
            'frequency':  'Daily',
            'month_pct':  None,
            'year_pct':   None,
        })

    if skew is not None:
        results.append({
            'series_id':  'CBOE_SKEW',
            'name':       'CBOE SKEW Index',
            'value':      skew,
            'value_fmt':  f"{skew:.1f}",
            'as_of':      today_str,
            'frequency':  'Daily',
            'month_pct':  None,
            'year_pct':   None,
        })

    if pc is not None:
        results.append({
            'series_id':  'CBOE_PC',
            'name':       'Equity Put/Call Ratio',
            'value':      pc,
            'value_fmt':  f"{pc:.2f}",
            'as_of':      today_str,
            'frequency':  'Daily',
            'month_pct':  None,
            'year_pct':   None,
        })

    _save_cache(results)
    logger.info(f"CBOE: {len(results)} volatility rows fetched")
    return results
