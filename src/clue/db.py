"""SQLite storage with schema migrations for extracted telemetry data."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from pathlib import Path

from .models import (
    MODEL_PRICING,
    ConversationTurn,
    Prompt,
    ScoringData,
    Session,
    SessionMetrics,
    TokenUsage,
    TrendData,
)
from .patterns import CORRECTION_RE as _CORRECTION_RE
from .patterns import FILE_REF_RE as _FILE_REF_RE

DEFAULT_DB_PATH = Path.home() / ".claude" / "usage.db"

SCHEMA_VERSION = 3

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS prompts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        date TEXT NOT NULL,
        hour INTEGER NOT NULL,
        day_of_week INTEGER NOT NULL,
        project TEXT NOT NULL,
        session_id TEXT NOT NULL,
        text TEXT NOT NULL,
        char_length INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        project TEXT NOT NULL,
        role TEXT NOT NULL,
        timestamp TEXT,
        model TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cache_creation_tokens INTEGER DEFAULT 0,
        cache_read_tokens INTEGER DEFAULT 0,
        tool_name TEXT,
        text_length INTEGER DEFAULT 0,
        is_subagent INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        project TEXT NOT NULL,
        started_at TEXT,
        prompt_count INTEGER DEFAULT 0,
        total_input_tokens INTEGER DEFAULT 0,
        total_output_tokens INTEGER DEFAULT 0,
        total_cache_creation_tokens INTEGER DEFAULT 0,
        total_cache_read_tokens INTEGER DEFAULT 0,
        models_used TEXT,
        tools_used TEXT,
        turn_count INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS watermarks (
        source TEXT PRIMARY KEY,
        last_modified REAL NOT NULL,
        last_line_count INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );

    CREATE INDEX IF NOT EXISTS idx_prompts_date ON prompts(date);
    CREATE INDEX IF NOT EXISTS idx_prompts_project ON prompts(project);
    CREATE INDEX IF NOT EXISTS idx_prompts_session ON prompts(session_id);
    CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
    CREATE INDEX IF NOT EXISTS idx_turns_project ON turns(project);
    CREATE INDEX IF NOT EXISTS idx_turns_model ON turns(model);
    CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);

    INSERT INTO schema_version (version) VALUES (1);
    """,
    2: """
    ALTER TABLE turns ADD COLUMN cwd TEXT;
    ALTER TABLE turns ADD COLUMN git_branch TEXT;
    ALTER TABLE turns ADD COLUMN claude_version TEXT;
    ALTER TABLE turns ADD COLUMN stop_reason TEXT;

    CREATE INDEX IF NOT EXISTS idx_turns_git_branch ON turns(git_branch);

    UPDATE schema_version SET version = 2;
    """,
    3: """
    ALTER TABLE turns ADD COLUMN tool_input_subagent_type TEXT;
    ALTER TABLE turns ADD COLUMN tool_input_run_in_background INTEGER DEFAULT 0;
    ALTER TABLE turns ADD COLUMN tool_input_skill TEXT;

    CREATE INDEX IF NOT EXISTS idx_turns_tool_input_subagent_type
        ON turns(tool_input_subagent_type);
    CREATE INDEX IF NOT EXISTS idx_turns_tool_input_skill
        ON turns(tool_input_skill);

    UPDATE schema_version SET version = 3;
    """,
}


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Get current schema version, 0 if fresh database."""
    try:
        cur = conn.execute("SELECT MAX(version) FROM schema_version")
        row = cur.fetchone()
        return row[0] if row and row[0] else 0
    except sqlite3.OperationalError:
        return 0


def init_db(
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[sqlite3.Connection, bool]:
    """Create or open the database and run pending migrations.

    Returns (connection, ran_migrations) so callers can decide whether
    a full re-extract is needed after a schema upgrade.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Set restrictive umask before creating DB to avoid TOCTOU permission window
    old_umask = os.umask(0o077)
    try:
        conn = sqlite3.connect(str(db_path))
    finally:
        os.umask(old_umask)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    current = _get_schema_version(conn)
    ran_migrations = False
    for version in sorted(MIGRATIONS.keys()):
        if version > current:
            conn.executescript(MIGRATIONS[version])
            ran_migrations = True

    # Restrict DB file and WAL journal files to owner-only access
    for suffix in ("", "-wal", "-shm"):
        wal_path = db_path.parent / (db_path.name + suffix)
        with contextlib.suppress(OSError):
            if wal_path.exists():
                os.chmod(wal_path, 0o600)

    return conn, ran_migrations


