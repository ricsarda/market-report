"""Build the daily market report PDF using ReportLab."""

import io
import logging
import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, Image, KeepTogether,
    NextPageTemplate, PageBreak, PageTemplate, SimpleDocTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

logger = logging.getLogger(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY        = HexColor('#1A2B4A')
STEEL_BLUE  = HexColor('#2563EB')
LIGHT_BLUE  = HexColor('#EFF6FF')
POSITIVE    = HexColor('#16A34A')
NEGATIVE    = HexColor('#DC2626')
NEUTRAL     = HexColor('#6B7280')
BORDER      = HexColor('#E2E8F0')
HDR_BG      = HexColor('#1A2B4A')
GRP_BG      = HexColor('#2D4A6B')
KPI_POS_BG  = HexColor('#DCFCE7')
KPI_NEG_BG  = HexColor('#FEE2E2')
KPI_NEU_BG  = HexColor('#F1F5F9')
WHITE       = colors.white

PAGE_W, PAGE_H = LETTER
MARGIN    = 0.65 * inch
CONTENT_W = PAGE_W - 2 * MARGIN

_THEME_COLORS = {
    'Inflation':       '#F97316',
    'Rates & Yields':  '#2563EB',
    'Growth':          '#16A34A',
    'Labor':           '#7C3AED',
    'Liquidity & FX':  '#0D9488',
    'Sentiment':       '#D97706',
    'Credit & Risk':   '#BE123C',
    'Volatility':      '#7C3AED',
}
_TICKER_GROUP_COLORS = {
    'US Equities':   '#2563EB',
    'International': '#7C3AED',
    'Crypto':        '#F97316',
    'Commodities':   '#16A34A',
    'FX & Dollar':   '#0D9488',
}


# ── XML escaping ──────────────────────────────────────────────────────────────
def _x(text) -> str:
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


# ── Number formatters ─────────────────────────────────────────────────────────
def _fmt_price(val):
    if val is None: return '—'
    if val >= 10_000: return f"{val:,.0f}"
    if val >= 100:    return f"{val:,.2f}"
    if val >= 1:      return f"{val:.4f}"
    return f"{val:.6f}"

def _fmt_pct(val):
    if val is None: return '—'
    return f"+{val:.2f}%" if val >= 0 else f"{val:.2f}%"


# ── Paragraph styles ──────────────────────────────────────────────────────────
def _styles():
    b = dict(fontName='Helvetica', fontSize=8, leading=11)
    return {
        'section':    ParagraphStyle('section',   fontName='Helvetica-Bold', fontSize=10,
                                     textColor=NAVY, spaceBefore=10, spaceAfter=4,
                                     keepWithNext=1),
        'bullet':     ParagraphStyle('bullet',    fontName='Helvetica', fontSize=9,
                                     textColor=HexColor('#1F2937'), leading=13, leftIndent=10),
        'footnote':   ParagraphStyle('footnote',  fontName='Helvetica-Oblique', fontSize=7,
                                     textColor=NEUTRAL, leading=9),
        'narrative':  ParagraphStyle('narrative', fontName='Helvetica', fontSize=9,
                                     textColor=HexColor('#1F2937'), leading=13, spaceAfter=6),
        'narr_label': ParagraphStyle('narr_label',fontName='Helvetica-Oblique', fontSize=7,
                                     textColor=NEUTRAL, spaceAfter=4),
        'cal_hdr':    ParagraphStyle('cal_hdr',   fontName='Helvetica-Bold', fontSize=8,
                                     textColor=NAVY),
        'th':         ParagraphStyle('th',        fontName='Helvetica-Bold', fontSize=8,
                                     textColor=WHITE, alignment=TA_CENTER, leading=10),
        'td':         ParagraphStyle('td',        **b),
        'td_r':       ParagraphStyle('td_r',      alignment=TA_RIGHT, **b),
        'td_bold':    ParagraphStyle('td_bold',   fontName='Helvetica-Bold', fontSize=8, leading=11),
        'td_muted':   ParagraphStyle('td_muted',  fontName='Helvetica', fontSize=7.5,
                                     textColor=NEUTRAL, leading=10),
        'td_muted_r': ParagraphStyle('td_muted_r',fontName='Helvetica', fontSize=7.5,
                                     textColor=NEUTRAL, alignment=TA_RIGHT, leading=10),
        'pct_pos':    ParagraphStyle('pct_pos',   fontName='Helvetica-Bold', fontSize=8,
                                     textColor=POSITIVE, alignment=TA_RIGHT, leading=11),
        'pct_neg':    ParagraphStyle('pct_neg',   fontName='Helvetica-Bold', fontSize=8,
                                     textColor=NEGATIVE, alignment=TA_RIGHT, leading=11),
        'pct_neu':    ParagraphStyle('pct_neu',   fontName='Helvetica', fontSize=8,
                                     textColor=NEUTRAL, alignment=TA_RIGHT, leading=11),
        'kpi_lbl':    ParagraphStyle('kpi_lbl',   fontName='Helvetica', fontSize=6.5,
                                     textColor=NEUTRAL, alignment=TA_CENTER, leading=8),
        'kpi_val_pos':ParagraphStyle('kpi_vp',    fontName='Helvetica-Bold', fontSize=12,
                                     textColor=POSITIVE, alignment=TA_CENTER, leading=14),
        'kpi_val_neg':ParagraphStyle('kpi_vn',    fontName='Helvetica-Bold', fontSize=12,
                                     textColor=NEGATIVE, alignment=TA_CENTER, leading=14),
        'kpi_val_neu':ParagraphStyle('kpi_vne',   fontName='Helvetica-Bold', fontSize=12,
                                     textColor=NAVY, alignment=TA_CENTER, leading=14),
        # Cover-page specific — no spaceBefore/spaceAfter; explicit Spacers used instead
        'cover_title': ParagraphStyle('cover_title', fontName='Helvetica-Bold', fontSize=30,
                                      leading=36, textColor=NAVY, alignment=TA_CENTER),
        'cover_sub':   ParagraphStyle('cover_sub',   fontName='Helvetica', fontSize=11,
                                      leading=15, textColor=NEUTRAL, alignment=TA_CENTER),
        'cover_sec':   ParagraphStyle('cover_sec',   fontName='Helvetica-Bold', fontSize=12,
                                      textColor=NAVY, spaceBefore=8, spaceAfter=5),
        'cover_mood':  ParagraphStyle('cover_mood',  fontName='Helvetica', fontSize=10,
                                      textColor=HexColor('#1F2937'), leading=15,
                                      leftIndent=10, spaceAfter=6),
        'cover_theme': ParagraphStyle('cover_theme', fontName='Helvetica', fontSize=9,
                                      textColor=HexColor('#1F2937'), leading=13, leftIndent=10),
    }


def _pct_para(val, st):
    text = _fmt_pct(val)
    if val is None:
        return Paragraph(text, st['pct_neu'])
    return Paragraph(text, st['pct_pos'] if val >= 0 else st['pct_neg'])


def _base_table_style():
    return TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), HDR_BG),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [WHITE, LIGHT_BLUE]),
        ('GRID',          (0, 0), (-1, -1), 0.25, BORDER),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
    ])


