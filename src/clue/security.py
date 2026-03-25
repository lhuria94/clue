"""Security analysis for AI usage posture.

Scans prompts, settings, CLAUDE.md files, and AI responses for
security anti-patterns. Called by export.generate_dashboard_data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .patterns import (
    CLAUDE_MD_RISKS,
    DANGEROUS_CMD_RE,
    EXFILTRATION_RE,
    PLACEHOLDER_SECRET_RE,
    PROMPT_INJECTION_RE,
    SECRET_RE,
    SENSITIVE_FILE_RE,
)


def analyse_single_settings_file(
    settings_path: str, location_label: str,
) -> list[dict]:
    """Analyse one Claude settings file for security posture.

    Returns findings with a 'location' field showing where the issue was found.
    """
    path = Path(settings_path)
    findings: list[dict] = []

    if not path.exists():
        return findings

    try:
        settings = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
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


def analyse_claude_settings(claude_dir: str | None = None) -> list[dict]:
    """Analyse all Claude settings files for security posture.

    Checks three locations:
    - ~/.claude/settings.json (global)
    - <claude_dir>/settings.json (project — derived from claude_dir, not cwd)
    - <claude_dir>/settings.local.json (project local, gitignored)
    """
    findings: list[dict] = []

    # Global settings
    global_path = Path.home() / ".claude" / "settings.json"
    findings.extend(analyse_single_settings_file(
        str(global_path), "Global (~/.claude/settings.json)"))

    # Project-level settings — use claude_dir if provided, else cwd
    project_root = Path(claude_dir).parent if claude_dir else Path.cwd()
    project_path = project_root / ".claude" / "settings.json"
    if project_path.exists():
        findings.extend(analyse_single_settings_file(
            str(project_path), "Project (.claude/settings.json)"))

    project_local_path = project_root / ".claude" / "settings.local.json"
    if project_local_path.exists():
        findings.extend(analyse_single_settings_file(
            str(project_local_path), "Project Local (.claude/settings.local.json)"))

    return findings


def scan_claude_md_files(claude_dir: str | None) -> list[dict]:
    """Scan CLAUDE.md files for risky instructions.

    Checks project CLAUDE.md and any in ~/.claude/ for patterns that
    could weaken security posture (e.g. 'always use --no-verify').
    """
    findings: list[dict] = []

    # Locations to check
    candidates: list[tuple[str, str]] = []

    # Project-level CLAUDE.md (cwd)
    cwd_claude = Path.cwd() / "CLAUDE.md"
    if cwd_claude.exists():
        candidates.append((str(cwd_claude), "Project (CLAUDE.md)"))

    # Global CLAUDE.md
    if claude_dir:
        global_claude = Path(claude_dir) / "CLAUDE.md"
        if global_claude.exists():
            candidates.append((str(global_claude), f"Global ({global_claude.name})"))

    for path, location in candidates:
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:
            continue
        for pattern, category, detail in CLAUDE_MD_RISKS:
            if pattern.search(text):
                findings.append({
                    "category": category,
                    "severity": "high",
                    "detail": f"{detail} in {location}",
                    "location": location,
                })

    return findings


def scan_responses_for_secrets(claude_dir: str | None) -> list[dict]:
    """Scan assistant responses in conversation JSONL for leaked secrets.

    Reads conversation files and checks assistant text blocks for secrets
    that the AI may have generated or echoed back.
    Filters out common placeholder values to reduce false positives.
    """
    findings: list[dict] = []
    if not claude_dir:
        return findings

    projects_dir = Path(claude_dir) / "projects"
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
                entry = json.loads(line)
            except json.JSONDecodeError:
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
                match = SECRET_RE.search(text)
                if match and not PLACEHOLDER_SECRET_RE.search(match.group()):
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


def build_security_analysis(
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
    cur.execute("SELECT date, text FROM prompts ORDER BY date")
    for row in cur.fetchall():
        date, text = row[0], row[1]
        if SECRET_RE.search(text):
            _add("secrets_in_prompts", "high",
                 "Potential secret/credential detected in prompt text", date)
        if DANGEROUS_CMD_RE.search(text):
            _add("dangerous_commands", "high",
                 "Dangerous command pattern detected in prompt", date)
        if SENSITIVE_FILE_RE.search(text):
            _add("sensitive_file_refs", "medium",
                 "Reference to sensitive file in prompt", date)
        if PROMPT_INJECTION_RE.search(text):
            _add("prompt_injection", "critical",
                 "Prompt injection pattern detected — attempt to override AI instructions", date)
        if EXFILTRATION_RE.search(text):
            _add("data_exfiltration", "critical",
                 "Data exfiltration pattern — sending secrets to external service", date)

    # Hook bypass detection — --no-verify in prompts
    cur.execute("""
        SELECT date, COUNT(*) FROM prompts
        WHERE text LIKE '%--no-verify%'
        GROUP BY date
    """)
    for row in cur.fetchall():
        _add("hook_bypass", "high",
             f"{row[1]} prompt(s) requesting --no-verify", row[0])

    # Force push detection
    cur.execute("""
        SELECT date, COUNT(*) FROM prompts
        WHERE text LIKE '%force push%' OR text LIKE '%push --force%'
            OR text LIKE '%push -f%' OR text LIKE '%-f push%'
        GROUP BY date
    """)
    for row in cur.fetchall():
        _add("force_push", "medium",
             f"{row[1]} prompt(s) requesting force push", row[0])

    # Sandbox bypass
    cur.execute("""
        SELECT date, COUNT(*) FROM prompts
        WHERE text LIKE '%dangerouslyDisableSandbox%'
        GROUP BY date
    """)
    for row in cur.fetchall():
        _add("sandbox_bypass", "critical",
             f"{row[1]} prompt(s) requesting sandbox bypass", row[0])

    # Permission analysis — detect overly broad tool access patterns
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

    # Permission bypass flags in prompts
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

    # Excessive unreviewed tool usage per session — summarise, don't spam
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

    # Daily security signal counts for trend chart
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

    # Settings analysis — check ~/.claude/settings.json for broad permissions
    settings_findings = analyse_claude_settings()
    for sf in settings_findings:
        _add(sf["category"], sf["severity"], sf["detail"], None)

    # CLAUDE.md trust audit — scan for risky instructions
    claude_md_findings = scan_claude_md_files(claude_dir)
    for cf in claude_md_findings:
        _add(cf["category"], cf["severity"], cf["detail"], None)

    # Secrets in AI responses — scan conversation files
    response_findings = scan_responses_for_secrets(claude_dir)
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
