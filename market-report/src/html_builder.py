"""Generate the daily market report as a self-contained HTML page."""

import io
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / 'templates'
PAGES_BASE    = 'https://ricsarda.github.io/market-report'

_TICKER_GROUP_COLORS = {
    'US Equities':   '#2563EB',
    'International': '#7C3AED',
    'Crypto':        '#F97316',
    'Commodities':   '#16A34A',
    'FX & Dollar':   '#0D9488',
}
_THEME_COLORS = {
    'Inflation':     '#F97316',
    'Rates & Yields':'#2563EB',
    'Growth':        '#16A34A',
    'Labor':         '#7C3AED',
    'Liquidity & FX':'#0D9488',
    'Sentiment':     '#D97706',
    'Credit & Risk': '#BE123C',
    'Volatility':    '#7C3AED',
}


# ── Formatters ────────────────────────────────────────────────────────────────
def _fmt_price(val) -> str:
    if val is None:
        return '—'
    try:
        v = float(val)
        if v >= 10_000: return f'{v:,.0f}'
        if v >= 100:    return f'{v:,.2f}'
        if v >= 1:      return f'{v:.4f}'
        return f'{v:.6f}'
    except Exception:
        return '—'


def _fmt_pct(val) -> str:
    if val is None:
        return '—'
    try:
        v = float(val)
        return f'+{v:.2f}%' if v >= 0 else f'{v:.2f}%'
    except Exception:
        return '—'


def _cls(val) -> str:
    if val is None:
        return 'neu'
    try:
        return 'pos' if float(val) >= 0 else 'neg'
    except Exception:
        return 'neu'


