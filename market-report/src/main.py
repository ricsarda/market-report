#!/usr/bin/env python3
"""Daily Market Report — orchestrator (Phases 1-3)."""

import logging
import os
import sys
import time
from datetime import date, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import pytz
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(ROOT / '.env')

from cboe_fetch     import fetch_cboe_vol
from cot_fetch      import fetch_cot
from data_fetch     import fetch_prices, fetch_sector_data
from earnings_fetch import fetch_earnings
from emailer        import send_email
from insights       import compute_insights
from macro_fetch    import fetch_macro
from narrative      import generate_narrative
from news_fetch     import fetch_news
from archive_publisher import publish as publish_archive
from html_builder   import build_html
from pdf_builder    import build_pdf

OUTPUT_DIR = ROOT / 'output'
LOGS_DIR   = ROOT / 'logs'
ASSETS_DIR = ROOT / 'assets'
CONFIG_DIR = ROOT / 'config'

ET = pytz.timezone('America/New_York')


# ── Logging ───────────────────────────────────────────────────────────────────
def setup_logging():
    LOGS_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    fh  = TimedRotatingFileHandler(
        LOGS_DIR / 'market_report.log', when='midnight', backupCount=7, encoding='utf-8')
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(ch)


def load_config() -> dict:
    with open(CONFIG_DIR / 'settings.yaml', encoding='utf-8') as f:
        return yaml.safe_load(f)


def is_trading_day() -> bool:
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar('NYSE')
        today = date.today().isoformat()
        return not nyse.schedule(start_date=today, end_date=today).empty
    except ImportError:
        return date.today().weekday() < 5


