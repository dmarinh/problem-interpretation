"""
PTM Benchmark Design System
===========================
Single source of truth for visual styling across the benchmark dashboard.

Usage in every page:
    from benchmarks.visualizations.ui.style import inject_css, apply_ptm_template
    inject_css()   # call once, near the top of each page script

For the sidebar logo (call from app.py only, so it appears on every page):
    from benchmarks.visualizations.ui.style import sidebar_logo
    sidebar_logo()

For Plotly charts:
    st.plotly_chart(apply_ptm_template(my_chart_func(data)), use_container_width=True)
"""

from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_UI_DIR = Path(__file__).parent
LOGO_PATH = _UI_DIR / "logo.png"

# ---------------------------------------------------------------------------
# Material icon codes for st.Page() / st.navigation() icon= parameter.
# These render as crisp SVG icons (not emoji) in Streamlit's native nav.
# ---------------------------------------------------------------------------

MATERIAL_ICONS = {
    "overview": ":material/dashboard:",
    "model_comparison": ":material/bar_chart:",
    "ph_stochasticity": ":material/science:",
    "run_experiments": ":material/play_circle:",
    "link_results": ":material/arrow_forward:",
    "biotech": ":material/biotech:",
}

# ---------------------------------------------------------------------------
# Lucide SVG icon strings (inlined — no CDN, no package).
# Use icon() to embed them in st.markdown(..., unsafe_allow_html=True).
# ---------------------------------------------------------------------------

_SVG: dict[str, str] = {
    "alert-triangle": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24"'
        ' fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round">'
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>'
        "</svg>"
    ),
    "check-circle": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24"'
        ' fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round">'
        '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>'
        '<path d="m9 11 3 3L22 4"/>'
        "</svg>"
    ),
    "flask": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24"'
        ' fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round">'
        '<path d="M9 3h6l1 9H8L9 3z"/>'
        '<path d="M3 21h18"/>'
        '<path d="M7 21c0-4 2-7 5-7s5 3 5 7"/>'
        "</svg>"
    ),
    "play": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24"'
        ' fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round">'
        '<polygon points="6 3 20 12 6 21 6 3"/>'
        "</svg>"
    ),
    "bar-chart": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24"'
        ' fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round">'
        '<line x1="12" x2="12" y1="20" y2="10"/>'
        '<line x1="18" x2="18" y1="20" y2="4"/>'
        '<line x1="6" x2="6" y1="20" y2="16"/>'
        "</svg>"
    ),
    "dashboard": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24"'
        ' fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round">'
        '<rect width="7" height="9" x="3" y="3" rx="1"/>'
        '<rect width="7" height="5" x="14" y="3" rx="1"/>'
        '<rect width="7" height="9" x="14" y="12" rx="1"/>'
        '<rect width="7" height="5" x="3" y="16" rx="1"/>'
        "</svg>"
    ),
    "info": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24"'
        ' fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M12 16v-4"/><path d="M12 8h.01"/>'
        "</svg>"
    ),
    "arrow-right": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24"'
        ' fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round">'
        '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>'
        "</svg>"
    ),
}


def icon(name: str, size: int = 16, color: str = "currentColor") -> str:
    """Return an inline SVG string for use inside st.markdown(..., unsafe_allow_html=True)."""
    template = _SVG.get(name, "")
    return template.format(s=size, c=color) if template else ""


# ---------------------------------------------------------------------------
# CSS — injected once per page via inject_css()
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* =================================================================
   PTM Benchmark Design System
   Typeface : IBM Plex Sans 300/400/600 + IBM Plex Mono 400/500
   Palette  : warm neutrals · slate-blue · terracotta · forest green
================================================================= */

@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

/* --- Base -------------------------------------------------------- */
html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif !important;
}

/* --- Page title (st.title) --------------------------------------- */
h1 {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 26px !important;
    letter-spacing: -0.02em !important;
    color: #1C1A17 !important;
    line-height: 1.15 !important;
    margin-bottom: 4px !important;
}

/* --- Section headers (st.header) --------------------------------- */
/* Treated as instrument-panel section labels: small caps, ruled. */
h2 {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    letter-spacing: 0.07em !important;
    text-transform: uppercase !important;
    color: #1C1A17 !important;
    border-bottom: 1px solid #E4E2DC !important;
    padding-bottom: 10px !important;
    margin-top: 40px !important;
    margin-bottom: 20px !important;
}

/* --- Subheaders (st.subheader) ----------------------------------- */
h3 {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    color: #1C1A17 !important;
    margin-bottom: 4px !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    border-bottom: none !important;
}

/* --- Body text --------------------------------------------------- */
p {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 14px !important;
    color: #1C1A17 !important;
    line-height: 1.6 !important;
}