# ── SVG chart generators ──────────────────────────────────────────────────────
def _svg_from_fig(fig) -> str:
    """Render a matplotlib figure to an inline SVG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format='svg', bbox_inches='tight')
    buf.seek(0)
    svg = buf.read().decode('utf-8')
    idx = svg.find('<svg')
    return svg[idx:] if idx != -1 else svg


def _movers_svg(prices_data: list) -> str:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        top = sorted(
            [p for p in prices_data if p.get('daily_pct') is not None],
            key=lambda x: abs(x['daily_pct']), reverse=True,
        )[:10]
        top = list(reversed(top))
        labels = [p['ticker'] for p in top]
        vals   = [p['daily_pct'] for p in top]
        clrs   = ['#2e7d32' if v >= 0 else '#c62828' for v in vals]

        fig, ax = plt.subplots(figsize=(7, 2.6))
        ax.barh(labels, vals, color=clrs, height=0.6)
        ax.axvline(0, color='#94a3b8', linewidth=0.8)
        ax.set_xlabel('Daily Δ%', fontsize=8, color='#666')
        ax.tick_params(labelsize=7.5, colors='#374151')
        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color('#e2e8f0')
        for bar, val in zip(ax.patches, vals):
            offset = 0.06 if val >= 0 else -0.06
            ha = 'left' if val >= 0 else 'right'
            ax.text(val + offset, bar.get_y() + bar.get_height() / 2,
                    f'{val:+.2f}%', va='center', ha=ha, fontsize=7, color='#374151')
        ax.set_facecolor('#fafafa')
        fig.patch.set_facecolor('white')
        plt.tight_layout(pad=0.4)
        svg = _svg_from_fig(fig)
        plt.close(fig)
        return svg
    except Exception as e:
        logger.debug(f'Movers SVG failed: {e}')
        return ''


def _yield_curve_svg(macro_data: list) -> str:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        pts = [
            (lbl, next((m['value'] for m in macro_data if m['series_id'] == sid), None))
            for sid, lbl in [('DGS2','2Y'), ('DGS5','5Y'), ('DGS10','10Y'), ('DGS30','30Y')]
        ]
        pts = [(l, v) for l, v in pts if v is not None]
        if len(pts) < 2:
            return ''
        labels, vals = zip(*pts)
        inverted = vals[-1] < vals[0]
        color = '#c62828' if inverted else '#2563eb'

        fig, ax = plt.subplots(figsize=(3.5, 2.4))
        xs = list(range(len(labels)))
        ax.plot(xs, vals, 'o-', color=color, linewidth=2, markersize=5, zorder=3)
        ax.fill_between(xs, vals, min(vals) - 0.05, alpha=0.10, color=color)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylabel('Yield (%)', fontsize=7.5, color='#666')
        ax.tick_params(labelsize=7.5, colors='#374151')
        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color('#e2e8f0')
        sfx = ' (INVERTED)' if inverted else ''
        ax.set_title(f'Yield Curve{sfx}', fontsize=9, fontweight='bold', color=color)
        for i, (lbl, val) in enumerate(zip(labels, vals)):
            ax.annotate(f'{val:.2f}%', (i, val), textcoords='offset points',
                        xytext=(0, 7), ha='center', fontsize=7, color='#374151')
        ax.set_facecolor('#fafafa')
        fig.patch.set_facecolor('white')
        plt.tight_layout(pad=0.4)
        svg = _svg_from_fig(fig)
        plt.close(fig)
        return svg
    except Exception as e:
        logger.debug(f'Yield curve SVG failed: {e}')
        return ''


def _sector_heatmap_svg(sector_data: dict) -> str:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as mp

        if not sector_data:
            return ''
        items = list(sector_data.items())
        n = len(items)
        fig, ax = plt.subplots(figsize=(7, 1.15))
        ax.set_xlim(0, n)
        ax.set_ylim(0, 1)
        ax.axis('off')
        fig.patch.set_facecolor('white')
        max_abs = 3.0
        for i, (ticker, data) in enumerate(items):
            pct = data.get('daily_pct') or 0
            intensity = min(abs(pct) / max_abs, 1.0)
            if pct >= 0:
                bg = (max(0.72, 1 - intensity * 0.45), 1.0, max(0.72, 1 - intensity * 0.45))
            else:
                bg = (1.0, max(0.72, 1 - intensity * 0.45), max(0.72, 1 - intensity * 0.45))
            rect = mp.FancyBboxPatch(
                (i + 0.04, 0.06), 0.92, 0.88,
                boxstyle='round,pad=0.02',
                facecolor=bg, edgecolor='white', linewidth=1.2,
            )
            ax.add_patch(rect)
            ax.text(i + 0.5, 0.64, ticker, ha='center', va='center',
                    fontsize=6.5, fontweight='bold', color='#14213d')
            ax.text(i + 0.5, 0.28, f'{pct:+.1f}%', ha='center', va='center',
                    fontsize=7.5, fontweight='bold',
                    color='#2e7d32' if pct >= 0 else '#c62828')
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
        svg = _svg_from_fig(fig)
        plt.close(fig)
        return svg
    except Exception as e:
        logger.debug(f'Sector heatmap SVG failed: {e}')
        return ''


# ── Data preparation ──────────────────────────────────────────────────────────
def _build_kpis(prices_data: list, macro_data: list) -> list:
    def _find(ticker):
        return next((p for p in prices_data if p['ticker'] == ticker), None)

    def _open_or_daily(p):
        if p is None:
            return None
        return p.get('open_pct') if p.get('open_pct') is not None else p.get('daily_pct')

    spy   = _find('SPY')
    qqq   = _find('QQQ')
    vix   = next((m for m in macro_data if m['series_id'] == 'VIXCLS'), None)
    dgs10 = next((m for m in macro_data if m['series_id'] == 'DGS10'), None)

    spy_pct = _open_or_daily(spy)
    qqq_pct = _open_or_daily(qqq)
    return [
        {'label': 'S&P 500',    'value': _fmt_pct(spy_pct),  'cls': _cls(spy_pct)},
        {'label': 'Nasdaq 100', 'value': _fmt_pct(qqq_pct),  'cls': _cls(qqq_pct)},
        {'label': 'VIX',
         'value': f"{vix['value']:.1f}" if vix and vix.get('value') else '—',
         'cls': 'neu'},
        {'label': '10Y Yield',
         'value': f"{dgs10['value']:.2f}%" if dgs10 and dgs10.get('value') else '—',
         'cls': 'neu'},
    ]


def _build_price_groups(prices_data: list, ticker_groups: dict, has_open: bool) -> list:
    t2g = {}
    if ticker_groups:
        for grp, tickers in ticker_groups.items():
            for t in tickers:
                t2g[t] = grp

    groups: dict[str, list] = {}
    order: list[str] = []
    for item in prices_data:
        grp = t2g.get(item['ticker'], 'Other')
        if grp not in groups:
            groups[grp] = []
            order.append(grp)
        groups[grp].append({
            'ticker':      item['ticker'],
            'name':        item['name'],
            'prev_close':  _fmt_price(item.get('prev_close')),
            'daily_pct':   _fmt_pct(item.get('daily_pct')),
            'daily_cls':   _cls(item.get('daily_pct')),
            'open_price':  _fmt_price(item.get('open_price')) if has_open else None,
            'open_pct':    _fmt_pct(item.get('open_pct'))     if has_open else None,
            'open_cls':    _cls(item.get('open_pct'))         if has_open else None,
            'monthly_pct': _fmt_pct(item.get('monthly_pct')),
            'monthly_cls': _cls(item.get('monthly_pct')),
            'yearly_pct':  _fmt_pct(item.get('yearly_pct')),
            'yearly_cls':  _cls(item.get('yearly_pct')),
        })

    return [
        {'name': grp, 'color': _TICKER_GROUP_COLORS.get(grp, '#2D4A6B'), 'rows': groups[grp]}
        for grp in order
    ]


def _build_macro_groups(macro_data: list, macro_groups: dict) -> list:
    s2g = {}
    if macro_groups:
        for grp, sids in macro_groups.items():
            for sid in sids:
                s2g[sid] = grp

    groups: dict[str, list] = {}
    order: list[str] = []
    for item in macro_data:
        grp = s2g.get(item['series_id'], 'Other')
        if grp not in groups:
            groups[grp] = []
            order.append(grp)
        groups[grp].append({
            'name':      item['name'],
            'series_id': item['series_id'],
            'value_fmt': item.get('value_fmt', '—'),
            'as_of':     item.get('as_of', ''),
            'frequency': (item.get('frequency') or 'D')[0],
            'month_pct': _fmt_pct(item.get('month_pct')),
            'month_cls': _cls(item.get('month_pct')),
            'year_pct':  _fmt_pct(item.get('year_pct')),
            'year_cls':  _cls(item.get('year_pct')),
        })

    return [
        {'name': grp, 'color': _THEME_COLORS.get(grp, '#2D4A6B'), 'rows': groups[grp]}
        for grp in order
    ]


# ── Public entry point ────────────────────────────────────────────────────────
def build_html(
    report_date: str,
    prices_data: list,
    macro_data: list,
    news_data: list,
    summary_bullets: list,
    signals: list,
    close_df=None,
    ticker_groups: dict = None,
    macro_groups: dict = None,
    sector_data: dict = None,
    narrative_paragraphs: list = None,
    narrative_provider: str = 'rules',
    calendar: list = None,
    features: dict = None,
    insights: dict = None,
    earnings_data: list = None,
    cot_data: list = None,
    out_path: str = None,
) -> str:
    """
    Render a self-contained HTML market report.
    Returns the HTML string; also writes UTF-8 to out_path if provided.
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(['html']),
    )
    tmpl = env.get_template('report.html.j2')

    f        = features or {}
    ins      = insights or {}
    has_open = any(p.get('open_price') is not None for p in prices_data)

    risk_label = ins.get('risk_label', 'Neutral')
    risk_score = ins.get('risk_score', 0.0)
    risk_cls   = 'pos' if risk_score > 0.1 else ('neg' if risk_score < -0.1 else 'neu')
    b = ins.get('breadth', {})
    n_up  = b.get('n_up', 0)
    total = n_up + b.get('n_dn', 0)
    breadth_str = (
        f'Breadth at open: {n_up}/{total} tracked assets printed positive'
        if total else ''
    )

    movers_svg = _movers_svg(prices_data) if f.get('charts', True) and prices_data else ''
    sector_svg = _sector_heatmap_svg(sector_data) if f.get('sector_heatmap', True) and sector_data else ''
    yield_svg  = _yield_curve_svg(macro_data) if f.get('charts', True) and macro_data else ''

    ctx = dict(
        report_date        = report_date,
        generated_at       = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        pages_url          = PAGES_BASE,
        kpis               = _build_kpis(prices_data, macro_data),
        risk_label         = risk_label,
        risk_score         = f'{risk_score:+.2f}',
        risk_cls           = risk_cls,
        breadth_str        = breadth_str,
        summary            = summary_bullets or [],
        signals            = signals or [],
        has_open           = has_open,
        price_groups       = _build_price_groups(prices_data, ticker_groups, has_open),
        macro_groups_data  = _build_macro_groups(macro_data, macro_groups),
        movers_svg         = movers_svg,
        sector_svg         = sector_svg,
        yield_svg          = yield_svg,
        narrative          = narrative_paragraphs or [],
        narrative_provider = narrative_provider,
        news               = news_data or [],
        calendar           = calendar or [],
        earnings           = earnings_data or [],
        cot                = cot_data or [],
        features           = f,
    )

    html_str = tmpl.render(**ctx)

    if out_path:
        Path(out_path).write_text(html_str, encoding='utf-8')
        logger.info(f'HTML ready: {out_path}')

    return html_str
