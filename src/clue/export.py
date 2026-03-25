"""Export SQLite data to JSON for the dashboard.

All dimensional data is exported at daily granularity so the dashboard
can filter by arbitrary date ranges (7d, 30d, 90d, all) client-side.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .db import query_all_projects, query_project_stats, query_scoring_data, query_trend_data
from .models import MODEL_PRICING, ScoringData
from .patterns import CORRECTION_RE as _CORRECTION_RE
from .patterns import DANGEROUS_CMD_RE as _DANGEROUS_CMD_RE
from .patterns import EXFILTRATION_RE as _EXFILTRATION_RE
from .patterns import FILE_REF_RE as _FILE_REF_RE
from .patterns import PROMPT_INJECTION_RE as _PROMPT_INJECTION_RE
from .patterns import SECRET_RE as _SECRET_RE
from .patterns import SENSITIVE_FILE_RE as _SENSITIVE_FILE_RE
from .patterns import SLASH_CMD_RE as _SLASH_CMD_RE
from .scorer import compute_project_scores, compute_score, compute_trend


def _estimate_cost(
    model: str, input_t: int, output_t: int, cache_create_t: int, cache_read_t: int
) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["_default"])
    return (
        (input_t / 1_000_000) * pricing["input"]
        + (output_t / 1_000_000) * pricing["output"]
        + (cache_create_t / 1_000_000) * pricing["cache_write"]
        + (cache_read_t / 1_000_000) * pricing["cache_read"]
    )


def _compute_session_insights(
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


def _compute_weekly_digest(
    cur: sqlite3.Cursor,
    total_cost: float,
) -> dict:
    """Compute this-week vs last-week comparison for the digest.

    Uses today's date as anchor so the window is always the actual
    current week, not relative to the latest data point.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    cur.execute("SELECT COUNT(*) FROM prompts WHERE date > date(?, '-7 days')", (today,))
    if cur.fetchone()[0] == 0:
        # No data in the last 7 days — check if any data exists at all
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
        _estimate_cost(r[0], r[1] or 0, r[2] or 0, r[3] or 0, r[4] or 0)
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
        _estimate_cost(r[0], r[1] or 0, r[2] or 0, r[3] or 0, r[4] or 0)
        for r in cur.fetchall()
    )

    # Correction rate this week vs last week
    tw_prompts_total = this_week[0] or 0
    lw_prompts_total = last_week[0] or 0

    # This week corrections
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

    # Last week corrections
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
    from datetime import timedelta

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