# ── Logo helpers ──────────────────────────────────────────────────────────────
def _logo_transparent_buf(logo_path: str, white_threshold: int = 240):
    """Return BytesIO of logo PNG with white background knocked to alpha=0."""
    try:
        import numpy as np
        from PIL import Image as PILImage
        img = PILImage.open(logo_path).convert('RGBA')
        data = np.array(img, dtype=np.uint8)
        white = ((data[:, :, 0] >= white_threshold) &
                 (data[:, :, 1] >= white_threshold) &
                 (data[:, :, 2] >= white_threshold))
        data[white, 3] = 0
        result = PILImage.fromarray(data)
        buf = io.BytesIO()
        result.save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception as e:
        logger.debug(f"Logo transparency conversion failed: {e}")
        return None


def _logo_aspect(logo_path: str) -> float:
    """Return width/height ratio of the logo PNG."""
    try:
        from PIL import Image as PILImage
        img = PILImage.open(logo_path)
        return img.width / img.height if img.height else 1.0
    except Exception:
        return 1.0


# ── Watermark buffer (PIL pre-bakes opacity) ──────────────────────────────────
def _watermark_buf(logo_path: str, opacity: float = 0.05):
    try:
        from PIL import Image as PILImage
        img = PILImage.open(logo_path).convert('RGBA')
        r, g, b, a = img.split()
        a = a.point(lambda x: int(x * opacity))
        img.putalpha(a)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception:
        return None


# ── Chart helpers (matplotlib, lazy import) ──────────────────────────────────
def _sparkline(values: list, positive: bool = True, w=0.88, h=0.28) -> Image:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        color = '#16A34A' if positive else '#DC2626'
        fig, ax = plt.subplots(figsize=(w, h), dpi=100)
        xs = list(range(len(values)))
        ax.plot(xs, values, color=color, linewidth=1.4)
        ax.fill_between(xs, values, min(values), alpha=0.18, color=color)
        ax.set_xlim(0, max(len(values) - 1, 1))
        ax.axis('off')
        fig.patch.set_alpha(0)
        ax.patch.set_alpha(0)
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight',
                    pad_inches=0.01, transparent=True, dpi=100)
        plt.close(fig)
        buf.seek(0)
        return Image(buf, width=w * inch, height=h * inch)
    except Exception:
        return Spacer(w * inch, h * inch)


def _movers_chart(prices_data: list) -> Image:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        W, H = 7.0, 2.6
        top10 = sorted(
            [p for p in prices_data if p.get('daily_pct') is not None],
            key=lambda x: abs(x['daily_pct']), reverse=True
        )[:10]
        top10 = list(reversed(top10))
        labels = [p['ticker'] for p in top10]
        vals   = [p['daily_pct'] for p in top10]
        clrs   = ['#16A34A' if v >= 0 else '#DC2626' for v in vals]

        fig, ax = plt.subplots(figsize=(W, H))
        bars = ax.barh(labels, vals, color=clrs, height=0.6)
        ax.axvline(0, color='#94A3B8', linewidth=0.8, zorder=0)
        ax.set_xlabel('Daily \u0394%', fontsize=8, color='#6B7280')
        ax.tick_params(axis='both', labelsize=7.5, colors='#374151')
        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color('#E2E8F0')
        for bar, val in zip(bars, vals):
            offset = 0.06 if val >= 0 else -0.06
            ha = 'left' if val >= 0 else 'right'
            ax.text(val + offset, bar.get_y() + bar.get_height() / 2,
                    f'{val:+.2f}%', va='center', ha=ha, fontsize=7, color='#374151')
        fig.patch.set_facecolor('white')
        ax.set_facecolor('#FAFAFA')
        plt.tight_layout(pad=0.4)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', dpi=130)
        plt.close(fig)
        buf.seek(0)
        return Image(buf, width=W * inch, height=H * inch)
    except Exception as e:
        logger.debug(f"Movers chart failed: {e}")
        return Spacer(1, 0.1 * inch)


