"""Extraction pipeline — shared by CLI and dashboard."""

from __future__ import annotations

from pathlib import Path

from .db import (
    clear_db,
    delete_turns_by_sessions,
    get_watermark,
    init_db,
    insert_prompts,
    insert_sessions,
    insert_turns,
    query_all_turns,
    set_watermark,
)
from .extractor import (
    _count_lines,
    _file_mtime,
    build_sessions,
    extract_conversations,
    extract_prompts,
    find_changed_conversation_files,
)


def run_extract(claude_dir: Path, db_path: Path, incremental: bool = False) -> dict:
    """Core extraction logic. Returns stats dict."""
    conn = init_db(db_path)

    if not incremental:
        clear_db(conn)

    # Prompts — incremental via line count watermark
    history_file = claude_dir / "history.jsonl"
    since_line = 0
    if incremental and history_file.exists():
        _, since_line = get_watermark(conn, str(history_file))

    prompts = extract_prompts(claude_dir, since_line=since_line)
    insert_prompts(conn, prompts)

    if history_file.exists():
        set_watermark(
            conn, str(history_file), _file_mtime(history_file), _count_lines(history_file)
        )

    # Conversations — incremental via file mtime watermarks
    if incremental:
        changed = find_changed_conversation_files(
            claude_dir,
            get_wm=lambda key: get_watermark(conn, key),
            set_wm=lambda key, mtime, lines: set_watermark(conn, key, mtime, lines),
        )
        turns = extract_conversations(claude_dir, changed_files=changed)
        # Delete old turns for affected sessions before re-inserting
        affected_sessions = {t.session_id for t in turns}
        delete_turns_by_sessions(conn, affected_sessions)
    else:
        turns = extract_conversations(claude_dir)

    insert_turns(conn, turns)

    # Sessions — rebuild from all prompts and all DB turns
    all_prompts = extract_prompts(claude_dir) if incremental else prompts
    # Query all turns from DB (not just the freshly-extracted subset)
    all_turns = query_all_turns(conn) if incremental else turns
    sessions = build_sessions(all_prompts, all_turns)
    insert_sessions(conn, sessions)

    conn.close()

    return {
        "prompts": len(prompts),
        "turns": len(turns),
        "sessions": len(sessions),
    }
