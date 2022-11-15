"""Shared UI atoms for the dashboard: CSS, headers, badges, safe tables."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

_CSS = """
<style>
    .dtk-hero {
        border-radius: 14px; padding: 22px 26px; margin-bottom: 18px;
        background: linear-gradient(135deg, #e8f0fe 0%, #f6f8fa 60%);
        border: 1px solid rgba(37, 99, 235, 0.15);
    }
    .dtk-hero h1 { margin: 0 0 4px 0; font-size: 1.65rem; letter-spacing: -0.02em; }
    .dtk-hero p { margin: 0; opacity: 0.75; }
    .dtk-chip {
        display: inline-block; padding: 2px 12px; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600; margin-right: 6px;
        background: rgba(37, 99, 235, 0.10); color: #2563eb;
        border: 1px solid rgba(37, 99, 235, 0.25);
    }
    .dtk-chip.ok { background: rgba(5,150,105,.10); color:#059669; border-color: rgba(5,150,105,.3);}
    .dtk-chip.warn { background: rgba(217,119,6,.12); color:#d97706; border-color: rgba(217,119,6,.3);}
    .dtk-chip.bad { background: rgba(220,38,38,.10); color:#dc2626; border-color: rgba(220,38,38,.3);}
    .dtk-note {
        border-left: 3px solid #2563eb; background: rgba(37,99,235,.05);
        padding: 10px 14px; border-radius: 0 8px 8px 0; font-size: 0.92rem;
        margin: 10px 0;
    }
    div[data-testid="stMetric"] {
        background: rgba(127,127,127,0.06); border: 1px solid rgba(127,127,127,0.15);
        border-radius: 12px; padding: 14px 16px;
    }
    div[data-testid="stMetricLabel"] { font-weight: 600; }
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; padding: 8px 16px; }
    @media (prefers-color-scheme: dark) {
        .dtk-hero { background: linear-gradient(135deg, #1b2a4a 0%, #171e2c 60%);
                    border-color: rgba(147, 197, 253, 0.2); }
        .dtk-note { background: rgba(147,197,253,.08); }
    }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def hero(title: str, subtitle: str, chips: list[tuple[str, str]] | None = None) -> None:
    chip_html = ""
    for label, tone in chips or []:
        chip_html += f'<span class="dtk-chip {tone}">{esc(label)}</span>'
    chips_block = ""
    if chip_html:
        chips_block = '<div style="margin-top:10px">' + chip_html + "</div>"
    st.markdown(
        '<div class="dtk-hero">'
        f"<h1>{esc(title)}</h1><p>{esc(subtitle)}</p>{chips_block}</div>",
        unsafe_allow_html=True,
    )


def quality_tone(score: float) -> str:
    if score >= 80:
        return "ok"
    if score >= 50:
        return "warn"
    return "bad"


def empty_state(message: str, cta: str | None = None) -> None:
    st.markdown(f'<div class="dtk-note">{esc(message)}</div>', unsafe_allow_html=True)
    if cta:
        st.caption(cta)


def format_int(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def truncate_table(df, max_rows: int = 300):
    if len(df) > max_rows:
        return df.head(max_rows), max_rows
    return df, None