def _yield_curve_chart(macro_data: list) -> Image:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        pts = [(lbl, next((m['value'] for m in macro_data if m['series_id'] == sid), None))
               for sid, lbl in [('DGS2','2Y'),('DGS5','5Y'),('DGS10','10Y'),('DGS30','30Y')]]
        pts = [(l, v) for l, v in pts if v is not None]
        if len(pts) < 2:
            return Spacer(1, 0.1 * inch)
        labels, vals = zip(*pts)
        inverted = vals[-1] < vals[0]
        color = '#DC2626' if inverted else '#2563EB'

        fig, ax = plt.subplots(figsize=(3.2, 2.2))
        xs = list(range(len(labels)))
        ax.plot(xs, vals, 'o-', color=color, linewidth=2, markersize=5, zorder=3)
        ax.fill_between(xs, vals, min(vals) - 0.05, alpha=0.10, color=color)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylabel('Yield (%)', fontsize=7.5, color='#6B7280')
        ax.tick_params(labelsize=7.5, colors='#374151')
        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color('#E2E8F0')
        title_sfx = ' (INVERTED)' if inverted else ''
        ax.set_title(f'Yield Curve{title_sfx}', fontsize=9, fontweight='bold',
                     color='#DC2626' if inverted else '#1A2B4A')
        for i, (lbl, val) in enumerate(zip(labels, vals)):
            ax.annotate(f'{val:.2f}%', (i, val), textcoords='offset points',
                        xytext=(0, 7), ha='center', fontsize=7, color='#374151')
        ax.set_facecolor('#FAFAFA')
        fig.patch.set_facecolor('white')
        plt.tight_layout(pad=0.4)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', dpi=130)
        plt.close(fig)
        buf.seek(0)
        return Image(buf, width=3.2 * inch, height=2.2 * inch)
    except Exception as e:
        logger.debug(f"Yield curve chart failed: {e}")
        return Spacer(1, 0.1 * inch)


def _sector_heatmap(sector_data: dict) -> Image:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as mp
        if not sector_data:
            return Spacer(1, 0.1 * inch)
        items = list(sector_data.items())
        n = len(items)
        W, H = 7.0, 1.15
        fig, ax = plt.subplots(figsize=(W, H))
        ax.set_xlim(0, n)
        ax.set_ylim(0, 1)
        ax.axis('off')
        fig.patch.set_facecolor('white')
        max_abs = 3.0
        for i, (ticker, data) in enumerate(items):
            pct = data.get('daily_pct') or 0
            intensity = min(abs(pct) / max_abs, 1.0)
            if pct >= 0:
                bg = (1 - intensity * 0.45, 1, 1 - intensity * 0.45)
                bg = (max(0.72, bg[0]), bg[1], max(0.72, bg[2]))
            else:
                bg = (1, 1 - intensity * 0.45, 1 - intensity * 0.45)
                bg = (bg[0], max(0.72, bg[1]), max(0.72, bg[2]))
            rect = mp.FancyBboxPatch((i + 0.04, 0.06), 0.92, 0.88,
                                     boxstyle='round,pad=0.02',
                                     facecolor=bg, edgecolor='white', linewidth=1.2)
            ax.add_patch(rect)
            # Use ticker symbol — always unique (fixes "Cons" duplicate from name slicing)
            ax.text(i + 0.5, 0.64, ticker, ha='center', va='center',
                    fontsize=6.5, fontweight='bold', color='#1A2B4A')
            ax.text(i + 0.5, 0.28, f'{pct:+.1f}%', ha='center', va='center',
                    fontsize=7.5, color='#16A34A' if pct >= 0 else '#DC2626', fontweight='bold')
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', dpi=130, facecolor='white')
        plt.close(fig)
        buf.seek(0)
        return Image(buf, width=W * inch, height=H * inch)
    except Exception as e:
        logger.debug(f"Sector heatmap failed: {e}")
        return Spacer(1, 0.1 * inch)


# ── Page chrome callbacks ─────────────────────────────────────────────────────
def _footer(canvas, doc, report_date):
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(NEUTRAL)
    canvas.drawString(MARGIN, 0.38 * inch,
                      "Data: Yahoo Finance \xb7 FRED (Federal Reserve) \xb7 Finnhub  "
                      "\xb7  For informational purposes only. Not financial advice.")
    canvas.drawRightString(PAGE_W - MARGIN, 0.38 * inch, f"Page {doc.page}")


def _draw_cover_chrome(canvas, doc, report_date):
    """Page 1: footer only — cover content rendered as flowables."""
    canvas.saveState()
    _footer(canvas, doc, report_date)
    canvas.restoreState()


def _draw_interior_chrome(canvas, doc, logo_path, report_date,
                          watermark_buf, branding, logo_buf, aspect):
    """Pages 2+: watermark (behind) + compact header + footer."""
    canvas.saveState()

    hdr      = (branding or {}).get('header', {})
    logo_h   = hdr.get('logo_height_in', 0.60) * inch
    title_sz = hdr.get('title_size', 13)

    # ── Watermark (drawn first, sits below all flowables) ────────────
    wm_cfg = (branding or {}).get('watermark', {})
    if watermark_buf and wm_cfg.get('enabled', True):
        try:
            wm_w = wm_cfg.get('width_in', 4.5) * inch
            watermark_buf.seek(0)
            from PIL import Image as PILImage
            _tmp = PILImage.open(watermark_buf)
            wm_ratio = _tmp.height / _tmp.width if _tmp.width else 1.0
            wm_h = wm_w * wm_ratio
            watermark_buf.seek(0)
            canvas.drawImage(
                watermark_buf,
                (PAGE_W - wm_w) / 2, (PAGE_H - wm_h) / 2,
                width=wm_w, height=wm_h,
                mask='auto', preserveAspectRatio=True,
            )
        except Exception as e:
            logger.debug(f"Watermark draw failed: {e}")

    # ── Compact header ────────────────────────────────────────────────
    y_top    = PAGE_H - MARGIN + 0.15 * inch
    title_x  = MARGIN

    if logo_buf and logo_path and Path(logo_path).exists():
        try:
            logo_w_rendered = logo_h * aspect
            logo_buf.seek(0)
            ir = ImageReader(logo_buf)
            canvas.drawImage(ir,
                             MARGIN, y_top - logo_h - 0.04 * inch,
                             width=logo_w_rendered, height=logo_h,
                             mask='auto', preserveAspectRatio=False)
            title_x = MARGIN + logo_w_rendered + 0.15 * inch
        except Exception as e:
            logger.debug(f"Header logo failed: {e}")

    canvas.setFont('Helvetica-Bold', title_sz)
    canvas.setFillColor(NAVY)
    canvas.drawString(title_x, y_top - 0.28 * inch, 'DAILY MARKET REPORT')

    canvas.setFont('Helvetica', 8.5)
    canvas.setFillColor(NEUTRAL)
    canvas.drawString(title_x, y_top - 0.48 * inch,
                      f"{report_date}  \xb7  Post-Open Edition  \xb7  Automated Market Intelligence")

    canvas.setStrokeColor(STEEL_BLUE)
    canvas.setLineWidth(1.5)
    canvas.line(MARGIN, y_top - 0.62 * inch, PAGE_W - MARGIN, y_top - 0.62 * inch)

    _footer(canvas, doc, report_date)
    canvas.restoreState()


