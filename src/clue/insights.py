"""Insight computation helpers for the dashboard.

Stateless transformations operating on ScoringData / sqlite3.Cursor inputs.
Called by export.generate_dashboard_data.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from .models import MODEL_PRICING, ScoringData
from .patterns import CORRECTION_RE as _CORRECTION_RE
from .patterns import FILE_REF_RE as _FILE_REF_RE
from .patterns import SLASH_CMD_RE as _SLASH_CMD_RE


def estimate_cost(
    model: str, input_t: int, output_t: int, cache_create_t: int, cache_read_t: int
) -> float:
    """Estimate API cost for a single response based on token counts."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["_default"])
    return (
        (input_t / 1_000_000) * pricing["input"]
        + (output_t / 1_000_000) * pricing["output"]
        + (cache_create_t / 1_000_000) * pricing["cache_write"]
        + (cache_read_t / 1_000_000) * pricing["cache_read"]
    )


def compute_session_insights(
    global_data: ScoringData,
    per_project_data: dict[str, ScoringData],
    projects: list[str],
) -> dict:
    """Compute session-level insights from per-session metrics.

    Features:
    1. Best/worst sessions compared (top 10% vs bottom 10%)
    2. Per-project coaching with comparative data
    """
    metrics = global_data.session_metrics
    if len(metrics) < 5:
        return {"best_worst": None, "project_coaching": []}

    # --- Best vs worst sessions (by session cost) ---
    costed = [m for m in metrics if m.cost > 0]
    best_worst = None
    if len(costed) >= 10:
        by_cpp = sorted(costed, key=lambda m: m.cost)
        n10 = max(len(by_cpp) // 10, 1)
        top10 = by_cpp[:n10]
        bottom10 = by_cpp[-n10:]

        best_worst = {
            "top10": {
                "count": len(top10),
                "avg_prompt_length": round(
                    sum(m.avg_prompt_length for m in top10) / len(top10), 0
                ),
                "avg_turns": round(sum(m.turn_count for m in top10) / len(top10), 1),
                "avg_tool_diversity": round(
                    sum(m.tool_diversity for m in top10) / len(top10), 1
                ),
                "avg_cost": round(sum(m.cost for m in top10) / len(top10), 2),
                "correction_rate": round(
                    sum(m.correction_count for m in top10)
                    / max(sum(m.prompt_count for m in top10), 1) * 100, 1
                ),
                "read_before_edit_pct": round(
                    sum(1 for m in top10 if m.has_read_before_edit)
                    / len(top10) * 100, 0
                ),
            },
            "bottom10": {
                "count": len(bottom10),
                "avg_prompt_length": round(
                    sum(m.avg_prompt_length for m in bottom10) / len(bottom10), 0
                ),
                "avg_turns": round(
                    sum(m.turn_count for m in bottom10) / len(bottom10), 1
                ),
                "avg_tool_diversity": round(
                    sum(m.tool_diversity for m in bottom10) / len(bottom10), 1
                ),
                "avg_cost": round(
                    sum(m.cost for m in bottom10) / len(bottom10), 2
                ),
                "correction_rate": round(
                    sum(m.correction_count for m in bottom10)
                    / max(sum(m.prompt_count for m in bottom10), 1) * 100, 1
                ),
                "read_before_edit_pct": round(
                    sum(1 for m in bottom10 if m.has_read_before_edit)
                    / len(bottom10) * 100, 0
                ),
            },
        }

    # --- Per-project coaching ---
    project_coaching = []
    for proj in projects:
        proj_metrics = [m for m in metrics if m.project == proj and m.prompt_count > 0]
        if len(proj_metrics) < 3:
            continue

        total_prompts = sum(m.prompt_count for m in proj_metrics)
        total_corr = sum(m.correction_count for m in proj_metrics)
        total_cost = sum(m.cost for m in proj_metrics)
        total_tokens = sum(m.total_tokens for m in proj_metrics)

        project_coaching.append({
            "project": proj,
            "sessions": len(proj_metrics),
            "prompts": total_prompts,
            "correction_rate": round(total_corr / max(total_prompts, 1) * 100, 1),
            "cost_per_session": round(total_cost / len(proj_metrics), 2),
            "tokens_per_session": round(total_tokens / len(proj_metrics), 0),
            "avg_prompt_length": round(
                sum(m.avg_prompt_length for m in proj_metrics) / len(proj_metrics), 0
            ),
        })

    # Sort by cost_per_session descending (most expensive first)
    project_coaching.sort(key=lambda x: x["cost_per_session"], reverse=True)

    return {"best_worst": best_worst, "project_coaching": project_coaching}


def compute_weekly_digest(
    cur: sqlite3.Cursor,
    total_cost: float,
) -> dict:
    """Compute this-week vs last-week comparison for the digest."""
    today = datetime.now().strftime("%Y-%m-%d")

    cur.execute("SELECT COUNT(*) FROM prompts WHERE date > date(?, '-7 days')", (today,))
    has_recent_prompts = cur.fetchone()[0] > 0
    if not has_recent_prompts:
        # Fallback: check turns table for users whose data comes from conversations
        cur.execute(
            "SELECT COUNT(*) FROM turns WHERE SUBSTR(timestamp, 1, 10) > date(?, '-7 days')",
            (today,),
        )
        has_recent_turns = cur.fetchone()[0] > 0
        if not has_recent_turns:
            cur.execute("SELECT COUNT(*) FROM prompts")
            if cur.fetchone()[0] == 0:
                return {"has_data": False}

    # This week: last 7 days from today
    cur.execute(
        """
        SELECT
            COUNT(*) as prompts,
            COUNT(DISTINCT session_id) as sessions,
            AVG(char_length) as avg_len,
            SUM(CASE WHEN char_length < 15 THEN 1 ELSE 0 END) as short_prompts
        FROM prompts WHERE date > date(?, '-7 days')
    """,
        (today,),
    )
    this_week = cur.fetchone()

    # Last week: 8-14 days ago from today
    cur.execute(
        """
        SELECT
            COUNT(*) as prompts,
            COUNT(DISTINCT session_id) as sessions,
            AVG(char_length) as avg_len,
            SUM(CASE WHEN char_length < 15 THEN 1 ELSE 0 END) as short_prompts
        FROM prompts WHERE date > date(?, '-14 days') AND date <= date(?, '-7 days')
    """,
        (today, today),
    )
    last_week = cur.fetchone()

    # This week cost (per-model)
    cur.execute(
        """
        SELECT COALESCE(model, '_default'),
            SUM(input_tokens), SUM(output_tokens),
            SUM(cache_creation_tokens), SUM(cache_read_tokens)
        FROM turns WHERE SUBSTR(timestamp, 1, 10) > date(?, '-7 days')
        GROUP BY COALESCE(model, '_default')
    """,
        (today,),
    )
    tw_cost = sum(
        estimate_cost(r[0], r[1] or 0, r[2] or 0, r[3] or 0, r[4] or 0)
        for r in cur.fetchall()
    )

    # Last week cost (per-model)
    cur.execute(
        """
        SELECT COALESCE(model, '_default'),
            SUM(input_tokens), SUM(output_tokens),
            SUM(cache_creation_tokens), SUM(cache_read_tokens)
        FROM turns
        WHERE SUBSTR(timestamp, 1, 10) > date(?, '-14 days')
            AND SUBSTR(timestamp, 1, 10) <= date(?, '-7 days')
        GROUP BY COALESCE(model, '_default')
    """,
        (today, today),
    )
    lw_cost = sum(
        estimate_cost(r[0], r[1] or 0, r[2] or 0, r[3] or 0, r[4] or 0)
        for r in cur.fetchall()
    )

    # Correction rate this week vs last week
    tw_prompts_total = this_week[0] or 0
    lw_prompts_total = last_week[0] or 0

    cur.execute(
        "SELECT text FROM prompts WHERE date > date(?, '-7 days')", (today,)
    )
    tw_corrections = sum(
        1 for (t,) in cur.fetchall()
        if t and _CORRECTION_RE.match(t.strip())
    )
    tw_correction_rate = round(
        tw_corrections / max(tw_prompts_total, 1) * 100, 1
    )

    cur.execute(
        "SELECT text FROM prompts WHERE date > date(?, '-14 days') AND date <= date(?, '-7 days')",
        (today, today),
    )
    lw_corrections = sum(
        1 for (t,) in cur.fetchall()
        if t and _CORRECTION_RE.match(t.strip())
    )
    lw_correction_rate = round(
        lw_corrections / max(lw_prompts_total, 1) * 100, 1
    )

    # Compute date labels for display
    today_dt = datetime.now()
    tw_start = (today_dt - timedelta(days=7)).strftime("%b %d")
    lw_start = (today_dt - timedelta(days=14)).strftime("%b %d")
    lw_end = (today_dt - timedelta(days=7)).strftime("%b %d")
    today_label = today_dt.strftime("%b %d")

    return {
        "has_data": True,
        "this_week_label": f"{tw_start} – {today_label}",
        "last_week_label": f"{lw_start} – {lw_end}",
        "this_week": {
            "prompts": tw_prompts_total,
            "sessions": this_week[1] or 0,
            "avg_prompt_length": round(this_week[2] or 0, 0),
            "cost": round(tw_cost, 2),
            "correction_rate": tw_correction_rate,
        },
        "last_week": {
            "prompts": lw_prompts_total,
            "sessions": last_week[1] or 0,
            "avg_prompt_length": round(last_week[2] or 0, 0),
            "cost": round(lw_cost, 2),
            "correction_rate": lw_correction_rate,
        },
    }


def compute_prompt_learning(cur: sqlite3.Cursor) -> list[dict]:
    """Correlate prompt patterns with correction follow-ups.

    For each prompt, check if the NEXT prompt in the same session is a
    correction.  Group by pattern type and report correction rates.
    """
    cur.execute("""
        SELECT session_id, text, char_length
        FROM prompts ORDER BY session_id, timestamp
    """)
    rows = list(cur.fetchall())

    # Group prompts by session, detect which are followed by corrections
    sessions: dict[str, list[tuple[str, int, bool]]] = {}
    for r in rows:
        sid, text, length = r[0], r[1], r[2]
        sessions.setdefault(sid, []).append((text, length, False))

    # Mark prompts followed by a correction
    pattern_stats: dict[str, dict] = {
        "With file references": {"total": 0, "followed_by_correction": 0},
        "Without file references": {"total": 0, "followed_by_correction": 0},
        "Short prompts (<50 chars)": {"total": 0, "followed_by_correction": 0},
        "Detailed prompts (>200 chars)": {"total": 0, "followed_by_correction": 0},
        "Slash commands": {"total": 0, "followed_by_correction": 0},
    }

    for _sid, prompt_list in sessions.items():
        for i, (text, length, _) in enumerate(prompt_list):
            # Is the NEXT prompt a correction?
            next_is_correction = False
            if i + 1 < len(prompt_list):
                next_text = prompt_list[i + 1][0]
                next_is_correction = bool(
                    _CORRECTION_RE.match(next_text.strip())
                )

            # Skip if this prompt IS a correction
            if _CORRECTION_RE.match(text.strip()):
                continue

            has_file_ref = bool(_FILE_REF_RE.search(text))
            is_slash = bool(_SLASH_CMD_RE.match(text.strip()))

            if has_file_ref:
                pattern_stats["With file references"]["total"] += 1
                if next_is_correction:
                    pattern_stats["With file references"]["followed_by_correction"] += 1
            else:
                pattern_stats["Without file references"]["total"] += 1
                if next_is_correction:
                    pattern_stats["Without file references"]["followed_by_correction"] += 1

            if length < 50:
                pattern_stats["Short prompts (<50 chars)"]["total"] += 1
                if next_is_correction:
                    pattern_stats["Short prompts (<50 chars)"]["followed_by_correction"] += 1

            if length > 200:
                pattern_stats["Detailed prompts (>200 chars)"]["total"] += 1
                if next_is_correction:
                    pattern_stats["Detailed prompts (>200 chars)"]["followed_by_correction"] += 1

            if is_slash:
                pattern_stats["Slash commands"]["total"] += 1
                if next_is_correction:
                    pattern_stats["Slash commands"]["followed_by_correction"] += 1

    result = []
    for pattern, stats in pattern_stats.items():
        if stats["total"] >= 5:
            rate = stats["followed_by_correction"] / stats["total"] * 100
            result.append({
                "pattern": pattern,
                "count": stats["total"],
                "correction_rate": round(rate, 1),
            })

    return result


def build_advanced_usage(cur: sqlite3.Cursor) -> dict:
    """Build advanced usage analytics from the turns table."""
    # Agent type distribution
    cur.execute("""
        SELECT tool_input_subagent_type, COUNT(*)
        FROM turns WHERE tool_input_subagent_type IS NOT NULL
        GROUP BY tool_input_subagent_type ORDER BY 2 DESC
    """)
    agent_types = [{"type": r[0], "n": r[1]} for r in cur.fetchall()]

    # Parallel (background) agent invocations
    cur.execute("SELECT COUNT(*) FROM turns WHERE tool_input_run_in_background = 1")
    parallel_count = cur.fetchone()[0]

    # Total agent invocations for ratio
    cur.execute("SELECT COUNT(*) FROM turns WHERE tool_name = 'Agent'")
    total_agents = cur.fetchone()[0]

    # Skill usage
    cur.execute("""
        SELECT tool_input_skill, COUNT(*)
        FROM turns WHERE tool_input_skill IS NOT NULL
        GROUP BY tool_input_skill ORDER BY 2 DESC
    """)
    skills = [{"skill": r[0], "n": r[1]} for r in cur.fetchall()]

    # Task tool usage
    cur.execute("""
        SELECT tool_name, COUNT(*)
        FROM turns WHERE tool_name LIKE 'Task%'
        GROUP BY tool_name ORDER BY 2 DESC
    """)
    task_tools = [{"tool": r[0], "n": r[1]} for r in cur.fetchall()]

    # Daily advanced usage trends
    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date,
            SUM(CASE WHEN tool_name = 'Agent' THEN 1 ELSE 0 END) as agents,
            SUM(CASE WHEN tool_input_run_in_background = 1 THEN 1 ELSE 0 END) as parallel,
            SUM(CASE WHEN tool_input_skill IS NOT NULL THEN 1 ELSE 0 END) as skills,
            SUM(CASE WHEN tool_name LIKE 'Task%' THEN 1 ELSE 0 END) as tasks
        FROM turns WHERE timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date ORDER BY date
    """)
    daily = [
        {"d": r[0], "agents": r[1], "parallel": r[2], "skills": r[3], "tasks": r[4]}
        for r in cur.fetchall() if r[0]
    ]

    return {
        "agent_types": agent_types,
        "parallel_count": parallel_count,
        "total_agents": total_agents,
        "skills": skills,
        "task_tools": task_tools,
        "daily": daily,
    }
