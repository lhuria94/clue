"""Shared test fixtures for claude-usage tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from clue.db import init_db
from clue.models import ConversationTurn, Prompt, TokenUsage


@pytest.fixture
def tmp_dir(tmp_path):
    """Temporary directory for test data."""
    return tmp_path


@pytest.fixture
def db_conn(tmp_path):
    """Fresh SQLite connection with schema applied."""
    db_path = tmp_path / "test.db"
    conn, _ = init_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def mock_claude_dir(tmp_path):
    """Create a realistic ~/.claude/ directory structure with test data."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    # history.jsonl
    history = claude_dir / "history.jsonl"
    prompts = [
        {
            "display": "fix the login bug",
            "pastedContents": {},
            "timestamp": 1711000000000,
            "project": "/home/user/project-alpha",
            "sessionId": "session-001",
        },
        {
            "display": "yes",
            "pastedContents": {},
            "timestamp": 1711000060000,
            "project": "/home/user/project-alpha",
            "sessionId": "session-001",
        },
        {
            "display": "add pagination to the API endpoint for /users with cursor-based navigation",
            "pastedContents": {},
            "timestamp": 1711000120000,
            "project": "/home/user/project-alpha",
            "sessionId": "session-001",
        },
        {
            "display": "ok",
            "pastedContents": {},
            "timestamp": 1711003600000,
            "project": "/home/user/project-beta",
            "sessionId": "session-002",
        },
        {
            "display": (
                "refactor the auth middleware to use JWT tokens"
                " with proper rotation and refresh flow"
            ),
            "pastedContents": {},
            "timestamp": 1711007200000,
            "project": "/home/user/project-beta",
            "sessionId": "session-003",
        },
    ]
    history.write_text("\n".join(json.dumps(p) for p in prompts) + "\n")

    # sessions/
    sessions_dir = claude_dir / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "12345.json").write_text(
        json.dumps(
            {
                "pid": 12345,
                "sessionId": "session-001",
                "cwd": "/home/user/project-alpha",
                "startedAt": 1711000000000,
            }
        )
    )

    # projects/ with conversation files
    project_dir = claude_dir / "projects" / "-home-user-project-alpha"
    project_dir.mkdir(parents=True)

    conversation = [
        {
            "parentUuid": None,
            "isSidechain": False,
            "type": "user",
            "message": {"role": "user", "content": "fix the login bug"},
            "timestamp": "2025-03-21T10:00:00.000Z",
            "cwd": "/home/user/project-alpha",
            "gitBranch": "fix/auth-bug",
            "version": "2.1.75",
            "sessionId": "session-001",
            "uuid": "uuid-1",
        },
        {
            "parentUuid": "uuid-1",
            "isSidechain": False,
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {"type": "text", "text": "I'll fix the login bug."},
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "id": "tu-1",
                        "input": {"file_path": "/home/user/project-alpha/auth.py"},
                    },
                ],
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 1000,
                    "cache_read_input_tokens": 400,
                },
                "stop_reason": "tool_use",
            },
            "timestamp": "2025-03-21T10:00:01.000Z",
            "cwd": "/home/user/project-alpha",
            "gitBranch": "fix/auth-bug",
            "version": "2.1.75",
        },
        {
            "parentUuid": "uuid-1",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "id": "tu-2",
                        "input": {"file_path": "auth.py", "old_string": "x", "new_string": "y"},
                    },
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "id": "tu-3",
                        "input": {"command": "pytest"},
                    },
                ],
                "usage": {
                    "input_tokens": 800,
                    "output_tokens": 150,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 1200,
                },
                "stop_reason": "end_turn",
            },
            "timestamp": "2025-03-21T10:00:05.000Z",
        },
        # Advanced usage: Agent with subagent_type and run_in_background
        {
            "parentUuid": "uuid-1",
            "type": "assistant",
            "message": {
                "id": "msg-adv1",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Agent",
                        "id": "tu-4",
                        "input": {
                            "description": "research auth patterns",
                            "prompt": "Find auth patterns",
                            "subagent_type": "researcher",
                            "run_in_background": True,
                        },
                    },
                ],
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 100,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "stop_reason": "tool_use",
            },
            "requestId": "req-adv1",
            "timestamp": "2025-03-21T10:00:06.000Z",
        },
        # Advanced usage: Skill invocation
        {
            "parentUuid": "uuid-1",
            "type": "assistant",
            "message": {
                "id": "msg-adv2",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Skill",
                        "id": "tu-5",
                        "input": {"skill": "commit"},
                    },
                ],
                "usage": {
                    "input_tokens": 150,
                    "output_tokens": 80,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "stop_reason": "tool_use",
            },
            "requestId": "req-adv2",
            "timestamp": "2025-03-21T10:00:07.000Z",
        },
    ]
    conv_file = project_dir / "session-001.jsonl"
    conv_file.write_text("\n".join(json.dumps(c) for c in conversation) + "\n")

    # Subagent conversation
    subagent_dir = project_dir / "session-001" / "subagents"
    subagent_dir.mkdir(parents=True)
    subagent_conv = [
        {
            "type": "user",
            "message": {"role": "user", "content": "review this code"},
            "timestamp": "2025-03-21T10:00:02.000Z",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-haiku-4-5-20251001",
                "content": [{"type": "text", "text": "The code looks good."}],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "stop_reason": "end_turn",
            },
            "timestamp": "2025-03-21T10:00:03.000Z",
        },
    ]
    subagent_file = subagent_dir / "agent-a123.jsonl"
    subagent_file.write_text("\n".join(json.dumps(c) for c in subagent_conv) + "\n")

    # Second project
    project_dir_2 = claude_dir / "projects" / "-home-user-project-beta"
    project_dir_2.mkdir(parents=True)
    conv2 = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [{"type": "text", "text": "Architecture analysis complete."}],
                "usage": {
                    "input_tokens": 2000,
                    "output_tokens": 1500,
                    "cache_creation_input_tokens": 5000,
                    "cache_read_input_tokens": 3000,
                },
                "stop_reason": "end_turn",
            },
            "timestamp": "2025-03-21T11:00:00.000Z",
        },
    ]
    (project_dir_2 / "session-003.jsonl").write_text(
        "\n".join(json.dumps(c) for c in conv2) + "\n",
    )

    return claude_dir