# ── Legacy single-chrome (cover_page.enabled = false) ────────────────────────
def _draw_chrome(canvas, doc, logo_path, report_date, watermark_buf=None):
    canvas.saveState()

    if watermark_buf:
        try:
            watermark_buf.seek(0)
            canvas.drawImage(
                watermark_buf,
                PAGE_W * 0.2, PAGE_H * 0.2,
                width=PAGE_W * 0.6, height=PAGE_H * 0.5,
                mask='auto', preserveAspectRatio=True,
            )
        except Exception:
            pass

    y_top   = PAGE_H - MARGIN + 0.15 * inch
    title_x = MARGIN

    if logo_path and Path(logo_path).exists():
        try:
            asp = _logo_aspect(logo_path)
            logo_h = 0.52 * inch
            logo_w = logo_h * asp
            buf = _logo_transparent_buf(logo_path)
            if buf:
                buf.seek(0)
                canvas.drawImage(ImageReader(buf),
                                 MARGIN, y_top - 0.58 * inch,
                                 width=logo_w, height=logo_h,
                                 mask='auto', preserveAspectRatio=False)
            else:
                canvas.drawImage(logo_path, MARGIN, y_top - 0.58 * inch,
                                 width=1.5 * inch, height=0.52 * inch,
                                 mask='auto', preserveAspectRatio=True)
            title_x = MARGIN + logo_w + 0.15 * inch
        except Exception:
            pass

    canvas.setFont('Helvetica-Bold', 15)
    canvas.setFillColor(NAVY)
    canvas.drawString(title_x, y_top - 0.28 * inch, 'DAILY MARKET REPORT')

    canvas.setFont('Helvetica', 8.5)
    canvas.setFillColor(NEUTRAL)
    canvas.drawString(title_x, y_top - 0.48 * inch,
                      f"{report_date}  \xb7  Post-Open Edition  \xb7  Automated Market Intelligence")

    canvas.setStrokeColor(STEEL_BLUE)
    canvas.setLineWidth(1.5)
    canvas.line(MARGIN, y_top - 0.62 * inch, PAGE_W - MARGIN, y_top - 0.62 * inch)

    _footer(canvas, doc, report_date)
    canvas.restoreState()


# ── Section builders ──────────────────────────────────────────────────────────
def _section_title(text, st):
    return [Paragraph(_x(text), st['section']),
            HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=4)]


def _build_kpi_band(prices_data, macro_data, close_df, st):
    def _get_open_pct(ticker):
        t = next((p for p in prices_data if p['ticker'] == ticker), None)
        if t is None:
            return None
        # Prefer confirmed open move; fall back to prior-session daily_pct
        return t.get('open_pct') if t.get('open_pct') is not None else t.get('daily_pct')

    def _spark_vals(ticker):
        try:
            if close_df is not None and ticker in close_df.columns:
                return close_df[ticker].dropna().tail(6).tolist()
        except Exception:
            pass
        return None

    vix   = next((m for m in macro_data if m['series_id'] == 'VIXCLS'), {})
    dgs10 = next((m for m in macro_data if m['series_id'] == 'DGS10'), {})
    top   = sorted(prices_data, key=lambda x: abs(x.get('daily_pct') or 0), reverse=True)

    spy_pct  = _get_open_pct('SPY')
    qqq_pct  = _get_open_pct('QQQ')
    dxy_pct  = _get_open_pct('DX-Y.NYB')
    top_pct  = top[0].get('daily_pct') if top else None
    top_tick = top[0]['ticker'] if top else '—'

    cards = [
        ('S&amp;P 500',    _fmt_pct(spy_pct),  spy_pct,  _spark_vals('SPY')),
        ('Nasdaq 100',     _fmt_pct(qqq_pct),  qqq_pct,  _spark_vals('QQQ')),
        ('VIX',            f"{vix.get('value','—'):.1f}" if vix.get('value') else '—',
                                               None,     None),
        ('10Y Yield',      f"{dgs10.get('value','—'):.2f}%" if dgs10.get('value') else '—',
                                               None,     None),
        ('US Dollar',      _fmt_pct(dxy_pct),  dxy_pct,  _spark_vals('DX-Y.NYB')),
        ('Top Mover',      f"{top_tick} {_fmt_pct(top_pct)}", top_pct, _spark_vals(top_tick)),
    ]

    cells, bg_cmds = [], []
    for i, (label, value, pct, spark_vals) in enumerate(cards):
        bg = KPI_NEU_BG if pct is None else (KPI_POS_BG if pct >= 0 else KPI_NEG_BG)
        vs = (st['kpi_val_neu'] if pct is None else
              st['kpi_val_pos'] if pct >= 0 else st['kpi_val_neg'])
        bg_cmds.append(('BACKGROUND', (i, 0), (i, 0), bg))
        cell = [Paragraph(label, st['kpi_lbl']),
                Paragraph(_x(value), vs)]
        if spark_vals and len(spark_vals) >= 2:
            cell.append(_sparkline(spark_vals, positive=(pct or 0) >= 0))
        cells.append(cell)

    col_w = [CONTENT_W / 6] * 6
    tbl = Table([cells], colWidths=col_w)
    tbl.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('GRID',          (0, 0), (-1, -1), 0.5, BORDER),
    ] + bg_cmds))
    return [tbl, Spacer(1, 8)]