def _retry(func, name: str, retries: int = 3, delay: int = 15):
    log = logging.getLogger('main')
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:
            log.warning(f"{name} attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(delay)
    log.error(f"{name} exhausted {retries} retries — skipping")
    return None


# ── Economic calendar (FRED release dates) ───────────────────────────────────
def _fetch_calendar(fred_key: str) -> list:
    try:
        import requests
        today = date.today().isoformat()
        resp = requests.get(
            'https://api.stlouisfed.org/fred/releases/dates',
            params={'api_key': fred_key, 'realtime_start': today,
                    'realtime_end': today, 'file_type': 'json',
                    'include_release_dates_with_no_data': 'true'},
            timeout=8,
        )
        items = resp.json().get('release_dates', [])
        return [{'name': i.get('release_name', ''), 'date': i.get('date', '')}
                for i in items[:12]]
    except Exception as e:
        logging.getLogger('main').debug(f"Economic calendar fetch failed: {e}")
        return []


# ── Summary generation (insights-enhanced) ───────────────────────────────────
def _generate_summary(prices, macro, insights, threshold: float) -> list:
    bullets = []

    spy = next((t for t in prices if t['ticker'] == 'SPY'), None)
    if spy:
        verb = "gained" if spy['daily_pct'] > 0 else "lost"
        bullets.append(
            f"S&P 500 (SPY) {verb} {abs(spy['daily_pct']):.2f}% in the prior session."
        )

    movers = sorted(prices, key=lambda x: abs(x.get('daily_pct') or 0), reverse=True)
    if movers and abs(movers[0].get('daily_pct') or 0) >= threshold:
        top  = movers[0]
        sign = '+' if top['daily_pct'] > 0 else ''
        bullets.append(
            f"Standout: {top['ticker']} ({top['name']}) "
            f"{sign}{top['daily_pct']:.2f}% — largest single-asset swing."
        )

    breadth = insights.get('breadth', {})
    if breadth:
        n_up = breadth['n_up']; n_dn = breadth['n_dn']
        total = n_up + n_dn
        mood  = 'positive' if n_up > n_dn else 'negative'
        bullets.append(
            f"Breadth: {n_up}/{total} tracked assets advanced ({mood} participation)."
        )

    risk_label = insights.get('risk_label', '')
    risk_score = insights.get('risk_score', 0)
    if risk_label:
        bullets.append(
            f"Risk regime: {risk_label} (composite score {risk_score:+.2f}) — "
            f"driven by equity momentum, volatility, dollar, and safe-haven signals."
        )

    t10y2y = next((m for m in macro if m['series_id'] == 'T10Y2Y'), None)
    ff     = next((m for m in macro if m['series_id'] == 'FEDFUNDS'), None)
    if t10y2y and t10y2y.get('value') is not None:
        v = t10y2y['value']
        if v < 0:
            bullets.append(
                f"Yield curve inverted at {v:.2f}% (10Y-2Y) — historically a recession signal."
            )
        elif abs(v) < 0.15:
            bullets.append(f"Yield curve near flat at {v:.2f}% — monitor for sign change.")
        elif ff:
            bullets.append(
                f"Fed Funds at {ff['value']:.2f}%; 10Y-2Y spread at {v:.2f}% — policy backdrop stable."
            )
    elif ff:
        bullets.append(
            f"Fed Funds Rate at {ff['value']:.2f}% as of {ff['as_of']}."
        )

    return bullets[:5]


# ── Signal generation (technicals-enhanced) ──────────────────────────────────
def _generate_signals(prices, macro, insights) -> list:
    signals = []
    technicals = insights.get('technicals', {})

    for ticker in ['SPY', 'QQQ']:
        tech = technicals.get(ticker, {})
        rsi  = tech.get('rsi14')
        s200 = tech.get('pct_from_sma200')
        if rsi is not None:
            if rsi > 70:
                signals.append(f"{ticker} RSI at {rsi:.0f} — overbought; watch for momentum fade.")
            elif rsi < 30:
                signals.append(f"{ticker} RSI at {rsi:.0f} — oversold; watch for mean-reversion.")
        if s200 is not None and abs(s200) > 5:
            direction = "above" if s200 > 0 else "below"
            signals.append(
                f"{ticker} is {abs(s200):.1f}% {direction} its 200-day SMA — key long-term level."
            )

    correlations = insights.get('correlations', {})
    spy_btc = correlations.get('SPY_vs_BTC-USD')
    if spy_btc is not None and abs(spy_btc) > 0.6:
        mood = "high positive" if spy_btc > 0 else "high negative"
        signals.append(
            f"SPY/BTC 30-day correlation at {spy_btc:.2f} ({mood}) — crypto tracking equities."
        )

    for ticker_id, label, thr in [
        ('BTC-USD',  'Bitcoin',    3.0),
        ('CL=F',     'WTI Oil',    2.0),
        ('NG=F',     'Nat. Gas',   3.0),
        ('DX-Y.NYB', 'US Dollar',  0.5),
    ]:
        asset = next((t for t in prices if t['ticker'] == ticker_id), None)
        if asset and abs(asset.get('daily_pct') or 0) >= thr:
            d = asset['daily_pct']
            note = ('watch inflation & EM exposure'
                    if ticker_id in ('CL=F', 'NG=F', 'DX-Y.NYB')
                    else 'monitor risk sentiment')
            signals.append(f"{label} {d:+.1f}% — {note}.")

    vix = next((m for m in macro if m['series_id'] == 'VIXCLS'), None)
    if vix and vix.get('value'):
        v     = vix['value']
        level = ('elevated — heightened caution' if v > 25
                 else 'moderate' if v > 18 else 'contained')
        signals.append(f"VIX at {v:.1f} ({vix['as_of']}): volatility {level}.")

    if not signals:
        signals.append("No significant outlier signals detected. Standard monitoring applies.")
    return signals[:6]


def _cleanup_old_pdfs(retention_days: int):
    log    = logging.getLogger('main')
    cutoff = datetime.now().timestamp() - retention_days * 86_400
    for pdf in OUTPUT_DIR.glob('market_*.pdf'):
        if pdf.stat().st_mtime < cutoff:
            pdf.unlink()
            log.info(f"Deleted expired report: {pdf.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    setup_logging()
    log = logging.getLogger('main')
    log.info("=" * 60)
    log.info("Daily Market Report — starting")
    log.info("=" * 60)

    if not is_trading_day():
        log.info("Not a NYSE trading day — exiting.")
        sys.exit(0)

    cfg = load_config()
    OUTPUT_DIR.mkdir(exist_ok=True)
    (ROOT / '.tmp').mkdir(exist_ok=True)

    fred_key    = os.getenv('FRED_API_KEY', '')
    gmail_user  = os.getenv('GMAIL_USER', '')
    gmail_pass  = os.getenv('GMAIL_APP_PASSWORD', '')
    finnhub_key = os.getenv('FINNHUB_API_KEY', '')

    report_date = datetime.now(ET).strftime('%Y-%m-%d')
    features    = cfg.get('features', {})
    narr_cfg    = cfg.get('narrative', {})

    # ── Fetch ──────────────────────────────────────────────────────
    log.info("Step 1/5 — Asset prices")
    fetch_result = _retry(
        lambda: fetch_prices(cfg['tickers'], cfg.get('ticker_names', {}),
                             return_history=True),
        'data_fetch',
    )
    if fetch_result and isinstance(fetch_result, tuple):
        prices, close_df = fetch_result
    else:
        prices, close_df = fetch_result or [], None

    log.info("Step 2/5 — Macro data (FRED)")
    macro = _retry(
        lambda: fetch_macro(fred_key, cfg.get('fred_series', {})),
        'macro_fetch',
    ) or [] if fred_key else []

    log.info("Step 3/5 — News")
    news = _retry(
        lambda: fetch_news(finnhub_key, cfg.get('report', {}).get('news_items', 8)),
        'news_fetch',
    ) or []

    sector_data = {}
    if features.get('sector_heatmap', True) and cfg.get('sector_etfs'):
        log.info("Step 3b — Sector ETFs")
        sector_data = _retry(
            lambda: fetch_sector_data(cfg['sector_etfs']),
            'sector_fetch',
        ) or {}

    data_src = cfg.get('data_sources', {})

    cboe_rows = []
    if data_src.get('cboe_vol', True):
        log.info("Step 3c — CBOE volatility")
        cboe_rows = _retry(fetch_cboe_vol, 'cboe_fetch') or []
    if cboe_rows:
        macro.extend(cboe_rows)

    earnings_data = []
    if data_src.get('finnhub_earnings', True) and finnhub_key:
        log.info("Step 3d — Earnings calendar")
        earnings_data = _retry(
            lambda: fetch_earnings(finnhub_key, report_date),
            'earnings_fetch',
        ) or []

    cot_data = []
    if data_src.get('cftc_cot', True):
        log.info("Step 3e — CFTC COT positioning")
        cot_data = _retry(fetch_cot, 'cot_fetch') or []

    # ── Analytics ──────────────────────────────────────────────────
    log.info("Step 4/5 — Insights & narrative")
    import pandas as pd
    insights = {}
    if prices:
        try:
            insights = compute_insights(
                close_df if close_df is not None else pd.DataFrame(),
                prices, macro,
            )
        except Exception as e:
            log.warning(f"Insights failed: {e}")

    threshold = cfg.get('outlier_thresholds', {}).get('asset_daily_pct', 2.0)
    summary   = _generate_summary(prices, macro, insights, threshold)
    signals   = _generate_signals(prices, macro, insights)

    narrative_paragraphs = []
    if features.get('narrative', True):
        try:
            narrative_paragraphs = generate_narrative(
                report_date, summary, macro, insights, narr_cfg,
                env={
                    'ANTHROPIC_API_KEY': os.getenv('ANTHROPIC_API_KEY', ''),
                    'OPENAI_API_KEY':    os.getenv('OPENAI_API_KEY', ''),
                },
            )
        except Exception as e:
            log.warning(f"Narrative generation failed: {e}")

    calendar = []
    if features.get('economic_calendar', True) and fred_key:
        calendar = _fetch_calendar(fred_key)

    # ── Build PDF ──────────────────────────────────────────────────
    log.info("Step 5/5 — Building PDF")
    pdf_name = f"market_{report_date}.pdf"
    pdf_path = str(OUTPUT_DIR / pdf_name)
    logo     = str(ASSETS_DIR / 'logo.png')

    build_pdf(
        output_path          = pdf_path,
        report_date          = report_date,
        prices_data          = prices,
        macro_data           = macro,
        news_data            = news,
        summary_bullets      = summary,
        signals              = signals,
        logo_path            = logo if Path(logo).exists() else None,
        close_df             = close_df,
        ticker_groups        = cfg.get('ticker_groups'),
        macro_groups         = cfg.get('macro_groups'),
        watermark            = features.get('watermark', False),
        sector_data          = sector_data,
        narrative_paragraphs = narrative_paragraphs,
        narrative_provider   = narr_cfg.get('provider', 'rules'),
        calendar             = calendar,
        features             = features,
        insights             = insights,
        branding             = cfg.get('branding', {}),
        earnings_data        = earnings_data,
        cot_data             = cot_data,
    )
    log.info(f"PDF ready: {pdf_path}")

    # ── Build HTML ─────────────────────────────────────────────────
    html_name = f"market_{report_date}.html"
    html_path = str(OUTPUT_DIR / html_name)
    html_body = None
    try:
        html_body = build_html(
            report_date          = report_date,
            prices_data          = prices,
            macro_data           = macro,
            news_data            = news,
            summary_bullets      = summary,
            signals              = signals,
            close_df             = close_df,
            ticker_groups        = cfg.get('ticker_groups'),
            macro_groups         = cfg.get('macro_groups'),
            sector_data          = sector_data,
            narrative_paragraphs = narrative_paragraphs,
            narrative_provider   = narr_cfg.get('provider', 'rules'),
            calendar             = calendar,
            features             = features,
            insights             = insights,
            earnings_data        = earnings_data,
            cot_data             = cot_data,
            out_path             = html_path,
        )
        log.info(f"HTML ready: {html_path}")
    except Exception as e:
        log.warning(f"HTML build failed: {e}")

    # ── Publish to GitHub Pages archive ───────────────────────────
    if html_body:
        try:
            publish_archive(html_path, report_date)
        except Exception as e:
            log.warning(f"Archive publish failed: {e}")

    # ── Email ──────────────────────────────────────────────────────
    if gmail_user and gmail_pass:
        email_cfg  = cfg.get('email', {})
        recipients = email_cfg.get('recipients', [])
        subject    = email_cfg.get('subject', 'Daily Market Report — {date}').format(
            date=report_date)
        body = (
            f"Daily Market Report — {report_date}\n\n"
            + '\n'.join(f"\u2022 {b}" for b in summary)
            + "\n\nFull report attached.\n\n"
            "Generated automatically by the Market Intelligence System."
        )
        _retry(
            lambda: send_email(gmail_user, gmail_pass, recipients, subject, body,
                               pdf_path, html_body=html_body),
            'emailer',
        )
    else:
        log.warning("Gmail credentials not set — PDF saved locally, not emailed.")

    _cleanup_old_pdfs(cfg.get('report', {}).get('retention_days', 30))
    log.info("Daily Market Report — complete")
    log.info("=" * 60)


if __name__ == '__main__':
    main()