@pytest.fixture
def sample_prompts():
    """Sample Prompt objects for testing."""
    return [
        Prompt(
            timestamp=datetime(2025, 3, 21, 10, 0, tzinfo=timezone.utc),
            project="project-alpha",
            session_id="session-001",
            text="fix the login bug",
            char_length=17,
        ),
        Prompt(
            timestamp=datetime(2025, 3, 21, 10, 1, tzinfo=timezone.utc),
            project="project-alpha",
            session_id="session-001",
            text="yes",
            char_length=3,
        ),
        Prompt(
            timestamp=datetime(2025, 3, 21, 10, 2, tzinfo=timezone.utc),
            project="project-alpha",
            session_id="session-001",
            text="add pagination to the API endpoint for /users with cursor-based navigation",
            char_length=75,
        ),
    ]


@pytest.fixture
def sample_turns():
    """Sample ConversationTurn objects for testing."""
    return [
        ConversationTurn(
            session_id="session-001",
            project="project-alpha",
            role="assistant",
            model="claude-sonnet-4-6",
            tool_name="Read",
            timestamp="2025-03-21T10:00:00.000Z",
            usage=TokenUsage(
                input_tokens=500,
                output_tokens=200,
                cache_creation_tokens=1000,
                cache_read_tokens=400,
            ),
        ),
        ConversationTurn(
            session_id="session-001",
            project="project-alpha",
            role="assistant",
            model="claude-sonnet-4-6",
            tool_name="Edit",
            timestamp="2025-03-21T10:01:00.000Z",
            usage=TokenUsage(
                input_tokens=800, output_tokens=150, cache_creation_tokens=0, cache_read_tokens=1200
            ),
        ),
        ConversationTurn(
            session_id="session-001",
            project="project-alpha",
            role="assistant",
            model="claude-sonnet-4-6",
            tool_name="Bash",
            timestamp="2025-03-21T10:02:00.000Z",
            usage=TokenUsage(
                input_tokens=300, output_tokens=100, cache_creation_tokens=0, cache_read_tokens=800
            ),
        ),
    ]