def _build_cover_bottom(summary_bullets, insights, st):
    """TODAY'S THEME + KEY LEVELS — fills the lower half of the cover page."""
    elems = []

    # TODAY'S THEME — first 2 executive summary bullets in a light box
    theme_bullets = (summary_bullets or [])[:2]
    if theme_bullets:
        elems.append(Spacer(1, 10))
        elems.append(Paragraph("TODAY'S THEME", st['cover_sec']))
        content = [Paragraph(f"\u2022  {_x(b)}", st['cover_theme']) for b in theme_bullets]
        box = Table([[content]], colWidths=[CONTENT_W])
        box.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), LIGHT_BLUE),
            ('LEFTPADDING',   (0, 0), (-1, -1), 10),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('BOX',           (0, 0), (-1, -1), 0.5, BORDER),
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ]))
        elems.append(box)

    # KEY LEVELS — SPY and QQQ technical levels table
    tech    = (insights or {}).get('technicals', {})
    spy_t   = tech.get('SPY', {})
    qqq_t   = tech.get('QQQ', {})
    if spy_t or qqq_t:
        elems.append(Spacer(1, 10))
        elems.append(Paragraph('KEY LEVELS', st['cover_sec']))
        headers = ['', 'PREV CLOSE', 'SMA 50', 'SMA 200', '52W HIGH', '52W LOW']
        col_w   = [CONTENT_W * 0.10, CONTENT_W * 0.18, CONTENT_W * 0.18,
                   CONTENT_W * 0.18, CONTENT_W * 0.18, CONTENT_W * 0.18]
        rows = [[Paragraph(h, st['th']) for h in headers]]
        for ticker, t in [('SPY', spy_t), ('QQQ', qqq_t)]:
            if t:
                rows.append([
                    Paragraph(ticker,                          st['td_bold']),
                    Paragraph(_fmt_price(t.get('last')),       st['td_r']),
                    Paragraph(_fmt_price(t.get('sma50')),      st['td_r']),
                    Paragraph(_fmt_price(t.get('sma200')),     st['td_r']),
                    Paragraph(_fmt_price(t.get('high_52w')),   st['td_r']),
                    Paragraph(_fmt_price(t.get('low_52w')),    st['td_r']),
                ])
        tbl = Table(rows, colWidths=col_w)
        tbl.setStyle(_base_table_style())
        elems.append(tbl)

    return elems


def _build_cover_content(logo_path, report_date, prices_data, macro_data,
                         close_df, insights, summary_bullets, branding, st,
                         logo_buf=None, aspect=1.0):
    """All flowables for cover page (page 1)."""
    cov_cfg = (branding or {}).get('cover_page', {})
    logo_w  = cov_cfg.get('logo_width_in', 2.4) * inch
    logo_h  = logo_w * (1.0 / aspect) if aspect else logo_w  # preserve aspect

    elems = [Spacer(1, 2.0 * inch)]  # push hero block to upper third

    # Large centered logo — white background knocked out
    if logo_path and Path(logo_path).exists():
        try:
            if logo_buf:
                logo_buf.seek(0)
                img = Image(ImageReader(logo_buf), width=logo_w, height=logo_h)
            else:
                img = Image(logo_path, width=logo_w, height=logo_h)
            img.hAlign = 'CENTER'
            elems.append(img)
        except Exception as e:
            logger.debug(f"Cover logo failed: {e}")

    subtitle = (f"{report_date}  \xb7  Post-Open Edition  \xb7  "
                "Automated Market Intelligence")

    # Explicit spacers per spec — deterministic, not suppressed at frame edges
    elems.append(Spacer(1, 40))                                              # 40 pt gap
    elems.append(Paragraph('DAILY MARKET REPORT', st['cover_title']))
    elems.append(Spacer(1, 8))
    elems.append(Paragraph(subtitle, st['cover_sub']))
    elems.append(Spacer(1, 12))
    elems.append(HRFlowable(width='100%', thickness=1.2, color=STEEL_BLUE, spaceAfter=0))
    elems.append(Spacer(1, 10))

    # AT A GLANCE + KPI band
    elems.append(Paragraph('AT A GLANCE', st['cover_sec']))
    if prices_data or macro_data:
        elems += _build_kpi_band(prices_data or [], macro_data or [], close_df, st)

    # Market Mood
    elems.append(Paragraph('MARKET MOOD', st['cover_sec']))
    if insights:
        label  = insights.get('risk_label', 'Neutral')
        score  = insights.get('risk_score', 0.0)
        b      = insights.get('breadth', {})
        n_up   = b.get('n_up', 0)
        n_dn   = b.get('n_dn', 0)
        total  = n_up + n_dn
        bstr   = f"  \xb7  Breadth at open: {n_up}/{total} tracked assets printed positive" if total else ''
        mood   = f"{label} risk regime  \xb7  composite score {score:+.2f}{bstr}."
    else:
        mood = 'Risk data unavailable.'
    elems.append(Paragraph(mood, st['cover_mood']))

    # Lower-half fill content
    elems += _build_cover_bottom(summary_bullets, insights, st)

    return elems


def _build_summary(bullets, st):
    elems = _section_title('EXECUTIVE SUMMARY', st)
    for b in bullets:
        elems.append(Paragraph(f"\u2022  {_x(b)}", st['bullet']))
    elems.append(Spacer(1, 8))
    return [KeepTogether(elems)]


