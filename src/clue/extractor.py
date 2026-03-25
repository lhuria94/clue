"""Extract telemetry data from ~/.claude/ local files.

Supports both full and incremental extraction via file-level watermarks.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .models import ConversationTurn, Prompt, Session, TokenUsage

logger = logging.getLogger(__name__)

DEFAULT_CLAUDE_DIR = Path.home() / ".claude"


def _ts_to_dt(ts: int | float) -> datetime:
    """Convert millisecond epoch to datetime."""
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)


def _short_project(path: str) -> str:
    """Extract a human-readable project name from a full path.

    Cross-platform: handles both Unix and Windows paths.
    """
    if not path:
        return "unknown"
    # Normalise separators for cross-platform
    normalised = path.replace("\\", "/")
    parts = [p for p in normalised.split("/") if p]
    return parts[-1] if parts else "unknown"


def _project_from_dir_name(dir_name: str) -> str:
    """Decode Claude's encoded directory name to the actual project name.

    Claude encodes ``/Users/alice/workspace/my-app`` as
    ``-Users-alice-workspace-my-app`` (``/`` → ``-``).  The
    encoding is ambiguous because ``-`` appears both as the path
    separator and within directory names.

    We resolve by walking the real filesystem: at each level try
    progressively longer dash-joined (and dot-joined) segments until a
    matching directory is found, then recurse.

    Double-dash (``--``) encodes a dot-prefixed hidden directory.

    Falls back to the last segment when the path no longer exists.
    """
    if not dir_name or not dir_name.startswith("-"):
        return dir_name

    raw = dir_name.split("-")
    parts: list[str] = []
    i = 1  # skip leading ''
    while i < len(raw):
        if raw[i] == "" and i + 1 < len(raw):
            parts.append("." + raw[i + 1])
            i += 2
        elif raw[i] == "":
            i += 1
        else:
            parts.append(raw[i])
            i += 1

    if not parts:
        return dir_name

    def _walk(base: Path, idx: int) -> str | None:
        if idx >= len(parts):
            return base.name
        remaining = len(parts) - idx
        for length in range(remaining, 0, -1):
            segment = "-".join(parts[idx : idx + length])
            if (base / segment).is_dir():
                result = _walk(base / segment, idx + length)
                if result is not None:
                    return result
            if length >= 2:
                segment_dot = ".".join(parts[idx : idx + length])
                if (base / segment_dot).is_dir():
                    result = _walk(base / segment_dot, idx + length)
                    if result is not None:
                        return result
        return None

    result = _walk(Path("/"), 0)
    if result:
        return result
    return parts[-1]


def file_mtime(path: Path) -> float:
    """Get file modification time, 0.0 if not accessible."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def count_lines(path: Path) -> int:
    """Count lines in a file without reading entire content into memory."""
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# --- Prompt extraction ---


