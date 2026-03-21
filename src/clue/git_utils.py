"""Git log utilities for session-outcome correlation.

All functions return empty results on error (missing repo, not a git dir, timeout).
No exceptions propagate — callers always get safe defaults.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path


def get_available_repos(cwds: list[str]) -> list[str]:
    """Return repo root paths that exist locally and have a .git directory."""
    seen: set[str] = set()
    repos: list[str] = []
    for cwd in cwds:
        if not cwd:
            continue
        validated = _validate_cwd(cwd)
        if validated is None:
            continue
        path = validated
        for parent in [path, *list(path.parents)]:
            git_dir = parent / ".git"
            if git_dir.exists():
                root = str(parent)
                if root not in seen:
                    seen.add(root)
                    repos.append(root)
                break
    return repos


def _validate_cwd(cwd: str) -> Path | None:
    """Validate cwd is an existing directory. Returns Path or None."""
    try:
        p = Path(cwd).resolve()
        return p if p.is_dir() else None
    except (ValueError, OSError):
        return None


def get_commits_in_range(
    cwd: str,
    after: str,
    before: str,
    timeout: int = 10,
) -> list[dict]:
    """Get commits in a time range from a git repo.

    Returns list of {"sha": str, "timestamp": str, "message": str} dicts.
    Empty list on any error.
    """
    validated = _validate_cwd(cwd)
    if validated is None:
        return []
    try:
        result = subprocess.run(
            [
                "git", "-C", str(validated), "log",
                f"--after={after}",
                f"--before={before}",
                "--format=%H|%aI|%s",
                "--all",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "sha": parts[0],
                    "timestamp": parts[1],
                    "message": parts[2],
                })
        return commits
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def get_session_commits(
    cwd: str,
    session_start: str,
    session_end: str | None = None,
    buffer_minutes: int = 5,
) -> list[dict]:
    """Get commits that occurred during a session window.

    Uses session_start to session_end + buffer as the time window.
    If session_end is not provided, uses session_start + 2 hours.
    """
    try:
        start_dt = datetime.fromisoformat(session_start.replace("Z", "+00:00"))
        if session_end:
            end_dt = datetime.fromisoformat(session_end.replace("Z", "+00:00"))
        else:
            end_dt = start_dt + timedelta(hours=2)
        end_dt += timedelta(minutes=buffer_minutes)

        return get_commits_in_range(
            cwd,
            after=start_dt.isoformat(),
            before=end_dt.isoformat(),
        )
    except (ValueError, TypeError):
        return []


def classify_session(
    commit_count: int,
    turn_count: int,
) -> str:
    """Classify a session outcome based on commit and turn counts.

    Returns: "productive", "exploratory", or "abandoned".
    """
    if commit_count > 0:
        return "productive"
    if turn_count > 5:
        return "exploratory"
    return "abandoned"