def _build_news(news_data, st):
    if not news_data:
        return []
    elems = _section_title('TOP MARKET NEWS', st)
    col_w = [CONTENT_W * 0.52, CONTENT_W * 0.13, CONTENT_W * 0.17, CONTENT_W * 0.18]
    rows  = [[Paragraph(h, st['th']) for h in ('HEADLINE', 'SOURCE', 'WHEN', 'CATEGORY')]]
    nh = ParagraphStyle('nh', fontName='Helvetica', fontSize=7.5, leading=10)
    ni = ParagraphStyle('ni', fontName='Helvetica-Oblique', fontSize=7.5,
                        textColor=STEEL_BLUE, leading=10)
    for item in news_data:
        rows.append([
            Paragraph(_x(item['headline']),  nh),
            Paragraph(_x(item['source']),    st['td_muted']),
            Paragraph(_x(item['timestamp']), st['td_muted']),
            Paragraph(_x(item['impact']),    ni),
        ])
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_base_table_style())
    tbl.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elems += [tbl, Spacer(1, 10)]
    return [KeepTogether(elems[:3])] + elems[3:]


def _build_prices(prices_data, ticker_groups, st):
    elems = _section_title('ASSET PRICES & PERFORMANCE', st)

    has_open = any(p.get('open_price') is not None for p in prices_data)

    if has_open:
        col_w   = [CONTENT_W*0.090, CONTENT_W*0.210, CONTENT_W*0.110,
                   CONTENT_W*0.095, CONTENT_W*0.110, CONTENT_W*0.090,
                   CONTENT_W*0.130, CONTENT_W*0.165]
        headers = ['TICKER','NAME','PREV CLOSE','DAILY \u0394%','OPEN','OPEN \u0394%','1M \u0394%','1Y \u0394%']
    else:
        col_w   = [CONTENT_W*0.100, CONTENT_W*0.265, CONTENT_W*0.135,
                   CONTENT_W*0.125, CONTENT_W*0.185, CONTENT_W*0.190]
        headers = ['TICKER','NAME','PREV CLOSE','DAILY \u0394%','1M \u0394%','1Y \u0394%']

    t2g = {}
    if ticker_groups:
        for grp, tickers in ticker_groups.items():
            for t in tickers:
                t2g[t] = grp

    rows, row_meta = [[Paragraph(h, st['th']) for h in headers]], ['header']
    current_grp = None

    for item in prices_data:
        grp = t2g.get(item['ticker'], 'Other')
        if grp != current_grp:
            color_hex = _TICKER_GROUP_COLORS.get(grp, '#2D4A6B')
            rows.append([Paragraph(
                f'<font color="{color_hex}">\u25cf</font>  {_x(grp.upper())}',
                ParagraphStyle('gh', fontName='Helvetica-Bold', fontSize=7.5,
                               textColor=WHITE, leading=10)
            )] + [Paragraph('', st['td'])] * (len(headers) - 1))
            row_meta.append('group')
            current_grp = grp

        if has_open:
            row = [
                Paragraph(_x(item['ticker']),              st['td_bold']),
                Paragraph(_x(item['name']),                st['td']),
                Paragraph(_fmt_price(item['prev_close']),  st['td_r']),
                _pct_para(item.get('daily_pct'),           st),
                Paragraph(_fmt_price(item.get('open_price')), st['td_r']),
                _pct_para(item.get('open_pct'),            st),
                _pct_para(item.get('monthly_pct'),         st),
                _pct_para(item.get('yearly_pct'),          st),
            ]
        else:
            row = [
                Paragraph(_x(item['ticker']),                 st['td_bold']),
                Paragraph(_x(item['name']),                   st['td']),
                Paragraph(_fmt_price(item['prev_close']),      st['td_r']),
                _pct_para(item.get('daily_pct'),               st),
                _pct_para(item.get('monthly_pct'),             st),
                _pct_para(item.get('yearly_pct'),              st),
            ]
        rows.append(row)
        row_meta.append('data')

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_base_table_style())

    extra = []
    for i, meta in enumerate(row_meta):
        if meta == 'group':
            extra += [
                ('BACKGROUND',    (0, i), (-1, i), GRP_BG),
                ('SPAN',          (0, i), (-1, i)),
                ('TOPPADDING',    (0, i), (-1, i), 2),
                ('BOTTOMPADDING', (0, i), (-1, i), 2),
            ]
    if extra:
        tbl.setStyle(TableStyle(extra))

    elems.append(tbl)
    if has_open:
        elems.append(Paragraph(
            "OPEN = session opening price at 9:30 AM ET  \xb7  "
            "Dash (\u2014) means opening data not yet available",
            st['footnote']))
    elems.append(Spacer(1, 10))
    return elems