def extract_prompts(
    claude_dir: Path = DEFAULT_CLAUDE_DIR,
    since_line: int = 0,
) -> list[Prompt]:
    """Parse history.jsonl into Prompt objects.

    Args:
        claude_dir: Path to .claude directory.
        since_line: Skip this many lines (for incremental extraction).
    """
    history_file = claude_dir / "history.jsonl"
    if not history_file.exists():
        logger.warning("No history.jsonl found at %s", history_file)
        return []

    prompts = []
    with open(history_file, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i < since_line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                text = data.get("display", "")
                prompts.append(
                    Prompt(
                        timestamp=_ts_to_dt(data["timestamp"]),
                        project=_short_project(data.get("project", "")),
                        session_id=data.get("sessionId", ""),
                        text=text,
                        char_length=len(text),
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Skipping malformed history line %d: %s", i, exc)
    return prompts


# --- Conversation extraction ---


def _parse_conversation_file(
    path: Path,
    project: str,
    is_subagent: bool = False,
) -> list[ConversationTurn]:
    """Parse a single conversation JSONL file with all available fields.

    Claude Code streams responses as multiple JSONL entries per API call —
    one per content block (thinking, text, tool_use).  All entries from the
    same API call share the same ``message.id`` + ``requestId`` pair.
    Token usage is cumulative: the last entry per API call carries the full
    totals.  We deduplicate by collecting all entries, grouping by API-call
    hash, and emitting one turn per unique hash with the final usage.
    """
    turns: list[ConversationTurn] = []
    session_id = path.stem

    # First pass: collect raw entries, grouping assistant messages by API-call
    # hash so we can deduplicate streaming chunks.
    user_entries: list[dict] = []
    # api_hash → list of (data, msg) in file order
    assistant_groups: dict[str, list[tuple[dict, dict]]] = {}
    # For assistant entries without a hash (shouldn't happen, but be safe)
    assistant_no_hash: list[tuple[dict, dict]] = []

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = data.get("message", {})
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                if role == "user":
                    user_entries.append(data)
                else:
                    msg_id = msg.get("id")
                    req_id = data.get("requestId")
                    if msg_id and req_id:
                        key = f"{msg_id}:{req_id}"
                        assistant_groups.setdefault(key, []).append((data, msg))
                    else:
                        assistant_no_hash.append((data, msg))

    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return turns

    zero_usage = TokenUsage(0, 0, 0, 0)

    # Emit user turns (no dedup needed — user messages don't carry token usage)
    for data in user_entries:
        msg = data["message"]
        content = msg.get("content", [])
        text_len = 0
        if isinstance(content, str):
            text_len = len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_len += len(block.get("text", ""))
        turns.append(ConversationTurn(
            session_id=session_id,
            project=project,
            role="user",
            timestamp=data.get("timestamp"),
            model=msg.get("model"),
            usage=zero_usage,
            text_length=text_len,
            is_subagent=is_subagent,
            cwd=data.get("cwd"),
            git_branch=data.get("gitBranch"),
            claude_version=data.get("version"),
            stop_reason=msg.get("stop_reason"),
        ))

    # Emit one turn per unique API call (deduplicated assistant messages).
    # We merge all content blocks from the group to capture every tool name,
    # and take the usage from the last entry (the cumulative total).
    all_assistant = list(assistant_groups.values()) + [[e] for e in assistant_no_hash]
    for group in all_assistant:
        # Last entry has cumulative token usage
        last_data, last_msg = group[-1]

        # Collect tool names, inputs, and text across all content blocks
        tool_entries: list[tuple[str, dict]] = []  # (name, input)
        text_len = 0
        for data, msg in group:
            content = msg.get("content", [])
            if isinstance(content, str):
                text_len += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_entries.append((
                                block.get("name", "unknown"),
                                block.get("input") or {},
                            ))
                        elif block.get("type") == "text":
                            text_len += len(block.get("text", ""))

        usage_raw = last_msg.get("usage", {})
        if not isinstance(usage_raw, dict):
            usage_raw = {}
        usage = TokenUsage(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
            cache_creation_tokens=usage_raw.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage_raw.get("cache_read_input_tokens", 0),
        )

        # Use metadata from last entry (most complete)
        stop_reason = last_msg.get("stop_reason")
        # Fall back through group for stop_reason if last doesn't have it
        if not stop_reason:
            for _, m in reversed(group):
                if m.get("stop_reason"):
                    stop_reason = m["stop_reason"]
                    break

        base_kwargs = dict(
            session_id=session_id,
            project=project,
            role="assistant",
            timestamp=last_data.get("timestamp"),
            model=last_msg.get("model"),
            text_length=text_len,
            is_subagent=is_subagent,
            cwd=last_data.get("cwd"),
            git_branch=last_data.get("gitBranch"),
            claude_version=last_data.get("version"),
            stop_reason=stop_reason,
        )

        if tool_entries:
            # Attribute token usage to the first tool turn only
            for i, (tool, tool_input) in enumerate(tool_entries):
                # Extract advanced usage metadata from tool input
                subagent_type = None
                run_in_bg = False
                skill_name = None
                if tool == "Agent":
                    subagent_type = tool_input.get("subagent_type")
                    run_in_bg = bool(tool_input.get("run_in_background"))
                elif tool == "Skill":
                    skill_name = tool_input.get("skill")
                turns.append(ConversationTurn(
                    **base_kwargs,
                    usage=usage if i == 0 else zero_usage,
                    tool_name=tool,
                    tool_input_subagent_type=subagent_type,
                    tool_input_run_in_background=run_in_bg,
                    tool_input_skill=skill_name,
                ))
        else:
            turns.append(ConversationTurn(**base_kwargs, usage=usage))

    return turns


def extract_conversations(
    claude_dir: Path = DEFAULT_CLAUDE_DIR,
    changed_files: set[str] | None = None,
) -> list[ConversationTurn]:
    """Parse conversation JSONL files.

    Args:
        claude_dir: Path to .claude directory.
        changed_files: If provided, only parse these file paths (for incremental).
    """
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        return []

    all_turns: list[ConversationTurn] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        project = _project_from_dir_name(project_dir.name)

        for jsonl_file in project_dir.glob("*.jsonl"):
            if changed_files and str(jsonl_file) not in changed_files:
                continue
            turns = _parse_conversation_file(jsonl_file, project)
            all_turns.extend(turns)

        # Subagent conversations
        for session_dir in project_dir.iterdir():
            if not session_dir.is_dir():
                continue
            subagents_dir = session_dir / "subagents"
            if subagents_dir.exists():
                for jsonl_file in subagents_dir.glob("*.jsonl"):
                    if changed_files and str(jsonl_file) not in changed_files:
                        continue
                    turns = _parse_conversation_file(
                        jsonl_file,
                        project,
                        is_subagent=True,
                    )
                    all_turns.extend(turns)

    return all_turns


def find_changed_conversation_files(
    claude_dir: Path,
    get_wm: Callable[[str], tuple[float, int]],
    set_wm: Callable[[str, float, int], None],
) -> set[str]:
    """Find conversation files that changed since last extraction.

    Args:
        claude_dir: Path to .claude directory.
        get_wm: Callback to get watermark (returns (mtime, line_count)).
        set_wm: Callback to set watermark (key, mtime, line_count).

    Returns set of file paths that need re-parsing.
    """
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        return set()

    changed = set()

    def _check(path: Path) -> None:
        key = str(path)
        mtime = file_mtime(path)
        old_mtime, _ = get_wm(key)
        if mtime > old_mtime:
            changed.add(key)
            set_wm(key, mtime, count_lines(path))

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            _check(jsonl_file)
        for session_dir in project_dir.iterdir():
            if not session_dir.is_dir():
                continue
            subagents_dir = session_dir / "subagents"
            if subagents_dir.exists():
                for jsonl_file in subagents_dir.glob("*.jsonl"):
                    _check(jsonl_file)

    return changed


# --- Session building ---


def build_sessions(
    prompts: list[Prompt],
    turns: list[ConversationTurn],
) -> list[Session]:
    """Aggregate prompts and turns into Session summaries."""
    session_map: dict[str, Session] = {}

    for p in prompts:
        if p.session_id not in session_map:
            session_map[p.session_id] = Session(
                session_id=p.session_id,
                project=p.project,
                started_at=p.timestamp,
            )
        s = session_map[p.session_id]
        s.prompt_count += 1
        if s.started_at is None or p.timestamp < s.started_at:
            s.started_at = p.timestamp

    for t in turns:
        if t.session_id not in session_map:
            session_map[t.session_id] = Session(
                session_id=t.session_id,
                project=t.project,
            )
        s = session_map[t.session_id]
        s.turn_count += 1
        s.total_input_tokens += t.usage.input_tokens
        s.total_output_tokens += t.usage.output_tokens
        s.total_cache_creation_tokens += t.usage.cache_creation_tokens
        s.total_cache_read_tokens += t.usage.cache_read_tokens
        if t.model:
            s.models_used.add(t.model)
        if t.tool_name:
            s.tools_used[t.tool_name] = s.tools_used.get(t.tool_name, 0) + 1

    return list(session_map.values())
