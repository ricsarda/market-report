"""Compute analytical insights: breadth, risk score, correlations, technicals."""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── RSI (Wilder's exponential smoothing) ─────────────────────────────────────
def _rsi(series: pd.Series, window: int = 14) -> float:
    delta = series.diff().dropna()
    gains  = delta.clip(lower=0)
    losses = (-delta.clip(upper=0))
    avg_g = gains.ewm(alpha=1 / window, min_periods=window).mean().iloc[-1]
    avg_l = losses.ewm(alpha=1 / window, min_periods=window).mean().iloc[-1]
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)


# ── Public entry point ────────────────────────────────────────────────────────
def compute_insights(
    close_df: pd.DataFrame,
    prices_data: list,
    macro_data: list,
) -> dict:
    """
    Returns a dict with keys:
      breadth         – {n_up, n_dn, pct_up}
      risk_score      – float [-1, +1]
      risk_label      – 'Risk-On' | 'Neutral' | 'Risk-Off'
      correlations    – {pair_key: float}
      technicals      – {ticker: {last, sma50, sma200, pct_from_sma50,
                                   pct_from_sma200, rsi14, high_52w, low_52w}}
    """
    result: dict = {}

    # ── Breadth ───────────────────────────────────────────────────
    pcts = [p.get('daily_pct') for p in prices_data if p.get('daily_pct') is not None]
    n_up  = sum(1 for x in pcts if x > 0)
    n_dn  = sum(1 for x in pcts if x < 0)
    result['breadth'] = {
        'n_up':    n_up,
        'n_dn':    n_dn,
        'pct_up':  round(n_up / len(pcts) * 100, 1) if pcts else 50.0,
    }

    # ── Risk-on / Risk-off score ──────────────────────────────────
    # Each component normalized so a ~1σ move ≈ 0.3–0.5 units
    components = []

    def _get_pct(ticker):
        t = next((p for p in prices_data if p['ticker'] == ticker), None)
        return t.get('daily_pct') if t else None

    spy_pct = _get_pct('SPY')
    if spy_pct is not None:
        components.append(spy_pct / 1.5)

    qqq_pct = _get_pct('QQQ')
    if qqq_pct is not None:
        components.append(qqq_pct / 2.0)

    vix_val = next((m['value'] for m in macro_data if m['series_id'] == 'VIXCLS'), None)
    if vix_val is not None:
        components.append(-(vix_val - 18) / 8)   # 18 = neutral; higher VIX = risk-off

    dxy_pct = _get_pct('DX-Y.NYB')
    if dxy_pct is not None:
        components.append(-dxy_pct / 0.8)          # stronger dollar = risk-off

    gold_pct = _get_pct('GC=F')
    if gold_pct is not None:
        components.append(-gold_pct / 1.5)          # gold up = risk-off

    if components:
        raw = float(np.mean(components))
        score = float(np.clip(raw / 3.0, -1.0, 1.0))
    else:
        score = 0.0

    result['risk_score'] = round(score, 3)
    result['risk_label'] = (
        'Risk-On'  if score >  0.15 else
        'Risk-Off' if score < -0.15 else
        'Neutral'
    )

    # ── Correlations (30-day daily returns) ───────────────────────
    correlations = {}
    if not close_df.empty:
        recent = close_df.tail(31).pct_change().dropna()
        for a, b in [('SPY', 'BTC-USD'), ('SPY', 'GC=F'), ('SPY', 'DX-Y.NYB')]:
            if a in recent.columns and b in recent.columns:
                corr = recent[a].corr(recent[b])
                key  = f"{a}_vs_{b}"
                correlations[key] = round(float(corr), 3) if not pd.isna(corr) else None
    result['correlations'] = correlations

    # ── Technicals (SPY + QQQ) ───────────────────────────────────
    technicals = {}
    if not close_df.empty:
        for ticker in ['SPY', 'QQQ']:
            if ticker not in close_df.columns:
                continue
            s = close_df[ticker].dropna()
            if len(s) < 50:
                continue
            last    = float(s.iloc[-1])
            sma50   = float(s.tail(50).mean())
            sma200  = float(s.tail(200).mean()) if len(s) >= 200 else None
            rsi14   = _rsi(s)
            h52     = float(s.tail(252).max())
            l52     = float(s.tail(252).min())

            technicals[ticker] = {
                'last':              round(last, 2),
                'sma50':             round(sma50, 2),
                'sma200':            round(sma200, 2) if sma200 else None,
                'pct_from_sma50':    round((last - sma50)  / sma50  * 100, 2),
                'pct_from_sma200':   round((last - sma200) / sma200 * 100, 2) if sma200 else None,
                'rsi14':             rsi14,
                'high_52w':          round(h52, 2),
                'low_52w':           round(l52, 2),
                'pct_from_52w_high': round((last - h52) / h52 * 100, 2),
            }

    result['technicals'] = technicals
    logger.info(
        f"Insights: breadth {result['breadth']['n_up']}/{len(pcts)} up  |  "
        f"risk {result['risk_label']} ({result['risk_score']:+.2f})"
    )
    return result