def _build_macro(macro_data, macro_groups, st):
    if not macro_data:
        return []
    elems = _section_title('MACRO INDICATORS  (Federal Reserve / FRED)', st)

    col_w = [CONTENT_W*0.280, CONTENT_W*0.092, CONTENT_W*0.105,
             CONTENT_W*0.118, CONTENT_W*0.072, CONTENT_W*0.163, CONTENT_W*0.170]
    headers = ['INDICATOR','SERIES','VALUE','AS OF','FREQ','1M \u0394%','1Y \u0394%']

    s2g = {}
    if macro_groups:
        for grp, sids in macro_groups.items():
            for sid in sids:
                s2g[sid] = grp

    rows, row_meta = [[Paragraph(h, st['th']) for h in headers]], ['header']
    current_grp = None

    for item in macro_data:
        grp = s2g.get(item['series_id'], 'Other')
        if grp != current_grp:
            color_hex = _THEME_COLORS.get(grp, '#2D4A6B')
            rows.append([Paragraph(
                f'<font color="{color_hex}">\u25cf</font>  {_x(grp.upper())}',
                ParagraphStyle('mgh', fontName='Helvetica-Bold', fontSize=7.5,
                               textColor=WHITE, leading=10)
            )] + [Paragraph('', st['td'])] * (len(headers) - 1))
            row_meta.append('group')
            current_grp = grp

        rows.append([
            Paragraph(_x(item['name']),      st['td']),
            Paragraph(_x(item['series_id']), st['td_muted']),
            Paragraph(_x(item['value_fmt']), st['td_r']),
            Paragraph(_x(item['as_of']),     st['td_muted_r']),
            Paragraph(item['frequency'][0],
                      ParagraphStyle('freq', fontName='Helvetica', fontSize=7.5,
                                     textColor=NEUTRAL, alignment=TA_CENTER, leading=10)),
            _pct_para(item.get('month_pct'), st),
            _pct_para(item.get('year_pct'),  st),
        ])
        row_meta.append('data')

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_base_table_style())
    extra = []
    for i, meta in enumerate(row_meta):
        if meta == 'group':
            extra += [
                ('BACKGROUND',    (0, i), (-1, i), GRP_BG),
                ('SPAN',          (0, i), (-1, i)),
                ('TOPPADDING',    (0, i), (-1, i), 2),
                ('BOTTOMPADDING', (0, i), (-1, i), 2),
            ]
    if extra:
        tbl.setStyle(TableStyle(extra))

    elems += [tbl,
              Paragraph("D=Daily  \xb7  M=Monthly  \xb7  Q=Quarterly  \xb7  "
                        "\u0394% vs prior available reading of same series",
                        st['footnote']),
              Spacer(1, 10)]
    return elems


def _build_signals(signals, st):
    if not signals:
        return []
    elems = _section_title('SIGNALS TO WATCH TOMORROW', st)
    for s in signals:
        elems.append(Paragraph(f"\u2192  {_x(s)}", st['bullet']))
    # No trailing Spacer — avoid dead space at page bottom
    return [KeepTogether(elems)]


def _build_narrative(paragraphs: list, st, provider: str = 'rules'):
    if not paragraphs:
        return []
    elems = _section_title('MARKET NARRATIVE', st)
    # Only show provider label when not rules-based (avoids placeholder leak)
    if provider != 'rules':
        label = 'AI-Assisted Narrative'
        elems.append(Paragraph(f"[{label}]", st['narr_label']))
    content_rows = [Paragraph(_x(p), st['narrative']) for p in paragraphs]
    box = Table([[content_rows]], colWidths=[CONTENT_W])
    box.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), HexColor('#F0F9FF')),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BOX',           (0, 0), (-1, -1), 0.5, STEEL_BLUE),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    elems += [box, Spacer(1, 4)]   # reduced from 8 to help page count
    return elems


def _build_calendar(events: list, st):
    if not events:
        return []
    elems = _section_title('ECONOMIC CALENDAR — TODAY', st)
    col_w = [CONTENT_W * 0.60, CONTENT_W * 0.40]
    rows  = [[Paragraph('RELEASE', st['th']), Paragraph('DATE', st['th'])]]
    for ev in events[:12]:
        rows.append([
            Paragraph(_x(ev.get('name', '')), st['td']),
            Paragraph(_x(ev.get('date', '')), st['td_muted_r']),
        ])
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_base_table_style())
    elems += [tbl, Spacer(1, 6)]
    return [KeepTogether(elems)]


def _build_earnings(earnings_data: list, st):
    if not earnings_data:
        return []
    elems = _section_title('EARNINGS CALENDAR', st)
    col_w = [CONTENT_W*0.08, CONTENT_W*0.30, CONTENT_W*0.08,
             CONTENT_W*0.12, CONTENT_W*0.14, CONTENT_W*0.14, CONTENT_W*0.14]
    headers = ['TICKER', 'COMPANY', 'WHEN', 'DAY', 'EPS EST', 'EPS ACT', 'REV EST (M)']
    rows = [[Paragraph(h, st['th']) for h in headers]]

    def _fmt_eps(val):
        if val is None: return '—'
        try:    return f"{float(val):.2f}"
        except: return '—'

    def _fmt_rev(val):
        if val is None: return '—'
        try:    return f"{float(val)/1e6:,.0f}"
        except: return '—'

    for item in earnings_data:
        rows.append([
            Paragraph(_x(item.get('ticker', '')),    st['td_bold']),
            Paragraph(_x(item.get('company', '')),   st['td']),
            Paragraph(_x(item.get('when', '—')),     st['td_muted']),
            Paragraph(_x(item.get('day_label', '')), st['td_muted']),
            Paragraph(_fmt_eps(item.get('eps_estimate')), st['td_r']),
            Paragraph(_fmt_eps(item.get('eps_actual')),   st['td_r']),
            Paragraph(_fmt_rev(item.get('rev_estimate')), st['td_r']),
        ])

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_base_table_style())
    elems += [tbl, Spacer(1, 8)]
    return [KeepTogether(elems[:4])] + elems[4:]


def _build_cot(cot_data: list, st):
    if not cot_data:
        return []
    elems = _section_title('CFTC COT — NET NON-COMMERCIAL POSITIONING', st)
    col_w = [CONTENT_W*0.28, CONTENT_W*0.20, CONTENT_W*0.20,
             CONTENT_W*0.20, CONTENT_W*0.12]
    headers = ['MARKET', 'NET (CONTRACTS)', 'LONGS', 'SHORTS', 'AS OF']
    rows = [[Paragraph(h, st['th']) for h in headers]]

    for item in cot_data:
        net = item.get('net', 0)
        net_style = st['pct_pos'] if net >= 0 else st['pct_neg']
        sign = '+' if net >= 0 else ''
        rows.append([
            Paragraph(_x(item.get('label', '')),          st['td_bold']),
            Paragraph(f"{sign}{net:,}",                   net_style),
            Paragraph(f"{item.get('longs', 0):,}",        st['td_r']),
            Paragraph(f"{item.get('shorts', 0):,}",       st['td_r']),
            Paragraph(_x(item.get('as_of', '—')),         st['td_muted_r']),
        ])

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_base_table_style())
    elems.append(Paragraph(
        "Net = Non-commercial longs \u2212 shorts (large speculators).  "
        "Positive = net long (risk-on bias).  Source: CFTC Legacy Futures Only.",
        st['footnote']))
    elems += [tbl, Spacer(1, 8)]
    return [KeepTogether(elems[:4])] + elems[4:]


