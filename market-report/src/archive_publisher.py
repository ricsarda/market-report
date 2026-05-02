"""Copy each day's HTML report into docs/ and regenerate the archive index."""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DOCS_DIR   = Path(__file__).parent.parent.parent / 'docs'
PAGES_BASE = 'https://ricsarda.github.io/market-report'


def _index_entries(limit: int = 30) -> list:
    """Scan docs/ for YYYY/MM/DD.html files and return entries newest-first."""
    entries = []
    for html in sorted(DOCS_DIR.glob('????/??/??.html'), reverse=True)[:limit]:
        parts = html.parts
        year, month, day = parts[-3], parts[-2], parts[-1].replace('.html', '')
        date_str = f'{year}-{month}-{day}'
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            label    = dt.strftime('%A, %B %-d, %Y')
            month_hd = dt.strftime('%B %Y')
        except ValueError:
            label    = date_str
            month_hd = f'{year}-{month}'
        entries.append({
            'date':  date_str,
            'label': label,
            'month': month_hd,
            'url':   f'{PAGES_BASE}/{year}/{month}/{day}.html',
        })
    return entries


def publish(html_path: str, report_date: str) -> None:
    """
    Copy html_path → docs/YYYY/MM/DD.html and rebuild docs/index.html.

    Args:
        html_path:   Absolute path to the generated day-report HTML file.
        report_date: ISO date string, e.g. '2026-05-02'.
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    src = Path(html_path)
    if not src.exists():
        logger.warning('archive_publisher: HTML not found at %s — skipping', html_path)
        return

    # ── Copy day file ─────────────────────────────────────────────────────────
    try:
        dt      = datetime.strptime(report_date, '%Y-%m-%d')
        year    = dt.strftime('%Y')
        month   = dt.strftime('%m')
        day     = dt.strftime('%d')
    except ValueError:
        logger.error('archive_publisher: bad date %r', report_date)
        return

    dest_dir = DOCS_DIR / year / month
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest     = dest_dir / f'{day}.html'
    shutil.copy2(src, dest)
    logger.info('Published %s → %s', src.name, dest)

    # ── Rebuild index ─────────────────────────────────────────────────────────
    templates_dir = Path(__file__).parent.parent / 'templates'
    env  = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(['html']),
    )
    tmpl = env.get_template('index.html.j2')

    entries = _index_entries(limit=30)
    html_str = tmpl.render(
        entries      = entries,
        generated_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        pages_url    = PAGES_BASE,
    )

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / 'index.html').write_text(html_str, encoding='utf-8')
    logger.info('Archive index updated (%d entries)', len(entries))
