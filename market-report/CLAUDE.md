# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (from market-report/)
pip install -r requirements.txt

# Run the report manually
py src/main.py

# Run unit tests
py -m pytest tests/ -v

# Run a single test
py -m pytest tests/test_insights.py::test_rsi_overbought -v
```

## Architecture

The system fetches market data, computes analytics, builds a ReportLab PDF, and emails it. Entry point is `src/main.py`, which runs a 5-step pipeline:

1. **data_fetch.py** — yfinance: 20 tickers, 1-year daily history + pre-market. `fetch_prices(tickers, ticker_names, return_history=True)` returns `(results_list, close_df)`. `fetch_sector_data(sector_etfs)` fetches 11 sector ETFs for the heatmap.
2. **macro_fetch.py** — FRED API: 22 macro series with a 6-hour JSON cache at `.tmp/fred_cache.json`.
3. **news_fetch.py** — Finnhub REST; falls back to MarketWatch RSS if key missing.
4. **insights.py** — Pure analytics: market breadth, risk-on/off composite score (clamped [-1,+1]), 30-day SPY correlations, technicals (SMA50/200, RSI-14, 52-week range) for SPY and QQQ.
5. **narrative.py** — 3-paragraph market commentary. Tries Anthropic → OpenAI → rules-based. Provider set in `config/settings.yaml` under `narrative.provider`.
6. **pdf_builder.py** — ReportLab Platypus assembly. All external text goes through `_x(text)` (XML escape) before entering any `Paragraph()`. Charts (sparklines, movers bar, yield curve, sector heatmap) are matplotlib Agg renders to BytesIO, lazy-imported with graceful fallback.
7. **emailer.py** — Gmail SMTP. Do not modify — backward compatibility required.

## Key conventions

- **XML escaping**: Every string from external data (ticker names, news titles, macro labels) must be wrapped in `_x()` in pdf_builder.py. Missing this causes `&` in names like "S&P 500" to crash ReportLab's XML parser.
- **Pre-market column**: `has_pm = any(p.get('current_price') is not None for p in prices_data)` — the prices table dynamically switches between 8-column and 6-column layouts. Never assume the column count is fixed.
- **Wilder's RSI**: Uses `ewm(alpha=1/window, min_periods=window)` — not `rolling().mean()`. The `_rsi()` function in insights.py must stay consistent with this.
- **Risk score formula**: `mean([SPY_pct/1.5, QQQ_pct/2.0, -(VIX-18)/8, -DXY_pct/0.8, -Gold_pct/1.5])` then `/3.0` and clamp to [-1,+1]. Thresholds: >0.1 = Risk-On, <-0.1 = Risk-Off.
- **Grouped tables**: `row_meta` list tracks which rows are group headers; background commands are appended after `_base_table_style()` so they override the alternating ROWBACKGROUNDS.
- **matplotlib**: Always set `matplotlib.use('Agg')` before importing pyplot inside chart functions. All chart functions return a `Spacer` on any exception.

## Configuration

All tuning happens in `config/settings.yaml`:
- `features:` toggles (kpi_band, charts, sector_heatmap, watermark, narrative, economic_calendar)
- `narrative.provider:` — `rules` | `anthropic` | `openai`
- `ticker_groups:` / `macro_groups:` — controls grouping rows in PDF tables
- `outlier_thresholds.asset_daily_pct:` — threshold for "standout mover" summary bullet

Secrets live in `.env`: `FRED_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `FINNHUB_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.

## Scheduling

Windows Task Scheduler fires `py src/main.py` daily at 9:30 AM ET. The script calls `is_trading_day()` (uses `pandas_market_calendars` if available, else weekday check) and exits cleanly on non-NYSE days.

## Known constraints

- `VIXCLS` on FRED has a 1-trading-day lag.
- yfinance is an unofficial wrapper — pin the version and watch for breaks after Yahoo API changes.
- FRED `fetch_macro` uses a 6-hour cache; delete `.tmp/fred_cache.json` to force a fresh fetch.
- Pre-market price column only populates for US equities between 4:00–9:30 AM ET.
