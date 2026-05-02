"""Fetch CFTC Commitments of Traders (COT) net positioning via Socrata public API."""

import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent.parent / '.tmp' / 'cot_cache.json'
_CACHE_TTL  = 24 * 3600

_SOCRATA_URL = 'https://publicreporting.cftc.gov/resource/6dca-dn3j.json'

# Map: display name → Socrata market_and_exchange_names substring for LIKE filter
_COT_MARKETS = {
    'S&P 500':    'S&P 500 STOCK INDEX',
    'WTI Crude':  'CRUDE OIL, LIGHT SWEET',
    'Gold':       'GOLD',
}

_HEADERS = {'Accept': 'application/json'}


def _load_cache():
    try:
        if _CACHE_FILE.exists():
            raw = json.loads(_CACHE_FILE.read_text(encoding='utf-8'))
            if time.time() - raw.get('ts', 0) < _CACHE_TTL:
                logger.info("COT: using cached data (< 24 h old)")
                return raw.get('data')
    except Exception as e:
        logger.debug(f"COT cache read failed: {e}")
    return None


def _save_cache(data: list) -> None:
    try:
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({'ts': time.time(), 'data': data}),
            encoding='utf-8',
        )
    except Exception as e:
        logger.debug(f"COT cache write failed: {e}")


def _fetch_one(label: str, market_substr: str, timeout: int = 12) -> dict | None:
    """Query Socrata for the most recent COT row matching market_substr."""
    try:
        params = {
            '$where':  f"market_and_exchange_names LIKE '%{market_substr}%'",
            '$order':  'report_date_as_yyyy_mm_dd DESC',
            '$limit':  '1',
            '$select': (
                'market_and_exchange_names,report_date_as_yyyy_mm_dd,'
                'noncomm_positions_long_all,noncomm_positions_short_all'
            ),
        }
        resp = requests.get(_SOCRATA_URL, params=params, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            logger.warning(f"COT {label}: no rows returned")
            return None
        row   = rows[0]
        longs = int(row.get('noncomm_positions_long_all', 0) or 0)
        short = int(row.get('noncomm_positions_short_all', 0) or 0)
        net   = longs - short
        as_of = row.get('report_date_as_yyyy_mm_dd', '')
        return {
            'label':  label,
            'net':    net,
            'longs':  longs,
            'shorts': short,
            'as_of':  as_of,
        }
    except Exception as e:
        logger.warning(f"COT {label} fetch failed: {e}")
        return None


def fetch_cot() -> list:
    """
    Returns COT net non-commercial positioning for S&P 500, WTI Crude, Gold.

    Each item: {label, net, longs, shorts, as_of}
    Net > 0 = net long (risk-on bias); net < 0 = net short.
    Fails gracefully — returns [] on any error.
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    results = []
    for label, substr in _COT_MARKETS.items():
        row = _fetch_one(label, substr)
        if row is not None:
            results.append(row)

    _save_cache(results)
    logger.info(f"COT: {len(results)} markets fetched")
    return results
