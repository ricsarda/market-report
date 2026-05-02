"""Fetch asset prices, pre-market/live data, and sector ETF data via yfinance."""

import logging
from datetime import date

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_prices(tickers: list, ticker_names: dict, return_history: bool = False):
    """
    Returns list of per-ticker dicts (ticker, name, prev_close, daily_pct,
    monthly_pct, yearly_pct, open_price, open_pct).

    open_price / open_pct are the confirmed session-open values (9:30 AM ET
    auction). They are None before market open or on non-trading days — the
    PDF renders a dash in that case.

    If return_history=True, returns (list, close_df) where close_df is the
    full 1-year daily close DataFrame — reused by insights and sparklines
    with no extra API call.
    """
    if not tickers:
        return ([], pd.DataFrame()) if return_history else []

    # ── 1. Bulk daily history (1 year) ──────────────────────────
    logger.info(f"Downloading daily history for {len(tickers)} tickers...")
    raw = yf.download(
        tickers, period='1y', auto_adjust=True, progress=False, threads=True,
    )
    close = raw['Close'] if 'Close' in raw.columns else pd.DataFrame()
    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])

    # ── 2. Today's session opening prices ───────────────────────
    logger.info("Downloading today's opening prices...")
    try:
        today_raw = yf.download(
            tickers, period='1d', interval='1d',
            auto_adjust=True, progress=False,
        )
        open_prices = today_raw['Open'] if 'Open' in today_raw.columns else pd.DataFrame()
        if isinstance(open_prices, pd.Series):
            open_prices = open_prices.to_frame(name=tickers[0])
    except Exception as e:
        logger.warning(f"Opening price download failed: {e}")
        open_prices = pd.DataFrame()

    # ── 3. Per-ticker calculations ───────────────────────────────
    results = []
    today = date.today()

    for ticker in tickers:
        try:
            if ticker not in close.columns:
                logger.warning(f"No daily data for {ticker} — skipping")
                continue

            series = close[ticker].dropna()
            if not series.empty and series.index[-1].date() == today:
                series = series.iloc[:-1]
            if len(series) < 2:
                logger.warning(f"Insufficient history for {ticker}")
                continue

            prev_close  = float(series.iloc[-1])
            prev2_close = float(series.iloc[-2])
            month_ago   = float(series.iloc[-22]) if len(series) >= 22 else float(series.iloc[0])
            year_ago    = float(series.iloc[0])

            daily_pct   = (prev_close - prev2_close) / prev2_close * 100
            monthly_pct = (prev_close - month_ago)   / month_ago   * 100
            yearly_pct  = (prev_close - year_ago)    / year_ago    * 100

            open_price = open_pct = None
            if ticker in open_prices.columns and not open_prices.empty:
                raw_open = open_prices[ticker].iloc[-1]
                if raw_open is not None and not pd.isna(raw_open):
                    op = float(raw_open)
                    open_price = round(op, 4)
                    open_pct   = round((op - prev_close) / prev_close * 100, 2)

            results.append({
                'ticker':      ticker,
                'name':        ticker_names.get(ticker, ticker),
                'prev_close':  round(prev_close,  4),
                'daily_pct':   round(daily_pct,   2),
                'monthly_pct': round(monthly_pct, 2),
                'yearly_pct':  round(yearly_pct,  2),
                'open_price':  open_price,
                'open_pct':    open_pct,
            })
        except Exception as e:
            logger.error(f"Failed processing {ticker}: {e}")

    n_open = sum(1 for r in results if r.get('open_price') is not None)
    logger.info(f"Price data ready for {len(results)}/{len(tickers)} tickers "
                f"({n_open}/{len(results)} with valid open price)")
    return (results, close) if return_history else results


def fetch_sector_data(sector_etfs: dict) -> dict:
    """
    Fetches daily % change for sector ETFs.
    Returns {ticker: {'name': str, 'daily_pct': float}}.
    """
    if not sector_etfs:
        return {}

    tickers = list(sector_etfs.keys())
    logger.info(f"Downloading sector ETF data ({len(tickers)} tickers)...")
    try:
        raw = yf.download(tickers, period='5d', auto_adjust=True, progress=False)
        close = raw['Close'] if 'Close' in raw.columns else pd.DataFrame()
        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])

        results = {}
        today = date.today()
        for ticker, name in sector_etfs.items():
            if ticker not in close.columns:
                continue
            s = close[ticker].dropna()
            if not s.empty and s.index[-1].date() == today:
                s = s.iloc[:-1]
            if len(s) < 2:
                continue
            pct = (float(s.iloc[-1]) - float(s.iloc[-2])) / float(s.iloc[-2]) * 100
            results[ticker] = {'name': name, 'daily_pct': round(pct, 2)}
        return results
    except Exception as e:
        logger.error(f"Sector ETF fetch failed: {e}")
        return {}
