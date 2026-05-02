"""Generate a 3-paragraph market narrative via LLM or rules-based fallback."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent.parent / 'config' / 'narrative_prompt.txt'


# ── Prompt builder ────────────────────────────────────────────────────────────
def _build_prompt(report_date: str, summary: list, macro: list, insights: dict) -> str:
    template = _PROMPT_FILE.read_text(encoding='utf-8') if _PROMPT_FILE.exists() else _DEFAULT_PROMPT

    macro_lines = '\n'.join(
        f"  {m['name']} ({m['series_id']}): {m['value_fmt']} as of {m['as_of']}"
        for m in macro[:10]
    )
    insights_lines = (
        f"  Breadth: {insights.get('breadth', {}).get('n_up', '?')} up / "
        f"{insights.get('breadth', {}).get('n_dn', '?')} down\n"
        f"  Risk regime: {insights.get('risk_label', 'Unknown')} "
        f"(score {insights.get('risk_score', 0):+.2f})\n"
    )
    for pair, val in insights.get('correlations', {}).items():
        if val is not None:
            insights_lines += f"  {pair.replace('_vs_', ' vs ')}: {val:+.2f} (30-day)\n"
    for ticker, tech in insights.get('technicals', {}).items():
        insights_lines += (
            f"  {ticker}: RSI {tech.get('rsi14', '?')}, "
            f"{tech.get('pct_from_sma200', '?'):+.1f}% vs 200-SMA\n"
        )

    return template.format(
        date=report_date,
        summary='\n'.join(f"  - {b}" for b in summary),
        macro=macro_lines,
        insights=insights_lines,
    )


# ── LLM providers ─────────────────────────────────────────────────────────────
def _call_anthropic(prompt: str, model: str, max_tokens: int, api_key: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return msg.content[0].text.strip()


def _call_openai(prompt: str, model: str, max_tokens: int, api_key: str) -> str:
    import openai
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return resp.choices[0].message.content.strip()


# ── Rules-based fallback ──────────────────────────────────────────────────────
def _rules_narrative(summary: list, insights: dict, macro: list) -> list:
    breadth = insights.get('breadth', {})
    pct_up  = breadth.get('pct_up', 50)
    n_up    = breadth.get('n_up', '?')
    n_dn    = breadth.get('n_dn', '?')
    risk    = insights.get('risk_label', 'Neutral')
    score   = insights.get('risk_score', 0)

    p1 = (
        f"Markets closed the prior session with mixed signals across asset classes. "
        f"{' '.join(summary[:2])} "
        f"Breadth data shows {n_up} of the tracked universe advancing versus {n_dn} declining "
        f"({'positive' if pct_up >= 50 else 'negative'} participation at {pct_up:.0f}%)."
    )

    tech_lines = []
    for ticker, tech in insights.get('technicals', {}).items():
        rsi = tech.get('rsi14')
        s200 = tech.get('pct_from_sma200')
        if rsi and s200 is not None:
            tech_lines.append(
                f"{ticker} RSI stands at {rsi:.0f} with price "
                f"{'above' if s200 > 0 else 'below'} its 200-day SMA by {abs(s200):.1f}%"
            )
    tech_text = ('; '.join(tech_lines) + '.') if tech_lines else ''
    p2 = (
        f"The composite risk regime reads {risk} (score {score:+.2f}), reflecting the aggregate "
        f"of equity momentum, volatility, dollar strength, and safe-haven demand. {tech_text} "
        f"Cross-asset correlations and macro indicators provide additional context for positioning."
    )

    ff = next((m for m in macro if m['series_id'] == 'FEDFUNDS'), None)
    t10 = next((m for m in macro if m['series_id'] == 'T10Y2Y'), None)
    p3 = (
        f"Looking ahead, traders should monitor the signals outlined below for confirmation or "
        f"reversal of current trends. "
        + (f"Fed Funds at {ff['value']:.2f}% anchors the rate backdrop. " if ff else '')
        + (f"The 10Y-2Y yield spread at {t10['value']:.2f}% remains a key macro indicator. " if t10 else '')
        + "Maintain discipline around defined risk levels and await catalyst confirmation before adding exposure."
    )

    return [p1, p2, p3]


# ── Public entry point ────────────────────────────────────────────────────────
def generate_narrative(
    report_date: str,
    summary: list,
    macro: list,
    insights: dict,
    cfg: dict,
    env: dict,
) -> list:
    """
    Returns a list of 3 paragraph strings.
    cfg: the 'narrative' section from settings.yaml
    env: dict with LLM API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY)
    """
    provider = cfg.get('provider', 'rules').lower()

    if provider == 'anthropic':
        key = env.get('ANTHROPIC_API_KEY', '')
        if key:
            try:
                prompt = _build_prompt(report_date, summary, macro, insights)
                text   = _call_anthropic(prompt, cfg.get('model', 'claude-opus-4-7'),
                                         cfg.get('max_tokens', 800), key)
                paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
                if paragraphs:
                    logger.info("Narrative generated via Anthropic")
                    return paragraphs[:3]
            except Exception as e:
                logger.warning(f"Anthropic narrative failed: {e} — falling back to rules")

    if provider == 'openai':
        key = env.get('OPENAI_API_KEY', '')
        if key:
            try:
                prompt = _build_prompt(report_date, summary, macro, insights)
                text   = _call_openai(prompt, cfg.get('openai_model', 'gpt-4o'),
                                      cfg.get('max_tokens', 800), key)
                paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
                if paragraphs:
                    logger.info("Narrative generated via OpenAI")
                    return paragraphs[:3]
            except Exception as e:
                logger.warning(f"OpenAI narrative failed: {e} — falling back to rules")

    logger.info("Narrative generated via rules-based fallback")
    return _rules_narrative(summary, insights, macro)


# ── Default prompt (used if narrative_prompt.txt is missing) ─────────────────
_DEFAULT_PROMPT = """You are an expert financial market analyst writing a daily morning brief.
Based ONLY on the data provided — do not fabricate or extrapolate beyond it — write a concise
3-paragraph market narrative for {date}.

Paragraph 1 (Market Overview): Index performance and breadth.
Paragraph 2 (Key Drivers): Most important movers, macro backdrop, risk regime, cross-asset signals.
Paragraph 3 (Outlook): What to monitor in the next session. Reference specific levels where relevant.

Tone: professional, neutral, precise. Use the exact numbers from the data. Max 150 words per paragraph.
Separate paragraphs with a blank line.

--- DATA ---
Date: {date}

Summary:
{summary}

Macro Context:
{macro}

Analytical Insights:
{insights}
"""
