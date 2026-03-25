"""Dashboard helpers — color palette, formatters, Plotly config."""

from __future__ import annotations

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


def score_color(score: float) -> str:
    """Return a color based on score threshold."""
    if score >= 80:
        return COLORS["green"]
    if score >= 60:
        return COLORS["amber"]
    return COLORS["rose"]


def grade_class(grade: str) -> str:
    """Return CSS class for a letter grade."""
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
    """Format a token count with K/M/B suffixes."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