def clear_db(conn: sqlite3.Connection) -> None:
    """Drop all data (for full re-extract). Preserves schema."""
    conn.executescript("""
        DELETE FROM prompts;
        DELETE FROM turns;
        DELETE FROM sessions;
        DELETE FROM watermarks;
    """)
    conn.commit()


def get_watermark(conn: sqlite3.Connection, source: str) -> tuple[float, int]:
    """Get last-modified time and line count for a source file."""
    cur = conn.execute(
        "SELECT last_modified, last_line_count FROM watermarks WHERE source = ?",
        (source,),
    )
    row = cur.fetchone()
    return (row[0], row[1]) if row else (0.0, 0)


def set_watermark(conn: sqlite3.Connection, source: str, mtime: float, line_count: int) -> None:
    """Update watermark for a source file."""
    conn.execute(
        "INSERT OR REPLACE INTO watermarks (source, last_modified, last_line_count)"
        " VALUES (?, ?, ?)",
        (source, mtime, line_count),
    )
    conn.commit()


def insert_prompts(conn: sqlite3.Connection, prompts: list[Prompt]) -> int:
    """Insert prompt records. Returns count inserted."""
    if not prompts:
        return 0
    rows = [
        (
            p.timestamp.isoformat(),
            p.timestamp.strftime("%Y-%m-%d"),
            p.timestamp.hour,
            p.timestamp.weekday(),
            p.project,
            p.session_id,
            p.text,
            p.char_length,
        )
        for p in prompts
    ]
    conn.executemany(
        "INSERT INTO prompts"
        " (timestamp, date, hour, day_of_week, project, session_id, text, char_length)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def insert_turns(conn: sqlite3.Connection, turns: list[ConversationTurn]) -> int:
    """Insert conversation turn records."""
    if not turns:
        return 0
    rows = [
        (
            t.session_id,
            t.project,
            t.role,
            t.timestamp,
            t.model,
            t.usage.input_tokens,
            t.usage.output_tokens,
            t.usage.cache_creation_tokens,
            t.usage.cache_read_tokens,
            t.tool_name,
            t.text_length,
            1 if t.is_subagent else 0,
            t.cwd,
            t.git_branch,
            t.claude_version,
            t.stop_reason,
            t.tool_input_subagent_type,
            1 if t.tool_input_run_in_background else 0,
            t.tool_input_skill,
        )
        for t in turns
    ]
    conn.executemany(
        "INSERT INTO turns (session_id, project, role, timestamp, model, "
        "input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, "
        "tool_name, text_length, is_subagent, cwd, git_branch, claude_version, stop_reason, "
        "tool_input_subagent_type, tool_input_run_in_background, tool_input_skill) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def delete_turns_by_sessions(conn: sqlite3.Connection, session_ids: set[str]) -> int:
    """Delete turns for specific sessions (used before re-inserting on incremental runs)."""
    if not session_ids:
        return 0
    deleted = 0
    for sid in session_ids:
        cur = conn.execute("DELETE FROM turns WHERE session_id = ?", (sid,))
        deleted += cur.rowcount
    conn.commit()
    return deleted


def insert_sessions(conn: sqlite3.Connection, sessions: list[Session]) -> int:
    """Insert session summary records."""
    if not sessions:
        return 0
    rows = [
        (
            s.session_id,
            s.project,
            s.started_at.isoformat() if s.started_at else None,
            s.prompt_count,
            s.total_input_tokens,
            s.total_output_tokens,
            s.total_cache_creation_tokens,
            s.total_cache_read_tokens,
            json.dumps(sorted(s.models_used)),
            json.dumps(s.tools_used),
            s.turn_count,
        )
        for s in sessions
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO sessions (session_id, project, started_at, prompt_count, "
        "total_input_tokens, total_output_tokens, total_cache_creation_tokens, "
        "total_cache_read_tokens, models_used, tools_used, turn_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


# --- Query helpers ---


def _where(project: str | None) -> tuple[str, tuple]:
    """Build a parameterised WHERE clause scoped to a project."""
    if project:
        return "project = ?", (project,)
    return "1=1", ()


def query_scoring_data(conn: sqlite3.Connection, project: str | None = None) -> ScoringData:
    """Query all data needed by the scoring engine."""
    cur = conn.cursor()

    # Prompt lengths
    clause, params = _where(project)
    cur.execute(f"SELECT char_length FROM prompts WHERE {clause}", params)
    prompt_lengths = [r[0] for r in cur.fetchall()]

    # Token totals + session count
    clause, params = _where(project)
    cur.execute(
        f"""
        SELECT SUM(input_tokens), SUM(output_tokens),
               COUNT(DISTINCT session_id)
        FROM turns WHERE {clause}
    """,
        params,
    )
    row = cur.fetchone()
    total_input = row[0] or 0
    total_output = row[1] or 0
    session_count = row[2] or 0

    # Cache tokens
    cur.execute(
        f"""
        SELECT SUM(cache_creation_tokens), SUM(cache_read_tokens)
        FROM turns WHERE {clause}
    """,
        params,
    )
    row = cur.fetchone()
    cache_create = row[0] or 0
    cache_read = row[1] or 0

    # Tool counts
    cur.execute(
        f"""
        SELECT tool_name, COUNT(*) as uses
        FROM turns WHERE tool_name IS NOT NULL AND {clause}
        GROUP BY tool_name ORDER BY uses DESC
    """,
        params,
    )
    tool_counts = {r[0]: r[1] for r in cur.fetchall()}

    # Prompts per session
    clause, params = _where(project)
    cur.execute(
        f"""
        SELECT session_id, COUNT(*) as prompts
        FROM prompts WHERE {clause}
        GROUP BY session_id
    """,
        params,
    )
    prompts_per_session = [r[1] for r in cur.fetchall()]

    # Model usage
    clause, params = _where(project)
    cur.execute(
        f"""
        SELECT model, COUNT(*) as calls, SUM(output_tokens) as output_t
        FROM turns WHERE model IS NOT NULL AND {clause}
        GROUP BY model
    """,
        params,
    )
    model_calls: dict[str, int] = {}
    model_output_tokens: dict[str, int] = {}
    for r in cur.fetchall():
        model_calls[r[0]] = r[1]
        model_output_tokens[r[0]] = r[2] or 0

    # Prompt texts for semantic analysis
    clause, params = _where(project)
    cur.execute(f"SELECT text FROM prompts WHERE {clause}", params)
    prompt_texts = [r[0] for r in cur.fetchall()]

    # Turns per session (total turns including user + assistant)
    clause, params = _where(project)
    cur.execute(
        f"""
        SELECT session_id, COUNT(*) as turn_count
        FROM turns WHERE {clause}
        GROUP BY session_id
    """,
        params,
    )
    turns_per_session = [r[1] for r in cur.fetchall()]

    # Unique tools per session (tool diversity within sessions)
    cur.execute(
        f"""
        SELECT session_id, COUNT(DISTINCT tool_name) as tool_diversity
        FROM turns WHERE tool_name IS NOT NULL AND {clause}
        GROUP BY session_id
    """,
        params,
    )
    unique_tools_per_session = [r[1] for r in cur.fetchall()]

    # --- Per-session comparative metrics ---
    # Session-level: tools, tokens, corrections, read-before-edit
    clause, params = _where(project)
    cur.execute(
        f"""
        SELECT session_id, project,
            SUM(input_tokens + output_tokens) as total_tokens,
            COUNT(*) as turn_count,
            SUM(CASE WHEN tool_name = 'Read' THEN 1 ELSE 0 END) as reads,
            SUM(CASE WHEN tool_name IN ('Edit', 'Write') THEN 1 ELSE 0 END) as edits,
            COUNT(DISTINCT tool_name) as tool_div,
            SUM(CASE WHEN stop_reason = 'max_tokens' THEN 1 ELSE 0 END) as max_tok
        FROM turns WHERE {clause}
        GROUP BY session_id
    """,
        params,
    )
    session_turn_data = {r[0]: r for r in cur.fetchall()}

    # Per-session per-model token breakdown for accurate cost calculation
    cur.execute(
        f"""
        SELECT session_id, COALESCE(model, '_default'),
            SUM(input_tokens), SUM(output_tokens),
            SUM(cache_creation_tokens), SUM(cache_read_tokens)
        FROM turns WHERE {clause}
        GROUP BY session_id, COALESCE(model, '_default')
    """,
        params,
    )
    session_model_tokens: dict[str, list[tuple[str, int, int, int, int]]] = {}
    for r in cur.fetchall():
        session_model_tokens.setdefault(r[0], []).append(
            (r[1], r[2] or 0, r[3] or 0, r[4] or 0, r[5] or 0)
        )

    # Session-level prompt data: texts per session
    clause, params = _where(project)
    cur.execute(
        f"""
        SELECT session_id, text, char_length
        FROM prompts WHERE {clause}
        ORDER BY session_id, timestamp
    """,
        params,
    )
    session_prompts: dict[str, list[tuple[str, int]]] = {}
    for r in cur.fetchall():
        session_prompts.setdefault(r[0], []).append((r[1], r[2]))

    # Check read-before-edit per session (ordered tool sequence)
    clause, params = _where(project)
    cur.execute(
        f"""
        SELECT session_id, tool_name
        FROM turns
        WHERE tool_name IN ('Read', 'Edit', 'Write') AND {clause}
        ORDER BY session_id, id
    """,
        params,
    )
    session_tool_seq: dict[str, list[str]] = {}
    for r in cur.fetchall():
        session_tool_seq.setdefault(r[0], []).append(r[1])

    session_metrics: list[SessionMetrics] = []
    for sid, turn_row in session_turn_data.items():
        prompts_list = session_prompts.get(sid, [])
        texts = [p[0] for p in prompts_list]
        lengths = [p[1] for p in prompts_list]

        corr_count = sum(1 for t in texts if _CORRECTION_RE.match(t.strip()))
        file_refs = sum(1 for t in texts if _FILE_REF_RE.search(t))

        # Check read-before-edit sequence
        seq = session_tool_seq.get(sid, [])
        has_rbe = False
        if seq:
            first_edit_idx = next(
                (i for i, t in enumerate(seq) if t in ("Edit", "Write")), None
            )
            if first_edit_idx is not None and first_edit_idx > 0:
                has_rbe = any(seq[j] == "Read" for j in range(first_edit_idx))

        # Cost estimate (per-model to avoid MAX(model) inaccuracy)
        cost = 0.0
        model_token_groups = session_model_tokens.get(sid, [])
        for mdl, inp, outp, cc, cr in model_token_groups:
            pricing = MODEL_PRICING.get(mdl, MODEL_PRICING["_default"])
            cost += (
                (inp / 1_000_000) * pricing["input"]
                + (outp / 1_000_000) * pricing["output"]
                + (cc / 1_000_000) * pricing["cache_write"]
                + (cr / 1_000_000) * pricing["cache_read"]
            )
        # Dominant model = highest total tokens in this session
        dominant_model = (
            max(model_token_groups, key=lambda g: g[1] + g[2])[0]
            if model_token_groups else "_default"
        )

        session_metrics.append(SessionMetrics(
            session_id=sid,
            project=turn_row[1],
            prompt_count=len(prompts_list),
            turn_count=turn_row[3],
            total_tokens=turn_row[2] or 0,
            correction_count=corr_count,
            read_count=turn_row[4],
            edit_count=turn_row[5],
            has_read_before_edit=has_rbe,
            tool_diversity=turn_row[6],
            avg_prompt_length=sum(lengths) / len(lengths) if lengths else 0,
            file_ref_count=file_refs,
            cost=round(cost, 4),
            model=dominant_model,
            max_tokens_hits=turn_row[7],
        ))

    # Stop reason counts
    clause, params = _where(project)
    cur.execute(
        f"""
        SELECT stop_reason, COUNT(*)
        FROM turns WHERE stop_reason IS NOT NULL AND {clause}
        GROUP BY stop_reason
    """,
        params,
    )
    stop_reason_counts = {r[0]: r[1] for r in cur.fetchall()}

    # --- Advanced usage signals ---
    clause, params = _where(project)
    # Agent subagent type distribution
    cur.execute(
        f"""
        SELECT tool_input_subagent_type, COUNT(*)
        FROM turns
        WHERE tool_input_subagent_type IS NOT NULL AND {clause}
        GROUP BY tool_input_subagent_type
    """,
        params,
    )
    agent_type_counts = {r[0]: r[1] for r in cur.fetchall()}

    # Parallel invocations (Agent with run_in_background)
    cur.execute(
        f"""
        SELECT COUNT(*)
        FROM turns
        WHERE tool_input_run_in_background = 1 AND {clause}
    """,
        params,
    )
    parallel_invocations = cur.fetchone()[0] or 0

    # Skills used
    cur.execute(
        f"""
        SELECT tool_input_skill, COUNT(*)
        FROM turns
        WHERE tool_input_skill IS NOT NULL AND {clause}
        GROUP BY tool_input_skill
    """,
        params,
    )
    skills_used = {r[0]: r[1] for r in cur.fetchall()}

    # Task tool usage (TaskCreate, TaskUpdate, TaskList, TaskGet, TaskStop)
    cur.execute(
        f"""
        SELECT tool_name, COUNT(*)
        FROM turns
        WHERE tool_name LIKE 'Task%' AND {clause}
        GROUP BY tool_name
    """,
        params,
    )
    task_tool_counts = {r[0]: r[1] for r in cur.fetchall()}

    return ScoringData(
        prompt_lengths=prompt_lengths,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        session_count=session_count,
        cache_creation_tokens=cache_create,
        cache_read_tokens=cache_read,
        tool_counts=tool_counts,
        prompts_per_session=prompts_per_session,
        model_calls=model_calls,
        model_output_tokens=model_output_tokens,
        prompt_texts=prompt_texts,
        turns_per_session=turns_per_session,
        unique_tools_per_session=unique_tools_per_session,
        session_metrics=session_metrics,
        stop_reason_counts=stop_reason_counts,
        agent_type_counts=agent_type_counts,
        parallel_invocations=parallel_invocations,
        skills_used=skills_used,
        task_tool_counts=task_tool_counts,
    )


def query_trend_data(conn: sqlite3.Connection) -> TrendData:
    """Query data needed for trend computation."""
    cur = conn.cursor()

    cur.execute("SELECT MAX(date) FROM prompts")
    latest = cur.fetchone()[0]
    if not latest:
        return TrendData()

    cur.execute(
        "SELECT AVG(char_length) FROM prompts WHERE date > date(?, '-7 days')",
        (latest,),
    )
    recent_avg = cur.fetchone()[0] or 0

    cur.execute(
        "SELECT AVG(char_length) FROM prompts "
        "WHERE date <= date(?, '-7 days') AND date > date(?, '-14 days')",
        (latest, latest),
    )
    prior_avg = cur.fetchone()[0] or 0

    return TrendData(
        recent_avg_length=recent_avg,
        prior_avg_length=prior_avg,
        has_data=True,
    )


def query_all_projects(conn: sqlite3.Connection) -> list[str]:
    """Get all distinct project names."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT project FROM prompts
        UNION
        SELECT DISTINCT project FROM turns
    """)
    return sorted(r[0] for r in cur.fetchall())


def query_project_stats(conn: sqlite3.Connection, project: str) -> tuple[int, int, int]:
    """Get (prompt_count, token_count, session_count) for a project."""
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM prompts WHERE project = ?", (project,))
    prompt_count = cur.fetchone()[0]

    cur.execute(
        "SELECT SUM(input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens) "
        "FROM turns WHERE project = ?",
        (project,),
    )
    token_count = cur.fetchone()[0] or 0

    cur.execute(
        "SELECT COUNT(*) FROM sessions WHERE project = ? AND (prompt_count > 0 OR turn_count > 0)",
        (project,),
    )
    session_count = cur.fetchone()[0]

    return prompt_count, token_count, session_count


def query_all_turns(conn: sqlite3.Connection) -> list[ConversationTurn]:
    """Query all turns from the database as ConversationTurn objects."""
    cur = conn.cursor()
    cur.execute(
        "SELECT session_id, project, role, model, tool_name, "
        "input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, "
        "timestamp FROM turns"
    )
    return [
        ConversationTurn(
            session_id=r[0],
            project=r[1],
            role=r[2],
            model=r[3],
            tool_name=r[4],
            usage=TokenUsage(
                input_tokens=r[5],
                output_tokens=r[6],
                cache_creation_tokens=r[7],
                cache_read_tokens=r[8],
            ),
            timestamp=r[9],
        )
        for r in cur.fetchall()
    ]
