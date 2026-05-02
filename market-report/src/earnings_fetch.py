"""Fetch upcoming earnings via Finnhub calendar endpoint."""

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent.parent / '.tmp' / 'earnings_cache.json'
_CACHE_TTL  = 3 * 3600


def _load_cache():
    try:
        if _CACHE_FILE.exists():
            raw = json.loads(_CACHE_FILE.read_text(encoding='utf-8'))
            if time.time() - raw.get('ts', 0) < _CACHE_TTL:
                logger.info("Earnings: using cached data (< 3 h old)")
                return raw.get('data')
    except Exception as e:
        logger.debug(f"Earnings cache read failed: {e}")
    return None


def _save_cache(data: list) -> None:
    try:
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({'ts': time.time(), 'data': data}),
            encoding='utf-8',
        )
    except Exception as e:
        logger.debug(f"Earnings cache write failed: {e}")


def fetch_earnings(api_key: str, report_date: str, max_items: int = 10) -> list:
    """
    Returns upcoming earnings reporters for today and tomorrow.

    Each item: {ticker, company, date, when, eps_estimate, eps_actual,
                rev_estimate, day_label}
    Fails gracefully — returns [] on missing key or any exception.
    """
    if not api_key:
        logger.debug("Earnings: no Finnhub API key — skipping")
        return []

    cached = _load_cache()
    if cached is not None:
        return cached

    try:
        import finnhub
        client = finnhub.Client(api_key=api_key)

        today    = date.fromisoformat(report_date)
        tomorrow = today + timedelta(days=1)
        from_dt  = today.isoformat()
        to_dt    = tomorrow.isoformat()

        resp = client.earnings_calendar(
            _from=from_dt, to=to_dt, symbol='', international=False
        )
        raw_items = resp.get('earningsCalendar', []) if isinstance(resp, dict) else []

    except Exception as e:
        logger.warning(f"Earnings fetch failed: {e}")
        return []

    today_str    = today.isoformat()
    tomorrow_str = tomorrow.isoformat()

    results = []
    for item in raw_items:
        ticker  = item.get('symbol', '')
        company = item.get('company', ticker)
        dt      = item.get('date', '')
        when    = item.get('hour', '')          # 'bmo' | 'amc' | ''
        if when == 'bmo':
            when_label = 'BMO'
        elif when == 'amc':
            when_label = 'AMC'
        else:
            when_label = '—'

        if dt == today_str:
            day_label = 'Today'
        elif dt == tomorrow_str:
            day_label = 'Tomorrow'
        else:
            day_label = dt

        results.append({
            'ticker':       ticker,
            'company':      company,
            'date':         dt,
            'when':         when_label,
            'eps_estimate': item.get('epsEstimate'),
            'eps_actual':   item.get('epsActual'),
            'rev_estimate': item.get('revenueEstimate'),
            'day_label':    day_label,
        })

    results = results[:max_items]
    _save_cache(results)
    logger.info(f"Earnings: {len(results)} reporters fetched")
    return results
