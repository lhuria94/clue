"""Generate a mock SQLite database with realistic but fake data for screenshots."""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clue.db import init_db, insert_prompts, insert_sessions, insert_turns
from clue.models import ConversationTurn, Prompt, Session, TokenUsage

MOCK_DB = Path(__file__).resolve().parent.parent / "mock_clue.db"

# Fake project names — generic open-source style
PROJECTS = [
    "aurora-api",
    "nebula-frontend",
    "atlas-infra",
    "pulse-analytics",
    "forge-cli",
    "horizon-mobile",
    "cascade-pipeline",
    "prism-design-system",
]

MODELS = ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"]
MODEL_WEIGHTS = [0.80, 0.10, 0.10]

TOOLS = [
    "Read", "Edit", "Write", "Bash", "Grep", "Glob",
    "Agent", "WebSearch", "WebFetch", "NotebookEdit",
    "AskFollowup", "TodoRead", "TodoWrite",
]

STOP_REASONS = ["end_turn", "tool_use", "stop_sequence", "max_tokens"]
STOP_WEIGHTS = [0.45, 0.40, 0.10, 0.05]

GIT_BRANCHES = [
    "main", "feat/user-auth", "fix/token-refresh", "chore/deps-upgrade",
    "feat/dashboard-v2", "fix/cache-invalidation", "refactor/api-layer",
]

PROMPT_TEMPLATES = [
    "fix the {} bug in {}",
    "add {} support to {}",
    "refactor the {} module",
    "write tests for {}",
    "update the {} configuration",
    "explain how {} works",
    "review the {} implementation",
    "/commit",
    "/test {}",
    "why is {} failing?",
    "optimise the {} query",
    "add error handling to {}",
    "implement {} endpoint",
    "migrate {} to the new API",
    "debug the {} issue in production logs",
]

NOUNS = [
    "login", "auth", "cache", "database", "API", "webhook",
    "pagination", "search", "notification", "upload", "export",
    "import", "validation", "rate-limit", "retry", "timeout",
]

random.seed(42)

START_DATE = datetime(2025, 10, 1, tzinfo=timezone.utc)
END_DATE = datetime(2026, 3, 20, tzinfo=timezone.utc)
DAYS = (END_DATE - START_DATE).days


def random_prompt_text() -> str:
    template = random.choice(PROMPT_TEMPLATES)
    count = template.count("{}")
    nouns = random.sample(NOUNS, min(count, len(NOUNS)))
    for noun in nouns:
        template = template.replace("{}", noun, 1)
    return template


def generate() -> None:
    if MOCK_DB.exists():
        MOCK_DB.unlink()

    conn = init_db(MOCK_DB)

    prompts: list[Prompt] = []
    turns: list[ConversationTurn] = []
    sessions_map: dict[str, dict] = {}

    session_counter = 0

    for day_offset in range(DAYS):
        day = START_DATE + timedelta(days=day_offset)
        weekday = day.weekday()

        # Fewer sessions on weekends
        if weekday >= 5:
            num_sessions = random.randint(0, 3)
        else:
            num_sessions = random.randint(2, 8)

        for _ in range(num_sessions):
            session_counter += 1
            session_id = f"sess-{session_counter:05d}"
            project = random.choice(PROJECTS)
            model = random.choices(MODELS, MODEL_WEIGHTS)[0]
            branch = random.choice(GIT_BRANCHES)
            hour = random.randint(7, 22)
            minute = random.randint(0, 59)
            session_start = day.replace(hour=hour, minute=minute)

            num_prompts = random.randint(1, 15)
            is_subagent = random.random() < 0.15

            total_input = 0
            total_output = 0
            turn_count = 0

            for p_idx in range(num_prompts):
                ts = session_start + timedelta(minutes=p_idx * random.randint(1, 5))
                text = random_prompt_text()

                prompts.append(Prompt(
                    timestamp=ts,
                    project=project,
                    session_id=session_id,
                    text=text,
                    char_length=len(text),
                ))

                # Each prompt generates 1-3 turns
                num_turns = random.randint(1, 3)
                for t_idx in range(num_turns):
                    turn_ts = ts + timedelta(seconds=t_idx * 10)
                    input_tok = random.randint(200, 8000)
                    output_tok = random.randint(100, 4000)
                    cache_read = random.randint(0, int(input_tok * 0.8))
                    cache_write = random.randint(0, int(input_tok * 0.2))

                    tool = random.choice(TOOLS) if random.random() < 0.7 else None
                    stop = random.choices(STOP_REASONS, STOP_WEIGHTS)[0]

                    total_input += input_tok
                    total_output += output_tok
                    turn_count += 1

                    turns.append(ConversationTurn(
                        session_id=session_id,
                        project=project,
                        role="assistant",
                        model=model,
                        tool_name=tool,
                        usage=TokenUsage(
                            input_tokens=input_tok,
                            output_tokens=output_tok,
                            cache_creation_tokens=cache_write,
                            cache_read_tokens=cache_read,
                        ),
                        timestamp=turn_ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        cwd=f"/Users/demo/workspace/{project}",
                        git_branch=branch,
                        stop_reason=stop,
                        is_subagent=is_subagent,
                    ))

            sessions_map[session_id] = {
                "session_id": session_id,
                "project": project,
                "started_at": session_start,
                "prompt_count": num_prompts,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "turn_count": turn_count,
            }

    # Batch insert
    insert_prompts(conn, prompts)
    insert_turns(conn, turns)
    insert_sessions(conn, [
        Session(**s) for s in sessions_map.values()
    ])

    conn.close()

    print(f"Mock DB created: {MOCK_DB}")
    print(f"  Prompts: {len(prompts)}")
    print(f"  Turns:   {len(turns)}")
    print(f"  Sessions: {len(sessions_map)}")
    print(f"  Days: {DAYS}")
    print(f"  Projects: {len(PROJECTS)}")


if __name__ == "__main__":
    generate()