/* --- Captions (st.caption) --------------------------------------- */
.stCaption, .stCaption p {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 300 !important;
    font-size: 12px !important;
    color: #6A6760 !important;
    line-height: 1.55 !important;
}

/* --- Metrics (st.metric) ---------------------------------------- */
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] > div {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 0.10em !important;
    text-transform: uppercase !important;
    color: #6A6760 !important;
}

[data-testid="stMetricValue"],
[data-testid="stMetricValue"] > div {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 22px !important;
    font-weight: 400 !important;
    color: #1C1A17 !important;
    letter-spacing: -0.01em !important;
}

[data-testid="stMetricDelta"] svg { display: none; }

[data-testid="stMetricDelta"],
[data-testid="stMetricDelta"] > div {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 11px !important;
}

/* --- Dividers (st.divider) --------------------------------------- */
hr {
    border: none !important;
    border-top: 1px solid #E4E2DC !important;
    margin: 28px 0 !important;
}

/* --- Sidebar ----------------------------------------------------- */
[data-testid="stSidebar"] {
    background-color: #F1F0EC !important;
    border-right: 1px solid #E4E2DC !important;
}

/* Suppress any hidden nav placeholder that may still occupy height */
[data-testid="stSidebarNav"] {
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
}

/* Undo page-level h1/h2 rules inside the sidebar (nav subheaders, run labels) */
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    text-transform: none !important;
    letter-spacing: 0.01em !important;
    font-size: 12px !important;
    color: #1C1A17 !important;
    border-bottom: none !important;
    padding-bottom: 0 !important;
    margin-top: 8px !important;
    margin-bottom: 4px !important;
}

[data-testid="stSidebar"] p,
[data-testid="stSidebar"] .stCaption p {
    font-size: 12px !important;
    color: #6A6760 !important;
    line-height: 1.5 !important;
}

[data-testid="stSidebar"] hr {
    margin: 10px 0 !important;
    border-top-color: #E4E2DC !important;
}

/* --- Alerts ------------------------------------------------------ */
/* Reduce heavy box; add left accent border. Type colors come from theme. */
[data-testid="stAlertContainer"] {
    border-radius: 2px !important;
    padding: 10px 16px !important;
}

/* --- DataFrames -------------------------------------------------- */
[data-testid="stDataFrame"] > div {
    border: 1px solid #E4E2DC !important;
    border-radius: 2px !important;
}

/* --- Expanders --------------------------------------------------- */
[data-testid="stExpander"] {
    border: none !important;
    border-top: 1px solid #E4E2DC !important;
    border-radius: 0 !important;
}

[data-testid="stExpander"] summary {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 13px !important;
    color: #6A6760 !important;
}

/* --- Primary button ---------------------------------------------- */
button[data-testid="baseButton-primary"],
.stButton > button[kind="primary"] {
    background-color: #2A5A86 !important;
    color: #F8F7F4 !important;
    border: none !important;
    border-radius: 2px !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    letter-spacing: 0.04em !important;
    padding: 8px 24px !important;
    transition: background-color 0.15s ease !important;
}

button[data-testid="baseButton-primary"]:hover,
.stButton > button[kind="primary"]:hover {
    background-color: #1F4568 !important;
}

/* --- Form control labels ----------------------------------------- */
[data-testid="stSelectbox"] label p,
[data-testid="stMultiSelect"] label p,
[data-testid="stSlider"] label p,
[data-testid="stNumberInput"] label p,
[data-testid="stCheckbox"] label p {
    font-size: 11px !important;
    font-weight: 600 !important;
    letter-spacing: 0.07em !important;
    text-transform: uppercase !important;
    color: #6A6760 !important;
}

/* --- Status widget (st.status) ----------------------------------- */
[data-testid="stStatusWidget"] {
    border-radius: 2px !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 13px !important;
}

/* --- Page links -------------------------------------------------- */
[data-testid="stPageLink"] a {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    color: #2A5A86 !important;
    text-decoration: none !important;
}

[data-testid="stPageLink"] a:hover {
    text-decoration: underline !important;
}

