"""Clue Dashboard — Streamlit-powered AI efficiency dashboard for Claude Code."""

from __future__ import annotations

import html
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

# Ensure clue package is importable when run via streamlit
_src = str(Path(__file__).resolve().parent.parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

# ── Page config ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Clue — AI Efficiency Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ── CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Kill all Streamlit top chrome and padding */
    header[data-testid="stHeader"] { display: none !important; }
    .appview-container > .main > .block-container {
        padding-top: 0 !important; padding-bottom: 1rem; max-width: 1400px;
    }
    .appview-container > .main { padding-top: 0 !important; }
    .stApp > div:first-child { padding-top: 0 !important; }
    .block-container { padding-top: 0 !important; }
    [data-testid="stAppViewBlockContainer"] { padding-top: 0 !important; }
    h1, h2, h3 { letter-spacing: -0.02em; }

    /* Dashboard header bar */
    .dash-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.75rem 0 0.5rem 0;
        border-bottom: 1px solid rgba(128,128,128,0.12);
        margin-bottom: 0.75rem;
    }
    .dash-header .title {
        font-size: 1.35rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .dash-header .title .v { color: #6366f1; }
    .dash-header .title .dot { color: #fb923c; }
    .dash-header .right {
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }
    .dash-header .meta {
        font-size: 0.75rem;
        opacity: 0.5;
        text-align: right;
        line-height: 1.4;
    }
    /* Inline refresh button styled inside the HTML header */
    .dash-header .refresh-btn {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.35rem 0.85rem;
        border-radius: 8px;
        border: 1px solid rgba(99,102,241,0.3);
        background: rgba(99,102,241,0.08);
        color: #6366f1;
        font-size: 0.78rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s ease;
        text-decoration: none;
    }
    .dash-header .refresh-btn:hover {
        background: rgba(99,102,241,0.18);
        border-color: rgba(99,102,241,0.5);
    }

    [data-testid="stMetricLabel"] { font-size: 0.8rem; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; }
    [data-testid="stMetric"] {
        border: 1px solid rgba(128, 128, 128, 0.15);
        border-radius: 12px;
        padding: 1rem 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0.25rem;
        border-bottom: 1px solid rgba(128,128,128,0.15);
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 1rem;
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(99,102,241,0.08);
        border-bottom: 2px solid #6366f1;
    }

    .grade-badge {
        display: inline-block;
        padding: 0.15rem 0.5rem;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.8rem;
    }
    .grade-A { background: rgba(52,211,153,0.15); color: #34d399; }
    .grade-B { background: rgba(96,165,250,0.15); color: #60a5fa; }
    .grade-C { background: rgba(251,191,36,0.15); color: #fbbf24; }
    .grade-D { background: rgba(251,113,133,0.15); color: #fb7185; }
    .grade-F { background: rgba(239,68,68,0.15); color: #ef4444; }

    .dim-bar-bg {
        border-radius: 4px;
        height: 6px;
        width: 100%;
        background: rgba(128,128,128,0.12);
    }
    .dim-bar-fill { height: 6px; border-radius: 4px; transition: width 0.6s ease; }

    .rec-card {
        border-left: 3px solid #6366f1;
        border-radius: 0 8px 8px 0;
        padding: 0.75rem 1rem;
        margin-bottom: 0.5rem;
        font-size: 0.875rem;
        background: rgba(99,102,241,0.05);
    }

    /* Compact sync button */
    button[kind="primary"] {
        padding-top: 0.25rem !important;
        padding-bottom: 0.25rem !important;
        min-height: 0 !important;
        line-height: 1.2 !important;
    }

    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Colour palette (matches enterprise design) ──────────────────
COLORS = {
    "accent": "#6366f1",
    "accent_light": "#818cf8",
    "green": "#34d399",
    "amber": "#fbbf24",
    "rose": "#fb7185",
    "blue": "#60a5fa",
    "cyan": "#22d3ee",
    "orange": "#fb923c",
    "purple": "#a78bfa",
    "pink": "#f472b6",
}

CHART_COLORS = [
    COLORS["accent"], COLORS["blue"], COLORS["green"], COLORS["amber"],
    COLORS["rose"], COLORS["cyan"], COLORS["orange"], COLORS["purple"],
    COLORS["pink"], COLORS["accent_light"],
]

PLOTLY_LAYOUT = dict(
    margin=dict(l=40, r=20, t=30, b=40),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
    ),
)

# Hide Plotly toolbar to avoid overlap with legend
PLOTLY_CONFIG = dict(displayModeBar=False)


# ── Data loading — live from ~/.claude ────────────────────────────
from clue.db import init_db  # noqa: E402
from clue.export import generate_dashboard_data  # noqa: E402
from clue.pipeline import run_extract  # noqa: E402

DB_PATH = os.environ.get("CLUE_DB_PATH", str(Path.home() / ".claude" / "usage.db"))
CLAUDE_DIR = os.environ.get("CLUE_CLAUDE_DIR", str(Path.home() / ".claude"))


@st.cache_data(ttl=120, show_spinner="Loading data...")
def load_data(_db_path: str) -> dict:
    """Query SQLite and return dashboard data dict."""
    conn = init_db(Path(_db_path))
    data = generate_dashboard_data(conn, git_correlation=True)
    conn.close()
    return data


def get_data() -> dict:
    return load_data(DB_PATH)


def filter_by_range(items: list[dict], days: int | None) -> list[dict]:
    """Filter daily-granularity data by date range."""
    if days is None:
        return items
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [item for item in items if item.get("d", "") >= cutoff]


def score_color(score: float) -> str:
    if score >= 80:
        return COLORS["green"]
    if score >= 60:
        return COLORS["amber"]
    return COLORS["rose"]


def grade_class(grade: str) -> str:
    if grade.startswith("A"):
        return "grade-A"
    if grade.startswith("B"):
        return "grade-B"
    if grade.startswith("C"):
        return "grade-C"
    if grade.startswith("D"):
        return "grade-D"
    return "grade-F"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


# ── Load data ────────────────────────────────────────────────────
DATA = get_data()
overview = DATA["overview"]
eff = DATA["efficiency_score"]

# Show toast after a refresh rerun completes
if st.session_state.get("_refreshed"):
    st.toast("Dashboard refreshed", icon="✅")
    st.session_state["_refreshed"] = False

# ── Header ───────────────────────────────────────────────────────
generated = DATA.get("generated_at", "")
ts_str = ""
if generated:
    ts_str = datetime.fromisoformat(generated).strftime("%b %d, %H:%M")

col_hdr, _, col_meta, col_btn = st.columns([3, 3, 2, 0.7], vertical_alignment="center")
with col_hdr:
    st.markdown(
        '<span style="font-size:1.35rem;font-weight:700;letter-spacing:-0.02em">'
        '<span style="color:#6366f1">Clue</span>'
        '<span style="color:#fb923c">.</span> AI Efficiency Dashboard</span>',
        unsafe_allow_html=True,
    )
with col_meta:
    meta_parts = []
    if ts_str:
        meta_parts.append(f"Updated {ts_str}")
    meta_parts.append("Auto-refreshes every 2 min")
    st.markdown(
        f'<div style="text-align:right;font-size:0.85rem;opacity:0.5">'
        f'{" · ".join(meta_parts)}</div>',
        unsafe_allow_html=True,
    )
with col_btn:
    if st.button("↻ Sync", type="primary", help="Re-extract from ~/.claude and reload"):
        with st.spinner("Syncing from ~/.claude..."):
            run_extract(Path(CLAUDE_DIR), Path(DB_PATH), incremental=True)
        load_data.clear()
        st.session_state["_refreshed"] = True
        st.rerun()

st.divider()

# ── Period selector ──────────────────────────────────────────────
range_options = {"7 days": 7, "30 days": 30, "90 days": 90, "All time": None}
selected_range = st.radio(
    "Period",
    options=list(range_options.keys()),
    index=3,
    horizontal=True,
    label_visibility="collapsed",
)
DAYS = range_options[selected_range]

st.divider()

# ── Score Hero ───────────────────────────────────────────────────
score_col, dims_col, recs_col = st.columns([1, 1.5, 1.5])

with score_col:
    score = eff["overall"]
    grade = eff["grade"]
    color = score_color(score)
    trend = eff.get("trend", "stable")
    delta = eff.get("trend_delta", 0)

    # Gauge chart
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number=dict(font=dict(size=48, color=color), suffix=""),
        gauge=dict(
            axis=dict(range=[0, 100], tickwidth=0, tickcolor="rgba(0,0,0,0)", dtick=25),
            bar=dict(color=color, thickness=0.75),
            bgcolor="rgba(128,128,128,0.1)",
            borderwidth=0,
            steps=[
                dict(range=[0, 40], color="rgba(251,113,133,0.06)"),
                dict(range=[40, 70], color="rgba(251,191,36,0.06)"),
                dict(range=[70, 100], color="rgba(52,211,153,0.06)"),
            ],
        ),
    ))
    fig_gauge.update_layout(
        height=200,
        margin=dict(l=20, r=20, t=20, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_gauge, width="stretch", key="gauge", config=PLOTLY_CONFIG)

    trend_icon = {"improving": "↑", "declining": "↓"}.get(trend, "→")
    trend_color = {"improving": COLORS["green"], "declining": COLORS["rose"]}.get(
        trend, COLORS["amber"]
    )
    st.markdown(
        f'<div style="text-align:center;margin-top:-0.5rem">'
        f'<span style="font-size:1.5rem;font-weight:800">{html.escape(grade)}</span>'
        f' <span style="color:{trend_color};font-size:0.85rem">'
        f'{trend_icon} {abs(delta):.1f}% {html.escape(trend)}</span></div>',
        unsafe_allow_html=True,
    )

with dims_col:
    st.markdown("**Score Dimensions**")
    for dim in eff["dimensions"]:
        pct = dim["score"]
        col = score_color(pct)
        bar_html = (
            '<div style="display:flex;justify-content:space-between;'
            f'font-size:0.82rem;margin-bottom:0.1rem">'
            f'<span>{html.escape(dim["name"])}</span>'
            f'<span style="color:{col};font-weight:600">'
            f'{pct:.0f} ({html.escape(dim["grade"])})</span></div>'
            f'<div class="dim-bar-bg"><div class="dim-bar-fill"'
            f' style="width:{pct}%;background:{col}"></div></div>'
        )
        st.markdown(bar_html, unsafe_allow_html=True)

with recs_col:
    st.markdown("**Top Recommendations**")
    for rec in eff.get("top_recommendations", [])[:4]:
        st.markdown(
            f'<div class="rec-card">{html.escape(rec)}</div>',
            unsafe_allow_html=True,
        )

st.divider()

# ── KPIs ─────────────────────────────────────────────────────────
# Filter daily data for KPI computation
usage_f = filter_by_range(DATA.get("daily_usage", []), DAYS)
tokens_f = filter_by_range(DATA.get("daily_tokens", []), DAYS)
cost_f = filter_by_range(DATA.get("daily_cost", []), DAYS)
prompts_f = filter_by_range(DATA.get("prompt_lengths", []), DAYS)

kpi_prompts = sum(r["p"] for r in usage_f)
kpi_sessions = len({r["d"] for r in usage_f if r["s"] > 0})
kpi_input = sum(r.get("i", 0) for r in tokens_f)
kpi_output = sum(r.get("o", 0) for r in tokens_f)
kpi_cache_w = sum(r.get("cw", 0) for r in tokens_f)
kpi_cache_r = sum(r.get("cr", 0) for r in tokens_f)
kpi_tokens = kpi_input + kpi_output + kpi_cache_w + kpi_cache_r
kpi_cost = sum(r.get("c", 0) for r in cost_f)
kpi_cache_total = kpi_cache_w + kpi_cache_r
kpi_cache_pct = round(kpi_cache_r / kpi_cache_total * 100, 1) if kpi_cache_total > 0 else 0
kpi_avg_prompt = round(sum(r["l"] for r in prompts_f) / len(prompts_f), 0) if prompts_f else 0
kpi_projects = len({r["pj"] for r in filter_by_range(DATA.get("daily_project", []), DAYS)})

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Prompts", f"{kpi_prompts:,}")
tok_help = f"In: {fmt_tokens(kpi_input)} / Out: {fmt_tokens(kpi_output)}"
k2.metric("Tokens", fmt_tokens(kpi_tokens), help=tok_help)
k3.metric("Est. Cost", f"${kpi_cost:,.2f}")
k4.metric("Cache Hit", f"{kpi_cache_pct}%")
k5.metric("Avg Prompt", f"{int(kpi_avg_prompt):,} chars")
k6.metric("Projects", str(kpi_projects))

# ── Project Scores ───────────────────────────────────────────────
project_scores = DATA.get("project_scores", [])
if project_scores:
    with st.expander("Project Scores", expanded=False):
        cols_hdr = st.columns([3, 1, 1, 1, 1, 1])
        headers = ["Project", "Score", "Grade", "Sessions", "Prompts", "Tokens"]
        for c, h in zip(cols_hdr, headers, strict=True):
            c.markdown(f"**{h}**")

        for ps in sorted(project_scores, key=lambda x: x["score"], reverse=True):
            cols_row = st.columns([3, 1, 1, 1, 1, 1])
            cols_row[0].write(ps["project"])
            cols_row[1].write(f'{ps["score"]:.0f}')
            gc = grade_class(ps["grade"])
            cols_row[2].markdown(
                f'<span class="grade-badge {gc}">{html.escape(ps["grade"])}</span>',
                unsafe_allow_html=True,
            )
            cols_row[3].write(str(ps.get("sessions", 0)))
            cols_row[4].write(str(ps.get("prompts", 0)))
            cols_row[5].write(fmt_tokens(ps.get("tokens", 0)))

st.divider()

# ── Tabbed Charts ────────────────────────────────────────────────
tab_activity, tab_projects, tab_tools, tab_cost, tab_patterns, tab_journey, tab_insights = st.tabs(
    ["Activity", "Projects", "Tools", "Cost", "Patterns", "Journey", "Insights"]
)

# ── Activity Tab ─────────────────────────────────────────────────
with tab_activity:
    # Daily activity
    if usage_f:
        st.markdown("**Daily Activity**")
        fig_act = go.Figure()
        fig_act.add_trace(go.Scatter(
            x=[r["d"] for r in usage_f], y=[r["p"] for r in usage_f],
            name="Prompts", line=dict(color=COLORS["accent"], width=2),
            fill="tozeroy", fillcolor="rgba(99,102,241,0.08)",
        ))
        fig_act.add_trace(go.Scatter(
            x=[r["d"] for r in usage_f], y=[r["s"] for r in usage_f],
            name="Sessions", line=dict(color=COLORS["cyan"], width=2),
        ))
        fig_act.update_layout(height=350, **PLOTLY_LAYOUT)
        st.plotly_chart(fig_act, width="stretch", key="activity", config=PLOTLY_CONFIG)

    # Token consumption
    if tokens_f:
        col_tok1, col_tok2 = st.columns(2)
        with col_tok1:
            st.markdown("**Daily Token Consumption**")
            fig_tok = go.Figure()
            for key, label, color in [
                ("i", "Input", COLORS["blue"]),
                ("o", "Output", COLORS["accent"]),
                ("cw", "Cache Write", COLORS["amber"]),
                ("cr", "Cache Read", COLORS["green"]),
            ]:
                fig_tok.add_trace(go.Bar(
                    x=[r["d"] for r in tokens_f],
                    y=[r.get(key, 0) for r in tokens_f],
                    name=label, marker_color=color,
                ))
            fig_tok.update_layout(
                barmode="stack", height=350, **PLOTLY_LAYOUT,
            )
            st.plotly_chart(fig_tok, width="stretch", key="tokens", config=PLOTLY_CONFIG)

        with col_tok2:
            # Prompt length distribution
            if prompts_f:
                st.markdown("**Prompt Length Distribution (chars)**")
                buckets = {
                    "0-15": 0, "16-50": 0, "51-200": 0,
                    "201-500": 0, "501-1K": 0, "1K+": 0,
                }
                for r in prompts_f:
                    length = r["l"]
                    if length <= 15:
                        buckets["0-15"] += 1
                    elif length <= 50:
                        buckets["16-50"] += 1
                    elif length <= 200:
                        buckets["51-200"] += 1
                    elif length <= 500:
                        buckets["201-500"] += 1
                    elif length <= 1000:
                        buckets["501-1K"] += 1
                    else:
                        buckets["1K+"] += 1

                fig_pl = go.Figure(go.Bar(
                    x=list(buckets.keys()),
                    y=list(buckets.values()),
                    marker_color=COLORS["accent"],
                    marker=dict(cornerradius=4),
                ))
                fig_pl.update_layout(height=350, **PLOTLY_LAYOUT)
                st.plotly_chart(fig_pl, width="stretch", key="prompt_lengths", config=PLOTLY_CONFIG)

# ── Projects Tab ─────────────────────────────────────────────────
with tab_projects:
    proj_f = filter_by_range(DATA.get("daily_project", []), DAYS)
    proj_tok_f = filter_by_range(DATA.get("daily_project_tokens", []), DAYS)

    if proj_f:
        col_p1, col_p2 = st.columns(2)

        # Prompts by project
        with col_p1:
            st.markdown("**Prompts by Project**")
            proj_counts = {}
            for r in proj_f:
                proj_counts[r["pj"]] = proj_counts.get(r["pj"], 0) + r["p"]
            top_proj = sorted(proj_counts.items(), key=lambda x: x[1], reverse=True)[:15]

            fig_pp = go.Figure(go.Bar(
                y=[p[0] for p in reversed(top_proj)],
                x=[p[1] for p in reversed(top_proj)],
                orientation="h",
                marker_color=COLORS["accent"],
                marker=dict(cornerradius=4),
            ))
            fig_pp.update_layout(height=400, **PLOTLY_LAYOUT)
            st.plotly_chart(fig_pp, width="stretch", key="proj_prompts", config=PLOTLY_CONFIG)

        # Tokens by project
        with col_p2:
            st.markdown("**Tokens by Project**")
            proj_tok_counts = {}
            for r in proj_tok_f:
                proj_tok_counts[r["pj"]] = proj_tok_counts.get(r["pj"], 0) + r.get("t", 0)
            top_tok = sorted(proj_tok_counts.items(), key=lambda x: x[1], reverse=True)[:15]

            fig_pt = go.Figure(go.Bar(
                y=[p[0] for p in reversed(top_tok)],
                x=[p[1] for p in reversed(top_tok)],
                orientation="h",
                marker_color=COLORS["blue"],
                marker=dict(cornerradius=4),
            ))
            fig_pt.update_layout(height=400, **PLOTLY_LAYOUT)
            st.plotly_chart(fig_pt, width="stretch", key="proj_tokens", config=PLOTLY_CONFIG)

        # Daily project activity (top 8)
        top_8 = [p[0] for p in sorted(proj_counts.items(), key=lambda x: x[1], reverse=True)[:8]]
        daily_proj_data = {}
        for r in proj_f:
            if r["pj"] in top_8:
                daily_proj_data.setdefault(r["pj"], {"dates": [], "counts": []})
                daily_proj_data[r["pj"]]["dates"].append(r["d"])
                daily_proj_data[r["pj"]]["counts"].append(r["p"])

        if daily_proj_data:
            st.markdown("**Daily Project Activity**")
            fig_dp = go.Figure()
            for i, (proj, vals) in enumerate(daily_proj_data.items()):
                fig_dp.add_trace(go.Bar(
                    x=vals["dates"], y=vals["counts"],
                    name=proj, marker_color=CHART_COLORS[i % len(CHART_COLORS)],
                ))
            fig_dp.update_layout(
                barmode="stack", height=350, **PLOTLY_LAYOUT,
            )
            st.plotly_chart(fig_dp, width="stretch", key="daily_proj", config=PLOTLY_CONFIG)

    # Per-project cost efficiency
    pce_data = filter_by_range(DATA.get("project_cost_efficiency", []), DAYS)
    if pce_data:
        st.markdown("**Cost per Session by Project**")
        pce_agg: dict[str, dict] = {}
        for r in pce_data:
            pj = r["pj"]
            pce_agg.setdefault(pj, {"cost": 0.0, "sessions": 0})
            pce_agg[pj]["cost"] += r["cost"]
            pce_agg[pj]["sessions"] += r["sessions"]

        pce_table = []
        for pj, v in sorted(pce_agg.items(), key=lambda x: x[1]["cost"], reverse=True):
            cps = v["cost"] / v["sessions"] if v["sessions"] > 0 else 0
            pce_table.append({
                "Project": pj,
                "Total Cost": f'${v["cost"]:.2f}',
                "Sessions": v["sessions"],
                "Cost/Session": f"${cps:.2f}",
            })
        st.dataframe(pce_table, width="stretch", hide_index=True)

# ── Tools Tab ────────────────────────────────────────────────────
with tab_tools:
    tools_f = filter_by_range(DATA.get("daily_tools", []), DAYS)

    if tools_f:
        col_t1, col_t2 = st.columns([1, 2])

        # Top tools
        with col_t1:
            st.markdown("**Top Tools**")
            tool_counts = {}
            for r in tools_f:
                tool_counts[r["tool"]] = tool_counts.get(r["tool"], 0) + r["n"]
            top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:15]

            fig_tt = go.Figure(go.Bar(
                y=[t[0] for t in reversed(top_tools)],
                x=[t[1] for t in reversed(top_tools)],
                orientation="h",
                marker_color=COLORS["accent"],
                marker=dict(cornerradius=4),
            ))
            fig_tt.update_layout(height=500, **PLOTLY_LAYOUT)
            st.plotly_chart(fig_tt, width="stretch", key="top_tools", config=PLOTLY_CONFIG)

        # Tool usage trend (top 5)
        with col_t2:
            st.markdown("**Tool Usage Trend**")
            top_5_tools = [t[0] for t in top_tools[:5]]
            tool_daily = {}
            for r in tools_f:
                if r["tool"] in top_5_tools:
                    tool_daily.setdefault(r["tool"], {"dates": [], "counts": []})
                    tool_daily[r["tool"]]["dates"].append(r["d"])
                    tool_daily[r["tool"]]["counts"].append(r["n"])

            if tool_daily:
                fig_trend = go.Figure()
                for i, (tool, vals) in enumerate(tool_daily.items()):
                    fig_trend.add_trace(go.Scatter(
                        x=vals["dates"], y=vals["counts"],
                        name=tool, line=dict(color=CHART_COLORS[i % len(CHART_COLORS)], width=2),
                    ))
                fig_trend.update_layout(height=500, **PLOTLY_LAYOUT)
                st.plotly_chart(fig_trend, width="stretch", key="tool_trend", config=PLOTLY_CONFIG)

    # Stop reason distribution
    stop_reasons = DATA.get("stop_reason_totals", [])
    if stop_reasons:
        col_sr1, col_sr2 = st.columns(2)
        with col_sr1:
            st.markdown("**Stop Reason Distribution**")
            fig_sr = go.Figure(go.Pie(
                labels=[r["reason"] for r in stop_reasons],
                values=[r["n"] for r in stop_reasons],
                hole=0.55,
                marker=dict(colors=CHART_COLORS[:len(stop_reasons)]),
                textinfo="label+percent",
                textfont_size=11,
            ))
            fig_sr.update_layout(
                height=300, showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=20, r=20, t=10, b=20),
            )
            st.plotly_chart(fig_sr, width="stretch", key="stop_reasons", config=PLOTLY_CONFIG)

        with col_sr2:
            daily_sr = filter_by_range(DATA.get("daily_stop_reasons", []), DAYS)
            if daily_sr:
                st.markdown("**Daily Stop Reasons**")
                sr_by_reason: dict[str, dict] = {}
                for r in daily_sr:
                    sr_by_reason.setdefault(r["reason"], {"dates": [], "counts": []})
                    sr_by_reason[r["reason"]]["dates"].append(r["d"])
                    sr_by_reason[r["reason"]]["counts"].append(r["n"])

                fig_dsr = go.Figure()
                for i, (reason, vals) in enumerate(sr_by_reason.items()):
                    fig_dsr.add_trace(go.Bar(
                        x=vals["dates"], y=vals["counts"],
                        name=reason, marker_color=CHART_COLORS[i % len(CHART_COLORS)],
                    ))
                fig_dsr.update_layout(barmode="stack", height=300, **PLOTLY_LAYOUT)
                st.plotly_chart(
                    fig_dsr, width="stretch", key="daily_stop_reasons", config=PLOTLY_CONFIG,
                )

    # Agentic usage
    daily_agent = filter_by_range(DATA.get("daily_agentic", []), DAYS)
    if daily_agent:
        st.markdown("**Agentic vs Main Turns**")
        col_ag1, col_ag2 = st.columns(2)
        with col_ag1:
            fig_ag = go.Figure()
            fig_ag.add_trace(go.Bar(
                x=[r["d"] for r in daily_agent],
                y=[r["mt"] for r in daily_agent],
                name="Main", marker_color=COLORS["accent"],
            ))
            fig_ag.add_trace(go.Bar(
                x=[r["d"] for r in daily_agent],
                y=[r["at"] for r in daily_agent],
                name="Agent", marker_color=COLORS["orange"],
            ))
            fig_ag.update_layout(barmode="stack", height=300, **PLOTLY_LAYOUT)
            st.plotly_chart(fig_ag, width="stretch", key="agentic_turns", config=PLOTLY_CONFIG)

        with col_ag2:
            agent_cost = DATA.get("agentic_cost_split", {})
            if agent_cost.get("agent", 0) > 0 or agent_cost.get("main", 0) > 0:
                st.markdown("**Cost Split: Agent vs Main**")
                fig_ac = go.Figure(go.Pie(
                    labels=["Main", "Agent"],
                    values=[agent_cost.get("main", 0), agent_cost.get("agent", 0)],
                    hole=0.55,
                    marker=dict(colors=[COLORS["accent"], COLORS["orange"]]),
                    textinfo="label+percent+value",
                    texttemplate="%{label}<br>$%{value:.2f}<br>%{percent}",
                    textfont_size=11,
                ))
                fig_ac.update_layout(
                    height=300, showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=20, r=20, t=10, b=20),
                )
                st.plotly_chart(fig_ac, width="stretch", key="agent_cost", config=PLOTLY_CONFIG)

# ── Cost Tab ─────────────────────────────────────────────────────
with tab_cost:
    cost_filtered = filter_by_range(DATA.get("daily_cost", []), DAYS)
    model_totals = DATA.get("model_totals", [])

    if model_totals or cost_filtered:
        col_c1, col_c2 = st.columns(2)

        # Cost by model (doughnut)
        with col_c1:
            if model_totals:
                st.markdown("**Cost by Model**")
                models = [m["model"] for m in model_totals]
                costs = [m["estimated_cost_usd"] for m in model_totals]
                fig_donut = go.Figure(go.Pie(
                    labels=models, values=costs,
                    hole=0.55,
                    marker=dict(colors=CHART_COLORS[:len(models)]),
                    textinfo="label+percent",
                    textfont_size=11,
                ))
                fig_donut.update_layout(
                    height=350, showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=20, r=20, t=10, b=20),
                )
                st.plotly_chart(fig_donut, width="stretch", key="cost_model", config=PLOTLY_CONFIG)

        # Daily cost stacked
        with col_c2:
            if cost_filtered:
                st.markdown("**Daily Cost by Model**")
                cost_by_model = {}
                for r in cost_filtered:
                    cost_by_model.setdefault(r["m"], {"dates": [], "costs": []})
                    cost_by_model[r["m"]]["dates"].append(r["d"])
                    cost_by_model[r["m"]]["costs"].append(r["c"])

                fig_dc = go.Figure()
                for i, (model, vals) in enumerate(cost_by_model.items()):
                    fig_dc.add_trace(go.Bar(
                        x=vals["dates"], y=vals["costs"],
                        name=model, marker_color=CHART_COLORS[i % len(CHART_COLORS)],
                    ))
                fig_dc.update_layout(
                    barmode="stack", height=350, **PLOTLY_LAYOUT,
                )
                st.plotly_chart(fig_dc, width="stretch", key="daily_cost", config=PLOTLY_CONFIG)

        # Model cost table
        if model_totals:
            st.markdown("**Model Cost Breakdown**")
            table_data = []
            for m in sorted(model_totals, key=lambda x: x["estimated_cost_usd"], reverse=True):
                table_data.append({
                    "Model": m["model"],
                    "Input Tokens": fmt_tokens(m["input_tokens"]),
                    "Output Tokens": fmt_tokens(m["output_tokens"]),
                    "Est. Cost": f'${m["estimated_cost_usd"]:.2f}',
                })
            st.dataframe(table_data, width="stretch", hide_index=True)

        # API calls by model (doughnut)
        models_f = filter_by_range(DATA.get("daily_models", []), DAYS)
        if models_f:
            st.markdown("**API Calls by Model**")
            model_calls = {}
            for r in models_f:
                model_calls[r["m"]] = model_calls.get(r["m"], 0) + r["n"]
            fig_api = go.Figure(go.Pie(
                labels=list(model_calls.keys()),
                values=list(model_calls.values()),
                hole=0.55,
                marker=dict(colors=CHART_COLORS[:len(model_calls)]),
                textinfo="label+percent",
                textfont_size=11,
            ))
            fig_api.update_layout(
                height=300, showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=20, r=20, t=10, b=20),
            )
            st.plotly_chart(fig_api, width="stretch", key="api_calls", config=PLOTLY_CONFIG)

# ── Patterns Tab ─────────────────────────────────────────────────
with tab_patterns:
    col_pat1, col_pat2 = st.columns(2)

    # Hourly distribution
    with col_pat1:
        hourly = DATA.get("hourly_distribution", [])
        if hourly:
            st.markdown("**Prompts by Hour**")
            fig_h = go.Figure(go.Bar(
                x=[r["hour"] for r in hourly],
                y=[r["prompts"] for r in hourly],
                marker_color=COLORS["accent"],
                marker=dict(cornerradius=4),
            ))
            fig_h.update_layout(
                height=300, xaxis_title="Hour (24h)", **PLOTLY_LAYOUT,
            )
            st.plotly_chart(fig_h, width="stretch", key="hourly", config=PLOTLY_CONFIG)

    # Day of week
    with col_pat2:
        dow = DATA.get("day_of_week_distribution", [])
        if dow:
            st.markdown("**Prompts by Day of Week**")
            fig_dow = go.Figure(go.Bar(
                x=[r["day"] for r in dow],
                y=[r["prompts"] for r in dow],
                marker_color=COLORS["blue"],
                marker=dict(cornerradius=4),
            ))
            fig_dow.update_layout(height=300, **PLOTLY_LAYOUT)
            st.plotly_chart(fig_dow, width="stretch", key="dow", config=PLOTLY_CONFIG)

    # Branch usage table
    branches = DATA.get("branch_usage", [])
    if branches:
        st.markdown("**Activity by Git Branch**")
        branch_data = []
        for b in branches:
            branch_data.append({
                "Branch": b["branch"],
                "Turns": b["turns"],
                "Output Tokens": fmt_tokens(b.get("output_tokens", 0)),
            })
        st.dataframe(branch_data, width="stretch", hide_index=True)

# ── Journey Tab ──────────────────────────────────────────────────
with tab_journey:
    # Row 1: Streak + Weekly trend
    streak = DATA.get("usage_streak", 0)
    weekly = DATA.get("weekly_summaries", [])

    col_j1, col_j2, col_j3 = st.columns(3)
    with col_j1:
        st.metric("Active Streak", f"{streak} day{'s' if streak != 1 else ''}")
    with col_j2:
        if weekly:
            latest_week = weekly[-1]
            st.metric(
                f"This Week ({html.escape(latest_week['w'])})",
                f"{latest_week['p']} prompts",
                f"{latest_week['days']} active days",
            )
    with col_j3:
        if len(weekly) >= 2:
            curr, prev = weekly[-1], weekly[-2]
            delta = curr["p"] - prev["p"]
            st.metric(
                "Week-over-Week",
                f"{curr['p']} prompts",
                f"{delta:+d} vs prior week",
            )

    # Row 2: Activity Heatmap + Session Depth
    col_h1, col_h2 = st.columns(2)

    with col_h1:
        heatmap = DATA.get("heatmap_data", [])
        if heatmap:
            st.markdown("**Activity Heatmap** (prompts by hour and day)")
            dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            # Build 7x24 matrix
            matrix = [[0] * 24 for _ in range(7)]
            for cell in heatmap:
                if 0 <= cell["d"] <= 6 and 0 <= cell["h"] <= 23:
                    matrix[cell["d"]][cell["h"]] = cell["v"]

            fig_hm = go.Figure(go.Heatmap(
                z=matrix,
                x=list(range(24)),
                y=dow_labels,
                colorscale=[
                    [0, "rgba(99,102,241,0.03)"],
                    [0.25, "rgba(99,102,241,0.15)"],
                    [0.5, "rgba(99,102,241,0.35)"],
                    [0.75, "rgba(99,102,241,0.6)"],
                    [1, "rgba(99,102,241,0.9)"],
                ],
                showscale=False,
                hovertemplate="Hour %{x}, %{y}: %{z} prompts<extra></extra>",
                xgap=2, ygap=2,
            ))
            fig_hm.update_layout(
                height=250,
                xaxis=dict(
                    dtick=1, title="Hour (24h)",
                    showgrid=False, zeroline=False,
                ),
                yaxis=dict(showgrid=False, zeroline=False, autorange="reversed"),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=40, r=10, t=10, b=40),
            )
            st.plotly_chart(
                fig_hm, width="stretch", key="heatmap", config=PLOTLY_CONFIG,
            )

    with col_h2:
        depth_dist = DATA.get("session_depth_dist", [])
        if depth_dist:
            st.markdown("**Session Depth Distribution** (prompts per session)")
            # Bucket into ranges for readability
            buckets = {"1-2": 0, "3-5": 0, "6-10": 0, "11-20": 0, "21-40": 0, "41+": 0}
            for r in depth_dist:
                d, c = r["depth"], r["count"]
                if d <= 2:
                    buckets["1-2"] += c
                elif d <= 5:
                    buckets["3-5"] += c
                elif d <= 10:
                    buckets["6-10"] += c
                elif d <= 20:
                    buckets["11-20"] += c
                elif d <= 40:
                    buckets["21-40"] += c
                else:
                    buckets["41+"] += c

            fig_sd = go.Figure(go.Bar(
                x=list(buckets.keys()),
                y=list(buckets.values()),
                marker_color=[
                    COLORS["rose"], COLORS["amber"], COLORS["green"],
                    COLORS["accent"], COLORS["blue"], COLORS["rose"],
                ],
                marker=dict(cornerradius=4),
            ))
            fig_sd.update_layout(
                height=250,
                xaxis_title="Prompts per Session",
                yaxis_title="Sessions",
                **PLOTLY_LAYOUT,
            )
            st.plotly_chart(
                fig_sd, width="stretch", key="session_depth", config=PLOTLY_CONFIG,
            )

    # Row 3: Iteration Efficiency Trend
    iteration_data = DATA.get("daily_iteration", [])
    iteration_f = filter_by_range(iteration_data, DAYS) if iteration_data else []
    if iteration_f:
        st.markdown("**Iteration Efficiency Trend** (daily correction rate)")
        fig_iter = go.Figure()
        fig_iter.add_trace(go.Scatter(
            x=[r["d"] for r in iteration_f],
            y=[r["correction_pct"] for r in iteration_f],
            name="Correction %",
            line=dict(color=COLORS["rose"], width=2),
            fill="tozeroy",
            fillcolor="rgba(251,113,133,0.08)",
        ))
        fig_iter.add_trace(go.Bar(
            x=[r["d"] for r in iteration_f],
            y=[r["total"] for r in iteration_f],
            name="Total Prompts",
            marker_color="rgba(99,102,241,0.15)",
            yaxis="y2",
        ))
        fig_iter.update_layout(
            height=300,
            yaxis=dict(title="Correction %", side="left", range=[0, 50]),
            yaxis2=dict(
                title="Prompts", side="right", overlaying="y",
                showgrid=False,
            ),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="left", x=0,
            ),
            margin=dict(l=40, r=40, t=30, b=40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(
            fig_iter, width="stretch", key="iteration_trend", config=PLOTLY_CONFIG,
        )

    # Row 4: Weekly Summary Table
    if weekly:
        st.markdown("**Weekly Summary**")
        week_table = []
        for w in reversed(weekly[-12:]):  # Last 12 weeks
            week_table.append({
                "Week": w["w"],
                "Prompts": w["p"],
                "Sessions": w["s"],
                "Avg Length": f"{w['avg_len']:.0f} chars",
                "Active Days": f"{w['days']}/7",
            })
        st.dataframe(week_table, width="stretch", hide_index=True)

    # Row 5: Recent Sessions Timeline
    sessions_data = DATA.get("session_summaries", [])
    if sessions_data:
        st.markdown("**Recent Sessions**")
        session_table = []
        for s in sessions_data[:20]:
            tools = s.get("tools", {})
            top_tools = sorted(tools.items(), key=lambda x: x[1], reverse=True)[:3]
            tools_str = ", ".join(f"{t[0]} ({t[1]})" for t in top_tools) if top_tools else "—"
            session_table.append({
                "Project": html.escape(s["project"]),
                "Started": s.get("started", "—") or "—",
                "Prompts": s["prompts"],
                "Turns": s["turns"],
                "Tokens": fmt_tokens(s["tokens"]),
                "Top Tools": tools_str,
            })
        st.dataframe(session_table, width="stretch", hide_index=True)

# ── Insights Tab ────────────────────────────────────────────────
with tab_insights:
    # Correction cost KPI
    corr_cost = DATA.get("correction_cost", {})
    if corr_cost:
        col_i1, col_i2, col_i3 = st.columns(3)
        with col_i1:
            st.metric(
                "Correction Cost",
                f'${corr_cost.get("cost", 0):.2f}',
                help="Estimated tokens spent on turns following correction prompts",
            )
        with col_i2:
            st.metric(
                "% of Total Cost",
                f'{corr_cost.get("pct", 0):.1f}%',
                help="Fraction of total estimated cost attributed to corrections",
            )
        with col_i3:
            st.metric(
                "Sessions with Corrections",
                str(corr_cost.get("sessions", 0)),
            )

    # Prompt pattern stats
    pattern_stats = DATA.get("prompt_pattern_stats", [])
    if pattern_stats:
        st.markdown("**Prompt Pattern Analysis** (factual distributions)")
        st.caption("How different prompt types correlate with session token usage.")
        pattern_table = []
        for ps in pattern_stats:
            pattern_label = {
                "has_file_ref": "Contains file references",
                "has_slash_cmd": "Slash commands (/test, /review)",
                "short_prompt": "Short prompts (<50 chars)",
                "long_prompt": "Detailed prompts (>200 chars)",
                "all": "All prompts (baseline)",
            }.get(ps["pattern"], ps["pattern"])
            pattern_table.append({
                "Pattern": pattern_label,
                "Count": ps["count"],
                "Avg Session Tokens": fmt_tokens(int(ps["avg_session_tokens"])),
            })
        st.dataframe(pattern_table, width="stretch", hide_index=True)

    # Session outcomes (git-correlated)
    outcome_counts = DATA.get("outcome_counts")
    if outcome_counts:
        git_repos = DATA.get("git_repos_available", 0)
        git_total = DATA.get("git_repos_total", 0)
        st.markdown(
            f"**Session Outcomes** (git data from {git_repos} of {git_total} projects)"
        )
        col_o1, col_o2 = st.columns(2)
        with col_o1:
            labels = list(outcome_counts.keys())
            values = list(outcome_counts.values())
            oc_colors = {
                "productive": COLORS["green"],
                "exploratory": COLORS["blue"],
                "abandoned": COLORS["rose"],
            }
            fig_oc = go.Figure(go.Pie(
                labels=labels, values=values,
                hole=0.55,
                marker=dict(colors=[oc_colors.get(lb, COLORS["accent"]) for lb in labels]),
                textinfo="label+percent+value",
                textfont_size=11,
            ))
            fig_oc.update_layout(
                height=300, showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=20, r=20, t=10, b=20),
            )
            st.plotly_chart(fig_oc, width="stretch", key="outcomes", config=PLOTLY_CONFIG)

        with col_o2:
            ttv = DATA.get("time_to_value", [])
            if ttv:
                st.markdown("**Time to First Commit** (minutes)")
                minutes = [t["minutes"] for t in ttv]
                # Bucket into ranges
                ttv_buckets = {
                    "<5m": 0, "5-15m": 0, "15-30m": 0,
                    "30-60m": 0, "1-2h": 0, "2h+": 0,
                }
                for m in minutes:
                    if m < 5:
                        ttv_buckets["<5m"] += 1
                    elif m < 15:
                        ttv_buckets["5-15m"] += 1
                    elif m < 30:
                        ttv_buckets["15-30m"] += 1
                    elif m < 60:
                        ttv_buckets["30-60m"] += 1
                    elif m < 120:
                        ttv_buckets["1-2h"] += 1
                    else:
                        ttv_buckets["2h+"] += 1

                fig_ttv = go.Figure(go.Bar(
                    x=list(ttv_buckets.keys()),
                    y=list(ttv_buckets.values()),
                    marker_color=COLORS["green"],
                    marker=dict(cornerradius=4),
                ))
                fig_ttv.update_layout(
                    height=300,
                    xaxis_title="Time to First Commit",
                    yaxis_title="Sessions",
                    **PLOTLY_LAYOUT,
                )
                st.plotly_chart(
                    fig_ttv, width="stretch", key="time_to_value", config=PLOTLY_CONFIG,
                )
            else:
                st.info("No commit data found for time-to-value analysis.")

    # Team percentile benchmarks
    users = DATA.get("users")
    if users and len(users) > 1:
        st.markdown("**Team Benchmarks**")
        team_scores = DATA.get("project_scores", [])
        if team_scores:
            all_scores = [ps["score"] for ps in team_scores]
            all_scores_sorted = sorted(all_scores)
            team_table = []
            for ps in sorted(team_scores, key=lambda x: x["score"], reverse=True):
                rank = sum(1 for s in all_scores_sorted if s <= ps["score"])
                pctile = round(rank / len(all_scores_sorted) * 100)
                team_table.append({
                    "Project": ps["project"],
                    "Score": f'{ps["score"]:.0f}',
                    "Grade": ps["grade"],
                    "Percentile": f"{pctile}th",
                    "Prompts": ps.get("prompts", 0),
                })
            st.dataframe(team_table, width="stretch", hide_index=True)
    else:
        st.info(
            "**Team benchmarks** — Export and merge with teammates to see "
            "team percentile rankings.\n\n"
            "```bash\n"
            "# Each person:\n"
            "python -m clue export --scrub --user-label 'name' -o name.json\n\n"
            "# Merge:\n"
            "python -m clue merge alice.json bob.json -o team.json\n"
            "```"
        )

# ── Footer ───────────────────────────────────────────────────────
st.divider()
st.caption("Clue — AI Efficiency Scoring for Claude Code")