def _compute_prompt_learning(cur: sqlite3.Cursor) -> list[dict]:
    """Correlate prompt patterns with correction follow-ups.

    For each prompt, check if the NEXT prompt in the same session is a
    correction.  Group by pattern type and report correction rates.
    This is factual — derived from actual prompt sequences.
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

            # Skip if this prompt IS a correction (don't count correction→correction)
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


def _analyse_single_settings_file(
    settings_path: str, location_label: str,
) -> list[dict]:
    """Analyse one Claude settings file for security posture.

    Returns findings with a 'location' field showing where the issue was found.
    """
    import json as _json
    from pathlib import Path as _Path

    path = _Path(settings_path)
    findings: list[dict] = []

    if not path.exists():
        return findings

    try:
        settings = _json.loads(path.read_text())
    except (_json.JSONDecodeError, OSError):
        return findings

    def _add(category: str, severity: str, detail: str, setting: str) -> None:
        findings.append({
            "category": category,
            "severity": severity,
            "detail": detail,
            "setting": setting,
            "location": location_label,
        })

    permissions = settings.get("permissions", {})
    allow_list = permissions.get("allow", [])

    # Check for wildcard permissions
    dangerous_tools = {"Bash", "Write", "Edit", "Agent"}
    tool_categories = {
        "Bash": ("broad_bash_permissions", "high",
                 "Bash wildcard allows arbitrary shell command execution without review"),
        "Write": ("broad_write_permissions", "high",
                  "Write wildcard allows creating any file without review"),
        "Edit": ("broad_edit_permissions", "medium",
                 "Edit wildcard allows modifying any file without review"),
        "Agent": ("broad_agent_permissions", "medium",
                  "Agent wildcard allows spawning subagents without review"),
    }

    for entry in allow_list:
        if not isinstance(entry, str):
            continue
        if entry.strip() == "*":
            _add("wildcard_permissions", "critical",
                 "Global wildcard '*' in permissions allow list — "
                 "all tools run without human approval", entry)
            continue
        for tool in dangerous_tools:
            if entry.startswith(f"{tool}(") and "*" in entry:
                cat, sev, desc = tool_categories[tool]
                _add(cat, sev, f"'{entry}' — {desc}", entry)

    # Check for permission bypass modes
    if settings.get("bypassPermissions") is True:
        _add("wildcard_permissions", "critical",
             "bypassPermissions=true — all tools run without any approval",
             "bypassPermissions")

    if settings.get("autoApprove") is True:
        _add("wildcard_permissions", "critical",
             "autoApprove=true — all tool calls auto-approved",
             "autoApprove")

    # Broad allows with empty deny is worse
    deny_list = permissions.get("deny", [])
    has_broad_allows = any(
        isinstance(e, str) and ("*" in e or e.strip() in {"Bash", "Write", "Edit"})
        for e in allow_list
    )
    if has_broad_allows and not deny_list:
        _add("wildcard_permissions", "medium",
             "Broad allow rules with empty deny list — "
             "consider adding explicit denies for destructive operations",
             "permissions.deny=[]")

    # MCP servers — external tool providers expand attack surface
    mcp_servers = settings.get("mcpServers", {})
    if mcp_servers:
        for name, config in mcp_servers.items():
            if not isinstance(config, dict):
                continue
            _add("mcp_servers", "medium",
                 f"MCP server '{name}' configured — external tool providers "
                 "expand attack surface. Ensure this is a trusted server.",
                 f"mcpServers.{name}")

    return findings


def _analyse_claude_settings(claude_dir: str | None = None) -> list[dict]:
    """Analyse all Claude settings files for security posture.

    Checks three locations:
    - ~/.claude/settings.json (global)
    - <claude_dir>/settings.json (project — derived from claude_dir, not cwd)
    - <claude_dir>/settings.local.json (project local, gitignored)
    """
    from pathlib import Path as _Path

    findings: list[dict] = []

    # Global settings
    global_path = _Path.home() / ".claude" / "settings.json"
    findings.extend(_analyse_single_settings_file(
        str(global_path), "Global (~/.claude/settings.json)"))

    # Project-level settings — use claude_dir if provided, else cwd
    project_root = _Path(claude_dir).parent if claude_dir else _Path.cwd()
    project_path = project_root / ".claude" / "settings.json"
    if project_path.exists():
        findings.extend(_analyse_single_settings_file(
            str(project_path), "Project (.claude/settings.json)"))

    project_local_path = project_root / ".claude" / "settings.local.json"
    if project_local_path.exists():
        findings.extend(_analyse_single_settings_file(
            str(project_local_path), "Project Local (.claude/settings.local.json)"))

    return findings


def _scan_claude_md_files(claude_dir: str | None) -> list[dict]:
    """Scan CLAUDE.md files for risky instructions.

    Checks project CLAUDE.md and any in ~/.claude/ for patterns that
    could weaken security posture (e.g. 'always use --no-verify').
    """
    from pathlib import Path as _Path

    findings: list[dict] = []
    from .patterns import CLAUDE_MD_RISKS as _risks

    # Locations to check
    candidates: list[tuple[str, str]] = []

    # Project-level CLAUDE.md (cwd)
    cwd_claude = _Path.cwd() / "CLAUDE.md"
    if cwd_claude.exists():
        candidates.append((str(cwd_claude), "Project (CLAUDE.md)"))

    # Global CLAUDE.md
    if claude_dir:
        global_claude = _Path(claude_dir) / "CLAUDE.md"
        if global_claude.exists():
            candidates.append((str(global_claude), f"Global ({global_claude.name})"))

    for path, location in candidates:
        try:
            text = _Path(path).read_text(errors="replace")
        except OSError:
            continue
        for pattern, category, detail in _risks:
            if pattern.search(text):
                findings.append({
                    "category": category,
                    "severity": "high",
                    "detail": f"{detail} in {location}",
                    "location": location,
                })

    return findings


def _scan_responses_for_secrets(claude_dir: str | None) -> list[dict]:
    """Scan assistant responses in conversation JSONL for leaked secrets.

    Reads conversation files and checks assistant text blocks for secrets
    that the AI may have generated or echoed back.
    Filters out common placeholder values to reduce false positives.
    """
    import json as _json
    from pathlib import Path as _Path

    from .patterns import PLACEHOLDER_SECRET_RE as _PLACEHOLDER_RE

    findings: list[dict] = []
    if not claude_dir:
        return findings

    projects_dir = _Path(claude_dir) / "projects"
    if not projects_dir.exists():
        return findings

    seen_sessions: set[str] = set()
    session_details: list[tuple[str, str, str | None]] = []  # (session_id, project, date)

    for jsonl_file in projects_dir.rglob("*.jsonl"):
        try:
            lines = jsonl_file.read_text(errors="replace").splitlines()
        except OSError:
            continue

        session_has_secret = False
        for line in lines:
            if session_has_secret:
                break
            try:
                entry = _json.loads(line)
            except _json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue
            msg = entry.get("message", {})
            if msg.get("role") != "assistant":
                continue

            for block in msg.get("content", []):
                if block.get("type") != "text":
                    continue
                text = block.get("text", "")
                match = _SECRET_RE.search(text)
                if match and not _PLACEHOLDER_RE.search(match.group()):
                    session_id = jsonl_file.stem
                    if session_id not in seen_sessions:
                        seen_sessions.add(session_id)
                        ts = entry.get("timestamp", "")
                        date = ts[:10] if len(ts) >= 10 else None
                        # Extract project from path: projects/<project-dir>/session.jsonl
                        project_dir = jsonl_file.parent.name
                        if project_dir == "subagents":
                            project_dir = jsonl_file.parent.parent.parent.name
                        session_details.append((session_id, project_dir, date))
                        session_has_secret = True
                        break

    # Produce actionable findings — group by date, show session IDs
    if not session_details:
        return findings

    # If many sessions, summarise rather than list each one
    if len(session_details) > 5:
        dates = sorted({d for _, _, d in session_details if d})
        date_range = f"{dates[0]} to {dates[-1]}" if len(dates) > 1 else (dates[0] if dates else "unknown")
        findings.append({
            "category": "secrets_in_responses",
            "severity": "high",
            "detail": (
                f"{len(session_details)} sessions contain potential secrets in AI responses "
                f"({date_range}). Review sessions to determine if real credentials were exposed "
                f"or if these are code examples with placeholder values."
            ),
            "date": dates[-1] if dates else None,
        })
    else:
        for session_id, project_dir, date in session_details:
            findings.append({
                "category": "secrets_in_responses",
                "severity": "high",
                "detail": (
                    f"Session {session_id[:12]}… in {project_dir} — "
                    "AI response contains potential secret/credential"
                ),
                "date": date,
            })

    return findings


def _build_security_analysis(
    cur: sqlite3.Cursor,
    claude_dir: str | None = None,
) -> dict:
    """Analyse usage data for security anti-patterns.

    Detects:
    - Sensitive files read into AI context (.env, credentials, keys)
    - Dangerous shell commands (rm -rf /, force push, hook bypass, sandbox bypass)
    - Secrets potentially exposed in prompts (API keys, tokens)
    - Secrets echoed back in AI responses
    - CLAUDE.md files with risky instructions
    - Sandbox bypasses (dangerouslyDisableSandbox)
    """
    findings: list[dict] = []
    category_counts: dict[str, int] = {}

    def _add(category: str, severity: str, detail: str, date: str | None = None) -> None:
        findings.append({
            "category": category,
            "severity": severity,
            "detail": detail,
            "date": date,
        })
        category_counts[category] = category_counts.get(category, 0) + 1

    # Scan prompts for security anti-patterns
    # (File-path scan limited to prompt text; tool input paths not stored in DB)
    cur.execute("SELECT date, text FROM prompts ORDER BY date")
    for row in cur.fetchall():
        date, text = row[0], row[1]
        if _SECRET_RE.search(text):
            _add("secrets_in_prompts", "high",
                 "Potential secret/credential detected in prompt text", date)
        if _DANGEROUS_CMD_RE.search(text):
            _add("dangerous_commands", "high",
                 "Dangerous command pattern detected in prompt", date)
        if _SENSITIVE_FILE_RE.search(text):
            _add("sensitive_file_refs", "medium",
                 "Reference to sensitive file in prompt", date)
        if _PROMPT_INJECTION_RE.search(text):
            _add("prompt_injection", "critical",
                 "Prompt injection pattern detected — attempt to override AI instructions", date)
        if _EXFILTRATION_RE.search(text):
            _add("data_exfiltration", "critical",
                 "Data exfiltration pattern — sending secrets to external service", date)

    # 3. Hook bypass detection — --no-verify in prompts
    cur.execute("""
        SELECT date, COUNT(*) FROM prompts
        WHERE text LIKE '%--no-verify%'
        GROUP BY date
    """)
    for row in cur.fetchall():
        _add("hook_bypass", "high",
             f"{row[1]} prompt(s) requesting --no-verify", row[0])

    # 4. Force push detection
    cur.execute("""
        SELECT date, COUNT(*) FROM prompts
        WHERE text LIKE '%force push%' OR text LIKE '%push --force%'
            OR text LIKE '%push -f%' OR text LIKE '%-f push%'
        GROUP BY date
    """)
    for row in cur.fetchall():
        _add("force_push", "medium",
             f"{row[1]} prompt(s) requesting force push", row[0])

    # 5. Sandbox bypass — turns with dangerouslyDisableSandbox
    # This would be in Bash tool input, but we don't store full input.
    # Check prompts for the pattern instead.
    cur.execute("""
        SELECT date, COUNT(*) FROM prompts
        WHERE text LIKE '%dangerouslyDisableSandbox%'
        GROUP BY date
    """)
    for row in cur.fetchall():
        _add("sandbox_bypass", "critical",
             f"{row[1]} prompt(s) requesting sandbox bypass", row[0])

    # 6. Permission analysis — detect overly broad tool access patterns
    # High Bash-to-total ratio with no rejections suggests broad permissions
    cur.execute("SELECT COUNT(*) FROM turns WHERE tool_name = 'Bash'")
    bash_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM turns WHERE tool_name IS NOT NULL")
    total_tool_turns = cur.fetchone()[0]

    if total_tool_turns > 0:
        bash_pct = bash_count / total_tool_turns * 100
        if bash_pct > 40:
            _add("broad_bash_access", "medium",
                 f"Bash is {bash_pct:.0f}% of all tool calls — consider restricting "
                 "allowed commands to reduce attack surface", None)

    # 6b. Permission bypass flags in prompts
    cur.execute("""
        SELECT date, COUNT(*) FROM prompts
        WHERE text LIKE '%--dangerouslySkipPermissions%'
           OR text LIKE '%--trust-tools%'
           OR text LIKE '%bypassPermissions%'
        GROUP BY date
    """)
    for row in cur.fetchall():
        _add("wildcard_permissions", "critical",
             f"{row[1]} prompt(s) referencing permission bypass flags", row[0])

    # 6c. Excessive unreviewed tool usage per session — summarise, don't spam
    cur.execute("""
        SELECT COUNT(*), MAX(tool_count) FROM (
            SELECT COUNT(*) AS tool_count
            FROM turns
            WHERE tool_name IS NOT NULL
            GROUP BY session_id
            HAVING tool_count > 500
        )
    """)
    row = cur.fetchone()
    heavy_sessions, max_tools = row[0], row[1]
    if heavy_sessions > 0:
        _add("high_agent_autonomy", "medium",
             f"{heavy_sessions} session(s) with >500 tool calls "
             f"(max: {max_tools}) — may indicate excessive autonomy", None)

    # Detect high agent-to-session ratio
    cur.execute("SELECT COUNT(*) FROM turns WHERE tool_name = 'Agent'")
    agent_total = cur.fetchone()[0]
    if agent_total > 20:
        cur.execute("""
            SELECT COUNT(DISTINCT session_id) FROM turns WHERE tool_name = 'Agent'
        """)
        agent_sessions = cur.fetchone()[0]
        avg = agent_total / max(agent_sessions, 1)
        if avg > 15:
            _add("high_agent_autonomy", "medium",
                 f"Average {avg:.0f} agent calls per session across "
                 f"{agent_sessions} session(s) — ensure agents are scoped appropriately",
                 None)

    # 7. Daily security signal counts for trend chart
    cur.execute("SELECT DISTINCT date FROM prompts ORDER BY date")
    all_dates = [r[0] for r in cur.fetchall()]

    date_findings: dict[str, dict[str, int]] = {}
    for f in findings:
        d = f.get("date")
        if d:
            if d not in date_findings:
                date_findings[d] = {"high": 0, "medium": 0, "critical": 0}
            date_findings[d][f["severity"]] = date_findings[d].get(f["severity"], 0) + 1

    daily_security = [
        {
            "d": d,
            "critical": date_findings.get(d, {}).get("critical", 0),
            "high": date_findings.get(d, {}).get("high", 0),
            "medium": date_findings.get(d, {}).get("medium", 0),
        }
        for d in all_dates
        if d in date_findings
    ]

    # 8. Settings analysis — check ~/.claude/settings.json for broad permissions
    settings_findings = _analyse_claude_settings()
    for sf in settings_findings:
        _add(sf["category"], sf["severity"], sf["detail"], None)

    # 9. CLAUDE.md trust audit — scan for risky instructions
    claude_md_findings = _scan_claude_md_files(claude_dir)
    for cf in claude_md_findings:
        _add(cf["category"], cf["severity"], cf["detail"], None)

    # 10. Secrets in AI responses — scan conversation files
    response_findings = _scan_responses_for_secrets(claude_dir)
    for rf in response_findings:
        _add(rf["category"], rf["severity"], rf["detail"], rf.get("date"))

    # Compute risk score (0 = clean, higher = more risk)
    risk_score = (
        category_counts.get("prompt_injection", 0) * 50
        + category_counts.get("data_exfiltration", 0) * 50
        + category_counts.get("wildcard_permissions", 0) * 50
        + category_counts.get("sandbox_bypass", 0) * 50
        + category_counts.get("broad_bash_permissions", 0) * 30
        + category_counts.get("broad_write_permissions", 0) * 20
        + category_counts.get("secrets_in_prompts", 0) * 20
        + category_counts.get("secrets_in_responses", 0) * 20
        + category_counts.get("dangerous_commands", 0) * 15
        + category_counts.get("hook_bypass", 0) * 10
        + category_counts.get("broad_edit_permissions", 0) * 10
        + category_counts.get("broad_agent_permissions", 0) * 5
        + category_counts.get("force_push", 0) * 5
        + category_counts.get("sensitive_file_refs", 0) * 5
        + category_counts.get("mcp_servers", 0) * 5
    )
    # Cap at 100
    risk_score = min(risk_score, 100)

    return {
        "findings": findings,
        "category_counts": category_counts,
        "total_findings": len(findings),
        "risk_score": risk_score,
        "daily": daily_security,
        "settings_findings": settings_findings,
    }


def _build_advanced_usage(cur: sqlite3.Cursor) -> dict:
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


def generate_dashboard_data(
    conn: sqlite3.Connection,
    scrub: bool = False,
    user_label: str | None = None,
    git_correlation: bool = False,
    claude_dir: str | None = None,
) -> dict:
    """Query SQLite and produce a JSON-serialisable dict for the dashboard.

    Args:
        git_correlation: If True, run git log against local repos to correlate
            sessions with commits (adds session_outcomes, time_to_value).
            Slower due to subprocess calls.
    """
    cur = conn.cursor()

    # --- Overview (all-time) ---
    cur.execute("SELECT COUNT(*) FROM prompts")
    total_prompts = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM sessions WHERE prompt_count > 0 OR turn_count > 0")
    total_sessions = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT project) FROM (
            SELECT project FROM prompts
            UNION
            SELECT project FROM turns WHERE project IS NOT NULL
        )
    """)
    total_projects = cur.fetchone()[0]

    cur.execute(
        "SELECT SUM(input_tokens), SUM(output_tokens),"
        " SUM(cache_creation_tokens), SUM(cache_read_tokens) FROM turns"
    )
    row = cur.fetchone()
    total_input = row[0] or 0
    total_output = row[1] or 0
    total_cache_create = row[2] or 0
    total_cache_read = row[3] or 0
    total_tokens = total_input + total_output + total_cache_create + total_cache_read

    cur.execute("SELECT AVG(char_length) FROM prompts")
    avg_prompt_length = round(cur.fetchone()[0] or 0, 1)

    cur.execute("SELECT COUNT(*) FROM turns WHERE is_subagent = 1")
    subagent_turns = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM turns")
    total_turns = cur.fetchone()[0]

    cache_total = total_cache_create + total_cache_read
    cache_hit_rate = round(total_cache_read / cache_total * 100, 1) if cache_total > 0 else 0

    # --- Daily activity (prompts + sessions per day) ---
    # Prompts come from history.jsonl (may not capture all sessions).
    # Session counts come from turns table which has complete coverage.
    cur.execute("""
        SELECT date, COUNT(*) as prompts FROM prompts GROUP BY date
    """)
    daily_prompts_map = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date, COUNT(DISTINCT session_id) as sessions
        FROM turns WHERE timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date
    """)
    daily_sessions_map = {r[0]: r[1] for r in cur.fetchall() if r[0]}

    all_dates = sorted(set(daily_prompts_map) | set(daily_sessions_map))
    daily_usage = [
        {
            "d": d,
            "p": daily_prompts_map.get(d, 0),
            "s": daily_sessions_map.get(d, 0),
        }
        for d in all_dates
    ]

    # --- Daily tokens ---
    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date,
            SUM(input_tokens), SUM(output_tokens),
            SUM(cache_creation_tokens), SUM(cache_read_tokens)
        FROM turns WHERE timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date ORDER BY date
    """)
    daily_tokens = [
        {"d": r[0], "i": r[1], "o": r[2], "cw": r[3], "cr": r[4]} for r in cur.fetchall() if r[0]
    ]

    # --- Daily cost by model ---
    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date, model,
            SUM(input_tokens), SUM(output_tokens),
            SUM(cache_creation_tokens), SUM(cache_read_tokens)
        FROM turns WHERE model IS NOT NULL AND timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date, model ORDER BY date
    """)
    daily_cost = []
    for r in cur.fetchall():
        if r[0]:
            cost = _estimate_cost(r[1], r[2], r[3], r[4], r[5])
            daily_cost.append({"d": r[0], "m": r[1], "c": round(cost, 4)})

    # --- Daily project prompts ---
    cur.execute("""
        SELECT date, project, COUNT(*) as prompts
        FROM prompts GROUP BY date, project ORDER BY date
    """)
    daily_project = [{"d": r[0], "pj": r[1], "p": r[2]} for r in cur.fetchall()]

    # --- Daily project tokens ---
    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date, project,
            SUM(input_tokens) + SUM(output_tokens)
            + SUM(cache_creation_tokens) + SUM(cache_read_tokens)
        FROM turns WHERE timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date, project ORDER BY date
    """)
    daily_project_tokens = [{"d": r[0], "pj": r[1], "t": r[2]} for r in cur.fetchall() if r[0]]

    # --- Daily tool usage ---
    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date, tool_name, COUNT(*)
        FROM turns WHERE tool_name IS NOT NULL AND timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date, tool_name ORDER BY date
    """)
    daily_tools = [{"d": r[0], "tool": r[1], "n": r[2]} for r in cur.fetchall() if r[0]]

    # --- Daily model usage ---
    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date, model, COUNT(*),
            SUM(input_tokens), SUM(output_tokens)
        FROM turns WHERE model IS NOT NULL AND timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date, model ORDER BY date
    """)
    daily_models = [
        {"d": r[0], "m": r[1], "n": r[2], "i": r[3], "o": r[4]} for r in cur.fetchall() if r[0]
    ]

    # --- Prompt lengths with dates ---
    cur.execute("SELECT date, char_length FROM prompts ORDER BY date")
    prompt_lengths = [{"d": r[0], "l": r[1]} for r in cur.fetchall()]

    # --- Hourly distribution (all-time, kept for patterns) ---
    cur.execute("SELECT hour, COUNT(*) FROM prompts GROUP BY hour ORDER BY hour")
    hourly = {r[0]: r[1] for r in cur.fetchall()}
    hourly_distribution = [{"hour": h, "prompts": hourly.get(h, 0)} for h in range(24)]

    # --- Day of week ---
    cur.execute(
        "SELECT day_of_week, COUNT(*) FROM prompts GROUP BY day_of_week ORDER BY day_of_week"
    )
    dow_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    dow = {r[0]: r[1] for r in cur.fetchall()}
    day_of_week_distribution = [{"day": dow_map[d], "prompts": dow.get(d, 0)} for d in range(7)]

    # --- Total cost ---
    cur.execute("""
        SELECT model, SUM(input_tokens), SUM(output_tokens),
            SUM(cache_creation_tokens), SUM(cache_read_tokens)
        FROM turns WHERE model IS NOT NULL GROUP BY model
    """)
    total_estimated_cost = 0.0
    model_totals = []
    for r in cur.fetchall():
        cost = _estimate_cost(r[0], r[1], r[2], r[3], r[4])
        total_estimated_cost += cost
        model_totals.append(
            {
                "model": r[0],
                "input_tokens": r[1],
                "output_tokens": r[2],
                "estimated_cost_usd": round(cost, 4),
            }
        )

    # --- Efficiency scores (query data, then compute) ---
    scoring_data = query_scoring_data(conn)
    overall_score = compute_score(scoring_data)
    trend_data = query_trend_data(conn)
    trend, trend_delta = compute_trend(trend_data)
    overall_score.trend = trend
    overall_score.trend_delta = trend_delta

    projects = query_all_projects(conn)
    per_project_data = {p: query_scoring_data(conn, project=p) for p in projects}
    per_project_stats = {p: query_project_stats(conn, p) for p in projects}
    project_scores = compute_project_scores(projects, per_project_data, per_project_stats)

    # --- Git branch with most-used project per branch ---
    cur.execute("""
        SELECT b.git_branch, b.cnt, b.out_tokens, (
            SELECT t2.project FROM turns t2
            WHERE t2.git_branch = b.git_branch
            GROUP BY t2.project ORDER BY COUNT(*) DESC LIMIT 1
        ) as top_project
        FROM (
            SELECT git_branch, COUNT(*) as cnt, SUM(output_tokens) as out_tokens
            FROM turns
            WHERE git_branch IS NOT NULL AND git_branch != '' AND git_branch != 'HEAD'
            GROUP BY git_branch
            ORDER BY cnt DESC LIMIT 20
        ) b
    """)
    branch_usage = [
        {
            "branch": r[0], "turns": r[1],
            "output_tokens": r[2] or 0, "project": r[3] or "",
        }
        for r in cur.fetchall()
    ]

    # --- Journey: Session summaries (most recent 100) ---
    cur.execute("""
        SELECT s.session_id, s.project, s.started_at, s.prompt_count,
            s.total_input_tokens + s.total_output_tokens as total_tokens,
            s.tools_used, s.turn_count
        FROM sessions s
        WHERE s.prompt_count > 0
        ORDER BY s.started_at DESC LIMIT 100
    """)
    session_summaries = []
    for r in cur.fetchall():
        tools_raw = r[5]
        try:
            tools_dict = json.loads(tools_raw) if tools_raw else {}
        except (json.JSONDecodeError, TypeError):
            tools_dict = {}
        session_summaries.append({
            "id": r[0], "project": r[1], "started": r[2],
            "prompts": r[3], "tokens": r[4] or 0,
            "tools": tools_dict, "turns": r[6] or 0,
        })

    # --- Journey: Activity heatmap (hour x day_of_week) ---
    cur.execute("""
        SELECT hour, day_of_week, COUNT(*) as prompts
        FROM prompts GROUP BY hour, day_of_week
    """)
    heatmap_data = [{"h": r[0], "d": r[1], "v": r[2]} for r in cur.fetchall()]

    # --- Journey: Session depth distribution ---
    cur.execute("""
        SELECT prompt_count, COUNT(*) as sessions
        FROM sessions WHERE prompt_count > 0
        GROUP BY prompt_count ORDER BY prompt_count
    """)
    session_depth_dist = [{"depth": r[0], "count": r[1]} for r in cur.fetchall()]

    # --- Journey: Daily iteration signals ---
    cur.execute("SELECT date, text FROM prompts ORDER BY date")
    daily_texts: dict[str, list[str]] = {}
    for r in cur.fetchall():
        daily_texts.setdefault(r[0], []).append(r[1])

    daily_iteration = []
    for date, texts in sorted(daily_texts.items()):
        total = len(texts)
        corrections = sum(1 for t in texts if _CORRECTION_RE.match(t.strip()))
        daily_iteration.append({
            "d": date,
            "total": total,
            "corrections": corrections,
            "correction_pct": round(corrections / total * 100, 1) if total else 0,
        })

    # --- Journey: Weekly summaries ---
    cur.execute("""
        SELECT strftime('%Y-W%W', date) as week,
            COUNT(*) as prompts,
            COUNT(DISTINCT session_id) as sessions,
            AVG(char_length) as avg_len,
            COUNT(DISTINCT date) as active_days
        FROM prompts GROUP BY week ORDER BY week
    """)
    weekly_summaries = [
        {"w": r[0], "p": r[1], "s": r[2], "avg_len": round(r[3] or 0, 1), "days": r[4]}
        for r in cur.fetchall()
    ]

    # --- Journey: Usage streak ---
    active_dates = sorted({r["d"] for r in daily_usage})
    streak = 0
    if active_dates:
        from datetime import date as date_cls, timedelta

        today = date_cls.today()
        parsed = [date_cls.fromisoformat(d) for d in active_dates]
        # Count consecutive days ending at most recent active day
        # (only counts as "current" streak if last active day is today or yesterday)
        last_active = parsed[-1]
        if (today - last_active).days > 1:
            streak = 0
        else:
            current_streak = 1  # last_active day itself
            for d in reversed(parsed[:-1]):
                if d == last_active - timedelta(days=current_streak):
                    current_streak += 1
                else:
                    break
            streak = current_streak

    # --- Feature 3: Stop reason analysis (exact data from turns.stop_reason) ---
    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date, stop_reason, COUNT(*)
        FROM turns WHERE stop_reason IS NOT NULL AND timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date, stop_reason ORDER BY date
    """)
    daily_stop_reasons = [
        {"d": r[0], "reason": r[1], "n": r[2]} for r in cur.fetchall() if r[0]
    ]

    # Stop reason totals (all-time)
    cur.execute("""
        SELECT stop_reason, COUNT(*) FROM turns
        WHERE stop_reason IS NOT NULL GROUP BY stop_reason ORDER BY 2 DESC
    """)
    stop_reason_totals = [{"reason": r[0], "n": r[1]} for r in cur.fetchall()]

    # --- Feature 4: Agentic usage (exact data from turns.is_subagent) ---
    cur.execute("""
        SELECT SUBSTR(timestamp, 1, 10) as date,
            SUM(CASE WHEN is_subagent = 1 THEN 1 ELSE 0 END) as agent_turns,
            SUM(CASE WHEN is_subagent = 0 THEN 1 ELSE 0 END) as main_turns,
            SUM(CASE WHEN is_subagent = 1
                THEN input_tokens + output_tokens ELSE 0 END) as agent_tok,
            SUM(CASE WHEN is_subagent = 0
                THEN input_tokens + output_tokens ELSE 0 END) as main_tok
        FROM turns WHERE timestamp IS NOT NULL AND timestamp != ''
        GROUP BY date ORDER BY date
    """)
    daily_agentic = [
        {"d": r[0], "at": r[1], "mt": r[2], "a_tok": r[3] or 0, "m_tok": r[4] or 0}
        for r in cur.fetchall() if r[0]
    ]

    # Agentic cost split (all-time by is_subagent × model)
    cur.execute("""
        SELECT is_subagent, model, SUM(input_tokens), SUM(output_tokens),
            SUM(cache_creation_tokens), SUM(cache_read_tokens)
        FROM turns WHERE model IS NOT NULL
        GROUP BY is_subagent, model
    """)
    agentic_cost_split = {"agent": 0.0, "main": 0.0}
    for r in cur.fetchall():
        cost = _estimate_cost(r[1], r[2], r[3], r[4], r[5])
        if r[0] == 1:
            agentic_cost_split["agent"] += cost
        else:
            agentic_cost_split["main"] += cost
    agentic_cost_split = {
        k: round(v, 4) for k, v in agentic_cost_split.items()
    }

    # --- Feature 2: Per-project cost efficiency ---
    # Session counts per (date, project) — independent of model splits
    cur.execute("""
        SELECT SUBSTR(t.timestamp, 1, 10) as date, t.project,
            COUNT(DISTINCT t.session_id) as sessions
        FROM turns t
        WHERE t.timestamp IS NOT NULL AND t.timestamp != ''
        GROUP BY date, t.project
    """)
    pce_sessions: dict[tuple[str, str], int] = {}
    for r in cur.fetchall():
        if r[0]:
            pce_sessions[(r[0], r[1])] = r[2]

    # Cost per (date, project) grouped by model for accurate pricing
    cur.execute("""
        SELECT SUBSTR(t.timestamp, 1, 10) as date, t.project, t.model,
            SUM(t.input_tokens), SUM(t.output_tokens),
            SUM(t.cache_creation_tokens), SUM(t.cache_read_tokens)
        FROM turns t
        WHERE t.timestamp IS NOT NULL AND t.timestamp != '' AND t.model IS NOT NULL
        GROUP BY date, t.project, t.model ORDER BY date
    """)
    pce_cost_map: dict[tuple[str, str], float] = {}
    for r in cur.fetchall():
        if not r[0]:
            continue
        cost = _estimate_cost(r[2], r[3] or 0, r[4] or 0, r[5] or 0, r[6] or 0)
        key = (r[0], r[1])
        pce_cost_map[key] = pce_cost_map.get(key, 0.0) + cost

    project_cost_efficiency = []
    for key, cost in pce_cost_map.items():
        sessions = pce_sessions.get(key, 1)
        cost_r = round(cost, 4)
        project_cost_efficiency.append({
            "d": key[0], "pj": key[1], "sessions": sessions,
            "cost": cost_r, "cps": round(cost_r / max(sessions, 1), 4),
        })

    # --- Feature 8: Correction cost (accurate — tokens in turns following corrections) ---
    # For each session, find prompts that match correction pattern, then sum the tokens
    # of the assistant turn that follows.
    cur.execute("""
        SELECT p.session_id, p.date, p.text
        FROM prompts p ORDER BY p.session_id, p.timestamp
    """)
    session_correction_prompts: dict[str, list[str]] = {}
    for r in cur.fetchall():
        session_correction_prompts.setdefault(r[0], []).append(r[2])

    # Count correction prompts per session, then get session token totals
    correction_sessions: dict[str, int] = {}
    for sid, texts in session_correction_prompts.items():
        corr_count = sum(1 for t in texts if _CORRECTION_RE.match(t.strip()))
        if corr_count > 0:
            correction_sessions[sid] = corr_count

    # Get per-session token costs for sessions with corrections
    total_correction_cost = 0.0
    total_all_cost = total_estimated_cost
    if correction_sessions:
        placeholders = ",".join("?" * len(correction_sessions))
        cur.execute(
            f"""
            SELECT session_id, model,
                SUM(input_tokens), SUM(output_tokens),
                SUM(cache_creation_tokens), SUM(cache_read_tokens)
            FROM turns WHERE session_id IN ({placeholders}) AND model IS NOT NULL
            GROUP BY session_id, model
            """,
            list(correction_sessions.keys()),
        )
        session_costs: dict[str, float] = {}
        for r in cur.fetchall():
            cost = _estimate_cost(r[1], r[2] or 0, r[3] or 0, r[4] or 0, r[5] or 0)
            session_costs[r[0]] = session_costs.get(r[0], 0.0) + cost

        # Estimate: correction fraction of session = correction_prompts / total_prompts
        for sid, corr_count in correction_sessions.items():
            total_in_session = len(session_correction_prompts.get(sid, []))
            if total_in_session > 0 and sid in session_costs:
                correction_fraction = corr_count / total_in_session
                total_correction_cost += session_costs[sid] * correction_fraction

    correction_cost_data = {
        "cost": round(total_correction_cost, 4),
        "pct": (
            round(total_correction_cost / total_all_cost * 100, 1)
            if total_all_cost > 0
            else 0
        ),
        "sessions": len(correction_sessions),
    }

    # --- Feature 9: Prompt pattern distributions (factual stats, not causal) ---
    cur.execute("""
        SELECT p.session_id, p.text,
            (SELECT SUM(t.input_tokens + t.output_tokens)
             FROM turns t WHERE t.session_id = p.session_id) as session_tokens
        FROM prompts p
    """)

    # Track (session_id, tokens) per pattern to deduplicate session tokens
    pattern_buckets: dict[str, list[tuple[str, int]]] = {
        "has_file_ref": [],
        "has_slash_cmd": [],
        "short_prompt": [],
        "long_prompt": [],
        "all": [],
    }
    for r in cur.fetchall():
        sid, text, tokens = r[0], r[1], r[2] or 0
        pattern_buckets["all"].append((sid, tokens))
        if _FILE_REF_RE.search(text):
            pattern_buckets["has_file_ref"].append((sid, tokens))
        if _SLASH_CMD_RE.match(text.strip()):
            pattern_buckets["has_slash_cmd"].append((sid, tokens))
        if len(text) < 50:
            pattern_buckets["short_prompt"].append((sid, tokens))
        if len(text) > 200:
            pattern_buckets["long_prompt"].append((sid, tokens))

    prompt_pattern_stats = []
    for pattern, entries in pattern_buckets.items():
        prompt_count = len(entries)
        if prompt_count > 0:
            # Deduplicate: average session tokens across unique sessions, not per prompt
            unique_sessions = {sid: tok for sid, tok in entries}
            avg_tokens = sum(unique_sessions.values()) / len(unique_sessions)
            prompt_pattern_stats.append({
                "pattern": pattern,
                "count": prompt_count,
                "avg_session_tokens": round(avg_tokens, 0),
            })

    # --- Session insights: best/worst sessions, per-project coaching ---
    session_insights = _compute_session_insights(scoring_data, per_project_data, projects)

    # --- Weekly digest ---
    weekly_digest = _compute_weekly_digest(cur, total_estimated_cost)

    # --- Prompt learning: pattern → correction correlation ---
    prompt_learning = _compute_prompt_learning(cur)

    # --- Time-of-day correction analysis ---
    cur.execute("SELECT hour, text FROM prompts WHERE hour IS NOT NULL")
    hourly_texts: dict[int, list[str]] = {}
    for r in cur.fetchall():
        hourly_texts.setdefault(r[0], []).append(r[1])

    hourly_correction_rates = []
    for hour in sorted(hourly_texts.keys()):
        texts = hourly_texts[hour]
        total = len(texts)
        corr = sum(1 for t in texts if _CORRECTION_RE.match(t.strip()))
        hourly_correction_rates.append({
            "hour": hour,
            "prompts": total,
            "corrections": corr,
            "correction_rate": round(corr / max(total, 1) * 100, 1),
        })

    # --- Expensive sessions drill-down (top 20 by estimated cost) ---
    expensive_sessions = []
    costed_metrics = sorted(
        [m for m in scoring_data.session_metrics if m.cost > 0],
        key=lambda m: m.cost, reverse=True,
    )[:20]
    for m in costed_metrics:
        expensive_sessions.append({
            "session_id": m.session_id[:12],
            "project": m.project,
            "cost": round(m.cost, 2),
            "prompts": m.prompt_count,
            "corrections": m.correction_count,
            "correction_rate": round(
                m.correction_count / max(m.prompt_count, 1) * 100, 1
            ),
            "ai_responses": m.turn_count,
            "tools": m.tool_diversity,
            "model": m.model or "unknown",
        })

    # --- Branch coaching (correction rate + cost per branch) ---
    # Session counts and primary project per branch
    cur.execute("""
        SELECT t.git_branch, COUNT(DISTINCT t.session_id) as sessions
        FROM turns t
        WHERE t.git_branch IS NOT NULL AND t.git_branch != ''
            AND t.git_branch != 'HEAD'
        GROUP BY t.git_branch
    """)
    branch_session_map: dict[str, int] = {r[0]: r[1] for r in cur.fetchall()}

    # Primary project per branch (project with the most turns on that branch)
    cur.execute("""
        SELECT git_branch, project, COUNT(*) as cnt
        FROM turns
        WHERE git_branch IS NOT NULL AND git_branch != '' AND git_branch != 'HEAD'
        GROUP BY git_branch, project ORDER BY git_branch, cnt DESC
    """)
    branch_project_map: dict[str, str] = {}
    for br, proj, _cnt in cur.fetchall():
        if br not in branch_project_map:
            branch_project_map[br] = proj

    # Cost per branch grouped by model for accurate pricing
    cur.execute("""
        SELECT t.git_branch, t.model,
            COALESCE(SUM(t.input_tokens), 0) as input_tokens,
            COALESCE(SUM(t.output_tokens), 0) as output_tokens,
            COALESCE(SUM(t.cache_creation_tokens), 0) as cache_create,
            COALESCE(SUM(t.cache_read_tokens), 0) as cache_read
        FROM turns t
        WHERE t.git_branch IS NOT NULL AND t.git_branch != ''
            AND t.git_branch != 'HEAD' AND t.model IS NOT NULL
        GROUP BY t.git_branch, t.model
    """)
    branch_cost_map: dict[str, dict] = {}
    for br, model, in_t, out_t, cw_t, cr_t in cur.fetchall():
        cost = _estimate_cost(model, in_t, out_t, cw_t, cr_t)
        if br not in branch_cost_map:
            branch_cost_map[br] = {"sessions": branch_session_map.get(br, 1), "cost": 0.0}
        branch_cost_map[br]["cost"] += cost

    # Take top 20 branches by session count
    top_branches = sorted(branch_cost_map.items(), key=lambda x: x[1]["sessions"], reverse=True)[
        :20
    ]

    branch_coaching = []
    for br, br_data in top_branches:
        cur.execute("""
            SELECT p.text FROM prompts p
            WHERE p.session_id IN (
                SELECT DISTINCT session_id FROM turns
                WHERE git_branch = ?
            )
        """, (br,))
        branch_prompts = [r[0] for r in cur.fetchall()]
        br_total = len(branch_prompts)
        br_corr = sum(
            1 for t in branch_prompts if _CORRECTION_RE.match(t.strip())
        )
        branch_coaching.append({
            "branch": br,
            "project": branch_project_map.get(br, "unknown"),
            "sessions": br_data["sessions"],
            "prompts": br_total,
            "correction_rate": round(br_corr / max(br_total, 1) * 100, 1),
            "est_cost": round(br_data["cost"], 2),
        })

    result = {
        "generated_at": datetime.now().isoformat(),
        "schema_version": 6,
        "user_label": user_label,
        "overview": {
            "total_prompts": total_prompts,
            "total_sessions": total_sessions,
            "total_projects": total_projects,
            "total_tokens": total_tokens,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cache_tokens": total_cache_create + total_cache_read,
            "avg_prompt_length_chars": avg_prompt_length,
            "cache_hit_rate_pct": cache_hit_rate,
            "estimated_cost_usd": round(total_estimated_cost, 2),
            "total_turns": total_turns,
            "subagent_turns": subagent_turns,
        },
        "efficiency_score": {
            "overall": overall_score.overall,
            "grade": overall_score.grade,
            "trend": overall_score.trend,
            "trend_delta": overall_score.trend_delta,
            "dimensions": [
                {
                    "name": d.name,
                    "score": d.score,
                    "grade": d.grade,
                    "weight": d.weight,
                    "explanation": d.explanation,
                    "recommendations": d.recommendations,
                }
                for d in overall_score.dimensions
            ],
            "top_recommendations": overall_score.top_recommendations,
        },
        "project_scores": [
            {
                "project": ps.project,
                "score": ps.score.overall,
                "grade": ps.score.grade,
                "prompts": ps.prompt_count,
                "tokens": ps.token_count,
                "sessions": ps.session_count,
            }
            for ps in project_scores
        ],
        # Daily-granularity data for client-side date-range filtering
        "daily_usage": daily_usage,
        "daily_tokens": daily_tokens,
        "daily_cost": daily_cost,
        "daily_project": daily_project,
        "daily_project_tokens": daily_project_tokens,
        "daily_tools": daily_tools,
        "daily_models": daily_models,
        "prompt_lengths": prompt_lengths,
        # Pre-aggregated (for reference)
        "model_totals": model_totals,
        "hourly_distribution": hourly_distribution,
        "day_of_week_distribution": day_of_week_distribution,
        "branch_usage": branch_usage,
        # Journey data
        "session_summaries": session_summaries,
        "heatmap_data": heatmap_data,
        "session_depth_dist": session_depth_dist,
        "daily_iteration": daily_iteration,
        "weekly_summaries": weekly_summaries,
        "usage_streak": streak,
        # Insights data (Features 2-9)
        "daily_stop_reasons": daily_stop_reasons,
        "stop_reason_totals": stop_reason_totals,
        "daily_agentic": daily_agentic,
        "agentic_cost_split": agentic_cost_split,
        "project_cost_efficiency": project_cost_efficiency,
        "correction_cost": correction_cost_data,
        "prompt_pattern_stats": prompt_pattern_stats,
        # Data-driven insights
        "session_insights": session_insights,
        "weekly_digest": weekly_digest,
        "prompt_learning": prompt_learning,
        "hourly_correction_rates": hourly_correction_rates,
        "expensive_sessions": expensive_sessions,
        "branch_coaching": branch_coaching,
        # Advanced usage analytics
        "advanced_usage": _build_advanced_usage(cur),
        # Security analysis
        "security": _build_security_analysis(cur, claude_dir=claude_dir),
    }

    # --- Features 1/6/10: Git-correlated session outcomes (opt-in) ---
    if git_correlation:
        from .git_utils import classify_session, get_available_repos, get_session_commits

        # Get all distinct cwds from turns
        cur.execute(
            "SELECT DISTINCT cwd FROM turns WHERE cwd IS NOT NULL AND cwd != ''"
        )
        all_cwds = [r[0] for r in cur.fetchall()]
        available_repos = get_available_repos(all_cwds)
        repo_set = set(available_repos)

        # For each session, get commits and classify
        session_outcomes: list[dict] = []
        time_to_value: list[dict] = []
        outcome_counts = {"productive": 0, "exploratory": 0, "abandoned": 0}

        for s in session_summaries:
            sid = s["id"]
            started = s.get("started")
            turns = s.get("turns", 0)
            if not started:
                continue

            # Find the cwd for this session (most common cwd in turns)
            cur.execute(
                "SELECT cwd, COUNT(*) FROM turns "
                "WHERE session_id = ? AND cwd IS NOT NULL AND cwd != '' "
                "GROUP BY cwd ORDER BY 2 DESC LIMIT 1",
                (sid,),
            )
            cwd_row = cur.fetchone()
            if not cwd_row:
                outcome = classify_session(0, turns)
                outcome_counts[outcome] += 1
                session_outcomes.append({
                    "id": sid, "outcome": outcome,
                    "commits": 0, "has_git": False,
                })
                continue

            session_cwd = cwd_row[0]
            # Check if we have a git repo for this cwd
            from pathlib import Path as _Path

            has_git = False
            for parent in [_Path(session_cwd), *list(_Path(session_cwd).parents)]:
                if str(parent) in repo_set:
                    has_git = True
                    session_cwd = str(parent)
                    break

            if not has_git:
                outcome = classify_session(0, turns)
                outcome_counts[outcome] += 1
                session_outcomes.append({
                    "id": sid, "outcome": outcome,
                    "commits": 0, "has_git": False,
                })
                continue

            # Get last turn timestamp for session end
            cur.execute(
                "SELECT MAX(timestamp) FROM turns "
                "WHERE session_id = ? AND timestamp IS NOT NULL",
                (sid,),
            )
            end_row = cur.fetchone()
            session_end = end_row[0] if end_row else None

            commits = get_session_commits(
                session_cwd, started, session_end,
            )
            outcome = classify_session(len(commits), turns)
            outcome_counts[outcome] += 1
            session_outcomes.append({
                "id": sid, "outcome": outcome,
                "commits": len(commits), "has_git": True,
            })

            # Time-to-value: time from session start to first commit
            if commits:
                try:
                    start_dt = datetime.fromisoformat(
                        started.replace("Z", "+00:00")
                    )
                    # Commits are most-recent-first, so last = earliest
                    first_commit_ts = commits[-1]["timestamp"]
                    commit_dt = datetime.fromisoformat(first_commit_ts)
                    # Ensure both are offset-aware or both naive
                    if start_dt.tzinfo and not commit_dt.tzinfo:
                        from datetime import timezone

                        commit_dt = commit_dt.replace(tzinfo=timezone.utc)
                    elif commit_dt.tzinfo and not start_dt.tzinfo:
                        from datetime import timezone

                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    delta_min = (commit_dt - start_dt).total_seconds() / 60
                    if delta_min >= 0:
                        time_to_value.append({
                            "id": sid,
                            "minutes": round(delta_min, 1),
                        })
                except (ValueError, TypeError):
                    pass

        result["session_outcomes"] = session_outcomes
        result["outcome_counts"] = outcome_counts
        result["time_to_value"] = time_to_value
        result["git_repos_available"] = len(available_repos)
        result["git_repos_total"] = total_projects

    if scrub:
        # Remove anything that could identify the user, their projects, or branches
        result.pop("prompt_lengths", None)
        result.pop("daily_iteration", None)
        result.pop("branch_usage", None)
        result.pop("branch_coaching", None)
        result.pop("session_summaries", None)
        result.pop("expensive_sessions", None)
        result.pop("prompt_learning", None)
        result.pop("session_outcomes", None)
        result.pop("time_to_value", None)

        # Strip project names from per-project data (keep aggregated metrics)
        for entry in result.get("daily_project", []):
            entry["pj"] = "project"
        for entry in result.get("daily_project_tokens", []):
            entry["pj"] = "project"
        for ps in result.get("project_scores", []):
            ps["project"] = "project"
        for pce in result.get("project_cost_efficiency", []):
            pce["pj"] = "project"

        # Redact security findings (keep risk_score and category_counts only)
        sec = result.get("security", {})
        sec.pop("findings", None)
        sec.pop("settings_findings", None)
        sec.pop("daily", None)

    return result
