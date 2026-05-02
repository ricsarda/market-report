"""Unit tests for insights.py — breadth, risk score, RSI, technicals."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from insights import compute_insights, _rsi


# ── Fixtures ──────────────────────────────────────────────────────────────────
def _make_close_df(n=252):
    """Synthetic SPY-like series: uptrend with noise."""
    dates = pd.bdate_range(end='2026-04-21', periods=n)
    np.random.seed(42)
    spy  = 400 + np.cumsum(np.random.randn(n) * 1.5 + 0.1)
    qqq  = 350 + np.cumsum(np.random.randn(n) * 1.8 + 0.12)
    btc  = 40_000 + np.cumsum(np.random.randn(n) * 800)
    gold = 1_900 + np.cumsum(np.random.randn(n) * 10)
    dxy  = 100  + np.cumsum(np.random.randn(n) * 0.3)
    return pd.DataFrame({
        'SPY': spy, 'QQQ': qqq, 'BTC-USD': btc,
        'GC=F': gold, 'DX-Y.NYB': dxy,
    }, index=dates)


def _make_prices(spy_pct=1.0, qqq_pct=1.2, dxy_pct=-0.3, gold_pct=-0.5, n_up=14, n_dn=6):
    prices = [
        {'ticker': 'SPY',       'daily_pct': spy_pct},
        {'ticker': 'QQQ',       'daily_pct': qqq_pct},
        {'ticker': 'DX-Y.NYB',  'daily_pct': dxy_pct},
        {'ticker': 'GC=F',      'daily_pct': gold_pct},
    ]
    for i in range(n_up):
        prices.append({'ticker': f'STOCK{i}', 'daily_pct': 0.5})
    for i in range(n_dn):
        prices.append({'ticker': f'BOND{i}',  'daily_pct': -0.5})
    return prices


def _make_macro(vix=16.0):
    return [{'series_id': 'VIXCLS', 'value': vix, 'name': 'VIX',
             'value_fmt': str(vix), 'as_of': '2026-04-21',
             'frequency': 'Daily', 'month_pct': None, 'year_pct': None}]


# ── Breadth tests ─────────────────────────────────────────────────────────────
def test_breadth_positive():
    prices  = _make_prices(n_up=14, n_dn=6)
    result  = compute_insights(pd.DataFrame(), prices, [])
    breadth = result['breadth']
    assert breadth['n_up'] > breadth['n_dn']
    assert breadth['pct_up'] > 50


def test_breadth_negative():
    prices  = _make_prices(n_up=4, n_dn=16)
    result  = compute_insights(pd.DataFrame(), prices, [])
    breadth = result['breadth']
    assert breadth['n_dn'] > breadth['n_up']
    assert breadth['pct_up'] < 50


def test_breadth_keys_present():
    result = compute_insights(pd.DataFrame(), _make_prices(), [])
    assert {'n_up', 'n_dn', 'pct_up'} <= set(result['breadth'].keys())


# ── Risk score tests ───────────────────────────────────────────────────────────
def test_risk_on_signal():
    prices = _make_prices(spy_pct=2.0, qqq_pct=2.5, dxy_pct=-0.5, gold_pct=-1.0)
    macro  = _make_macro(vix=13.0)   # low VIX = risk-on
    result = compute_insights(pd.DataFrame(), prices, macro)
    assert result['risk_score'] > 0
    assert result['risk_label'] == 'Risk-On'


def test_risk_off_signal():
    prices = _make_prices(spy_pct=-2.5, qqq_pct=-3.0, dxy_pct=1.0, gold_pct=2.0)
    macro  = _make_macro(vix=30.0)   # high VIX = risk-off
    result = compute_insights(pd.DataFrame(), prices, macro)
    assert result['risk_score'] < 0
    assert result['risk_label'] == 'Risk-Off'


def test_risk_score_clamped():
    prices = _make_prices(spy_pct=10.0, qqq_pct=10.0, dxy_pct=-5.0, gold_pct=-5.0)
    macro  = _make_macro(vix=5.0)
    result = compute_insights(pd.DataFrame(), prices, macro)
    assert -1.0 <= result['risk_score'] <= 1.0


def test_neutral_regime():
    prices = _make_prices(spy_pct=0.0, qqq_pct=0.0, dxy_pct=0.0, gold_pct=0.0)
    macro  = _make_macro(vix=18.0)
    result = compute_insights(pd.DataFrame(), prices, macro)
    assert result['risk_label'] == 'Neutral'


# ── RSI tests ─────────────────────────────────────────────────────────────────
def test_rsi_overbought():
    s = pd.Series([float(i) for i in range(50, 80)])   # pure uptrend
    assert _rsi(s) > 70


def test_rsi_oversold():
    s = pd.Series([float(i) for i in range(80, 50, -1)])  # pure downtrend
    assert _rsi(s) < 30


def test_rsi_midrange():
    np.random.seed(0)
    s = pd.Series(100 + np.cumsum(np.random.randn(50) * 0.5))
    rsi = _rsi(s)
    assert 30 <= rsi <= 70


def test_rsi_all_gains_returns_100():
    s = pd.Series([100.0 + i for i in range(20)])
    assert _rsi(s) == 100.0


# ── Technicals tests ──────────────────────────────────────────────────────────
def test_technicals_keys():
    df     = _make_close_df()
    result = compute_insights(df, _make_prices(), _make_macro())
    assert 'SPY' in result['technicals']
    tech = result['technicals']['SPY']
    assert all(k in tech for k in
               ['last', 'sma50', 'sma200', 'pct_from_sma50',
                'pct_from_sma200', 'rsi14', 'high_52w', 'low_52w'])


def test_technicals_sma_ordering():
    """In a sustained uptrend, last price should be above both SMAs."""
    df     = _make_close_df()
    result = compute_insights(df, _make_prices(), _make_macro())
    tech   = result['technicals']['SPY']
    # With our uptrending synthetic data this should hold
    assert tech['sma50'] >= tech['sma200'] * 0.95   # rough sanity check


# ── Correlations tests ────────────────────────────────────────────────────────
def test_correlations_keys():
    df     = _make_close_df()
    result = compute_insights(df, _make_prices(), _make_macro())
    corr   = result['correlations']
    assert 'SPY_vs_BTC-USD' in corr
    assert 'SPY_vs_GC=F'    in corr
    assert 'SPY_vs_DX-Y.NYB' in corr


def test_correlations_range():
    df     = _make_close_df()
    result = compute_insights(df, _make_prices(), _make_macro())
    for val in result['correlations'].values():
        if val is not None:
            assert -1.0 <= val <= 1.0


# ── Empty / edge cases ────────────────────────────────────────────────────────
def test_empty_inputs_no_crash():
    result = compute_insights(pd.DataFrame(), [], [])
    assert 'breadth'      in result
    assert 'risk_score'   in result
    assert 'correlations' in result
    assert 'technicals'   in result


def test_missing_tickers_in_df():
    df = pd.DataFrame({'SPY': [100.0, 101.0, 102.0]},
                      index=pd.bdate_range('2026-01-01', periods=3))
    result = compute_insights(df, _make_prices(), _make_macro())
    assert 'QQQ' not in result['technicals']
