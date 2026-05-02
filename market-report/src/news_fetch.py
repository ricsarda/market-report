"""Fetch top market news from Finnhub (with RSS fallback)."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

RSS_FALLBACK_URL = "https://feeds.marketwatch.com/marketwatch/topstories/"

_IMPACT_MAP = {
    'Rate-sensitive':  ['fed', 'federal reserve', 'rate', 'interest', 'powell', 'fomc',
                        'basis point', 'hike', 'cut', 'treasury', 'yield'],
    'Inflation':       ['inflation', 'cpi', 'ppi', 'consumer price', 'price index',
                        'deflation', 'tariff'],
    'Earnings':        ['earnings', 'revenue', 'profit', 'eps', 'guidance',
                        'beat', 'miss', 'quarterly results'],
    'Commodities':     ['oil', 'crude', 'gold', 'energy', 'opec', 'commodity',
                        'natural gas', 'copper', 'silver'],
    'Crypto':          ['bitcoin', 'btc', 'ethereum', 'crypto', 'blockchain',
                        'defi', 'stablecoin'],
    'Geopolitical':    ['war', 'sanction', 'conflict', 'trade war', 'china',
                        'russia', 'geopolit', 'embargo'],
    'Macro / Growth':  ['gdp', 'unemployment', 'jobs', 'payroll', 'recession',
                        'growth', 'manufacturing', 'pmi'],
}


def _classify(headline: str) -> str:
    text = headline.lower()
    for label, keywords in _IMPACT_MAP.items():
        if any(kw in text for kw in keywords):
            return label
    return 'General'


def fetch_news(api_key: str, max_items: int = 10) -> list:
    if api_key:
        items = _from_finnhub(api_key, max_items)
        if items:
            return items
    return _from_rss(max_items)


def _from_finnhub(api_key: str, max_items: int) -> list:
    try:
        import finnhub
        client = finnhub.Client(api_key=api_key)
        raw = client.general_news('general', min_id=0)
        results = []
        for item in raw[:max_items]:
            ts = datetime.fromtimestamp(item.get('datetime', 0))
            results.append({
                'headline':  item.get('headline', '')[:130],
                'source':    item.get('source', 'Unknown'),
                'url':       item.get('url', ''),
                'timestamp': ts.strftime('%b %d, %H:%M'),
                'impact':    _classify(item.get('headline', '')),
            })
        logger.info(f"Finnhub: {len(results)} news items fetched")
        return results
    except Exception as e:
        logger.warning(f"Finnhub news failed: {e} — falling back to RSS")
        return []


def _from_rss(max_items: int) -> list:
    try:
        resp = requests.get(RSS_FALLBACK_URL, timeout=10, headers={'User-Agent': 'MarketReport/1.0'})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        results = []
        for item in root.findall('.//item')[:max_items]:
            title   = item.findtext('title', '').strip()
            pubdate = item.findtext('pubDate', '')[:16]
            results.append({
                'headline':  title[:130],
                'source':    'MarketWatch',
                'url':       item.findtext('link', ''),
                'timestamp': pubdate,
                'impact':    _classify(title),
            })
        logger.info(f"RSS fallback: {len(results)} news items fetched")
        return results
    except Exception as e:
        logger.error(f"RSS fallback also failed: {e}")
        return []