# ── Public entry point ────────────────────────────────────────────────────────
def build_pdf(
    output_path: str,
    report_date: str,
    prices_data: list,
    macro_data: list,
    news_data: list,
    summary_bullets: list,
    signals: list,
    logo_path: str = None,
    close_df=None,
    ticker_groups: dict = None,
    macro_groups: dict = None,
    watermark: bool = False,
    sector_data: dict = None,
    narrative_paragraphs: list = None,
    narrative_provider: str = 'rules',
    calendar: list = None,
    features: dict = None,
    insights: dict = None,
    branding: dict = None,
    earnings_data: list = None,
    cot_data: list = None,
) -> str:
    f  = features or {}
    st = _styles()
    br = branding or {}

    cover_enabled = br.get('cover_page', {}).get('enabled', False)
    wm_cfg        = br.get('watermark', {})
    wm_enabled    = wm_cfg.get('enabled', watermark)
    wm_opacity    = wm_cfg.get('opacity', 0.05)

    # Pre-compute logo assets once (PIL reads + numpy op run once per report)
    logo_buf = None
    asp      = 1.0
    if logo_path and Path(logo_path).exists():
        logo_buf = _logo_transparent_buf(logo_path)
        asp      = _logo_aspect(logo_path)

    wm_buf = None
    if wm_enabled and logo_path and Path(logo_path).exists():
        wm_buf = _watermark_buf(logo_path, opacity=wm_opacity)

    if cover_enabled:
        FOOTER_H = 0.65 * inch
        HEADER_H = 1.05 * inch

        cover_frame    = Frame(MARGIN, FOOTER_H,
                               CONTENT_W, PAGE_H - MARGIN * 0.5 - FOOTER_H,
                               id='cover')
        interior_frame = Frame(MARGIN, FOOTER_H,
                               CONTENT_W, PAGE_H - HEADER_H - FOOTER_H,
                               id='interior')

        def _cover_cb(canvas, doc):
            _draw_cover_chrome(canvas, doc, report_date)

        def _interior_cb(canvas, doc):
            _draw_interior_chrome(canvas, doc, logo_path, report_date,
                                  wm_buf, br, logo_buf, asp)

        cover_tpl    = PageTemplate(id='cover',    frames=[cover_frame],    onPage=_cover_cb)
        interior_tpl = PageTemplate(id='interior', frames=[interior_frame], onPage=_interior_cb)

        doc = BaseDocTemplate(
            output_path, pagesize=LETTER,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN * 0.5, bottomMargin=FOOTER_H,
            title=f"Daily Market Report {report_date}",
            author="Market Intelligence System",
        )
        doc.addPageTemplates([cover_tpl, interior_tpl])

        cover_flow = _build_cover_content(
            logo_path, report_date, prices_data, macro_data,
            close_df, insights, summary_bullets, br, st,
            logo_buf=logo_buf, aspect=asp,
        )
        cover_flow += [NextPageTemplate('interior'), PageBreak()]
        interior_flow = []

    else:
        def _chrome(canvas, doc):
            _draw_chrome(canvas, doc, logo_path, report_date, wm_buf)

        doc = SimpleDocTemplate(
            output_path, pagesize=LETTER,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=1.05 * inch, bottomMargin=0.65 * inch,
            title=f"Daily Market Report {report_date}",
            author="Market Intelligence System",
        )
        doc._onFirstPage  = _chrome
        doc._onLaterPages = _chrome
        cover_flow        = []
        interior_flow     = []
        if f.get('kpi_band', True) and (prices_data or macro_data):
            interior_flow += _build_kpi_band(prices_data, macro_data, close_df, st)

    # ── Interior content ───────────────────────────────────────────────
    flow = []

    flow += _build_summary(summary_bullets, st)
    flow += _build_news(news_data, st)

    # Charts — each wrapped in KeepTogether to prevent orphan titles
    if f.get('charts', True) and prices_data:
        movers_elems = _section_title('TOP 10 DAILY MOVERS', st) + \
                       [_movers_chart(prices_data), Spacer(1, 8)]
        flow.append(KeepTogether(movers_elems))

    flow += _build_prices(prices_data, ticker_groups, st)

    if f.get('sector_heatmap', True) and sector_data:
        sector_elems = _section_title('SECTOR PERFORMANCE (ETFs)', st) + \
                       [_sector_heatmap(sector_data), Spacer(1, 8)]
        flow.append(KeepTogether(sector_elems))

    flow += _build_macro(macro_data, macro_groups, st)

    if f.get('charts', True) and macro_data:
        yc = _yield_curve_chart(macro_data)
        if not isinstance(yc, Spacer):
            yc_elems = _section_title('YIELD CURVE', st) + [yc, Spacer(1, 8)]
            flow.append(KeepTogether(yc_elems))

    if f.get('narrative', True) and narrative_paragraphs:
        flow += _build_narrative(narrative_paragraphs, st, narrative_provider)

    if f.get('economic_calendar', True) and calendar:
        flow += _build_calendar(calendar, st)

    if earnings_data:
        flow += _build_earnings(earnings_data, st)

    if cot_data:
        flow += _build_cot(cot_data, st)

    flow += _build_signals(signals, st)

    # ── Build ──────────────────────────────────────────────────────────
    if cover_enabled:
        doc.build(cover_flow + interior_flow + flow)
    else:
        doc.build(interior_flow + flow,
                  onFirstPage=doc._onFirstPage,
                  onLaterPages=doc._onLaterPages)

    return output_path