/* --- Selectbox / multiselect dropdowns --------------------------- */
[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div > div {
    border-color: #E4E2DC !important;
    border-radius: 2px !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 13px !important;
}

/* --- Tabs -------------------------------------------------------- */
[data-testid="stTabs"] [data-baseweb="tab"] {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
}

/* --- Code blocks ------------------------------------------------- */
code, pre {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12px !important;
}

/* --- Hide deploy button and main menu (⋮) ------------------------ */
[data-testid="stAppDeployButton"],
[data-testid="stMainMenuButton"] {
    display: none !important;
}

/* --- Collapse empty header bar ----------------------------------- */
/* height:0 + overflow:visible removes the bar from layout while    */
/* keeping the sidebar expand button accessible when collapsed.     */
[data-testid="stHeader"] {
    height: 0 !important;
    min-height: 0 !important;
    overflow: visible !important;
    background: transparent !important;
}

.block-container {
    padding-top: 1rem !important;
}

/* --- Sidebar nav page links -------------------------------------- */
[data-testid="stSidebarNav"] a {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 13px !important;
    color: #1C1A17 !important;
}

[data-testid="stSidebarNav"] a[aria-current="page"] {
    font-weight: 600 !important;
    color: #2A5A86 !important;
}

</style>
"""


def inject_css() -> None:
    """Inject the PTM design system CSS. Call once near the top of each page script."""
    st.markdown(_CSS, unsafe_allow_html=True)


def sidebar_logo() -> None:
    """Render the FoodigIT logo full-width at the top of the sidebar.

    Uses a base64-embedded img inside st.sidebar.markdown so we can apply a
    negative margin-top directly on the element, bypassing Streamlit's built-in
    sidebar top padding without relying on CSS specificity fights.
    """
    if not LOGO_PATH.exists():
        return
    import base64
    with open(str(LOGO_PATH), "rb") as _f:
        _b64 = base64.b64encode(_f.read()).decode()
    st.sidebar.markdown(
        f'<div style="margin-top:-2rem">'
        f'<img src="data:image/png;base64,{_b64}" style="width:100%;display:block" />'
        f'</div>',
        unsafe_allow_html=True,
    )


def logo_as_pil():
    """Return the FoodigIT logo as a PIL Image for use as page_icon.

    Falls back to a plain emoji if PIL is unavailable or the file is missing.
    """
    try:
        from PIL import Image
        if LOGO_PATH.exists():
            return Image.open(str(LOGO_PATH))
    except ImportError:
        pass
    return ":material/biotech:"


# ---------------------------------------------------------------------------
# Plotly template
# ---------------------------------------------------------------------------

#: Design tokens used in the Plotly template — kept in sync with _CSS above.
_FONT_SANS = "IBM Plex Sans, sans-serif"
_FONT_MONO = "IBM Plex Mono, monospace"
_BG = "#F8F7F4"
_GRID = "#E4E2DC"
_AXIS_LINE = "#C8C5BC"
_INK = "#1C1A17"
_INK_SECONDARY = "#6A6760"

#: Default colorway — tier-ordered, semantic only.
PTM_COLORWAY = [
    "#2A5A86",  # slate-blue  (tier 0 / frontier)
    "#4A7F9E",  # lighter blue (tier 1 / established)
    "#2A6347",  # forest green (tier 2 / cost-optimised)
    "#A67B12",  # dark amber   (tier 3 / reasoning)
    "#6A6760",  # neutral gray (tier 4 / open-source)
    "#B84A2E",  # terracotta   (safety / error)
    "#7B68AE",  # soft purple  (accent 7th series)
]


def apply_ptm_template(fig):
    """Apply the PTM design system to a Plotly figure and return it.

    Does not alter chart data, trace types, or colorscales that carry
    semantic meaning (heatmaps, safety matrix).  Only affects background,
    font family, axis chrome, hover label, legend, and margins.
    """
    fig.update_layout(
        paper_bgcolor=_BG,
        plot_bgcolor=_BG,
        font=dict(family=_FONT_SANS, color=_INK, size=12),
        title=dict(
            font=dict(family=_FONT_SANS, size=13, color=_INK),
            x=0,
            xanchor="left",
            pad=dict(l=0, t=4, b=0),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            font=dict(family=_FONT_SANS, size=11, color=_INK_SECONDARY),
            title_font=dict(family=_FONT_SANS, size=11, color=_INK_SECONDARY),
        ),
        hoverlabel=dict(
            bgcolor=_INK,
            bordercolor=_INK,
            font=dict(family=_FONT_MONO, size=11, color=_BG),
        ),
        margin=dict(l=48, r=24, t=44, b=44),
        colorway=PTM_COLORWAY,
    )
    # update_xaxes / update_yaxes propagate to all subplot axes automatically.
    _axis = dict(
        gridcolor=_GRID,
        gridwidth=1,
        linecolor=_AXIS_LINE,
        zerolinecolor=_GRID,
        tickfont=dict(family=_FONT_MONO, size=11, color=_INK_SECONDARY),
        title_font=dict(family=_FONT_SANS, size=12, color=_INK_SECONDARY),
        showgrid=True,
    )
    fig.update_xaxes(**_axis)
    fig.update_yaxes(**_axis)
    return fig
