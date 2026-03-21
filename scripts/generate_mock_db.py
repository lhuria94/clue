"""Generate a mock SQLite database with realistic but fake data for screenshots."""

from __future__ import annotations

import random
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
MODEL_WEIGHTS = [0.65, 0.30, 0.05]  # Heavy Opus to trigger cost rec

# Tool distribution weighted to create realistic imperfections:
# Edit-heavy (more edits than reads), some Bash-for-reading
TOOLS = [
    "Read", "Edit", "Write", "Bash", "Grep", "Glob",
    "Agent", "WebSearch", "WebFetch", "NotebookEdit",
    "AskFollowup", "TodoRead", "TodoWrite",
]
TOOL_WEIGHTS = [
    0.12, 0.20, 0.08, 0.18, 0.10, 0.08,
    0.05, 0.03, 0.02, 0.02,
    0.05, 0.04, 0.03,
]

STOP_REASONS = ["end_turn", "tool_use", "stop_sequence", "max_tokens"]
STOP_WEIGHTS = [0.45, 0.40, 0.10, 0.05]

GIT_BRANCHES = [
    "main", "feat/user-auth", "fix/token-refresh", "chore/deps-upgrade",
    "feat/dashboard-v2", "fix/cache-invalidation", "refactor/api-layer",
]

FILES = [
    "src/auth/login.py", "src/api/routes.ts", "src/db/queries.sql",
    "src/services/notification.py", "src/cache/redis_client.py",
    "src/models/user.py", "src/middleware/rate_limit.py",
    "tests/test_auth.py", "src/api/webhooks.py", "src/utils/retry.py",
    "src/components/Dashboard.tsx", "src/hooks/useAuth.ts",
    "config/settings.yaml", "src/jobs/sync_worker.py",
]

NOUNS = [
    "login", "auth", "cache", "database", "API", "webhook",
    "pagination", "search", "notification", "upload", "export",
    "import", "validation", "rate-limit", "retry", "timeout",
]

# Short slash commands (~5-15 chars, ~10% of prompts)
SHORT_PROMPTS = [
    "/commit",
    "/test",
    "yes",
    "ok",
    "continue",
    "looks good",
    "/review",
    "no that's wrong, try again",
    "not what I meant, revert that",
    "fix it",
    "do it",
    "why?",
    "try again",
    "wrong file",
    "undo",
]

# Medium prompts with file refs (~50-200 chars, ~50% of prompts)
MEDIUM_TEMPLATES = [
    "fix the {noun} bug in {file} — it's returning 500 when the token expires",
    "add {noun} support to {file}, follow the same pattern as the existing handlers",
    "refactor {file} to use dependency injection instead of global state",
    "write unit tests for {file} covering the error paths and edge cases",
    "the {noun} in {file} is throwing a TypeError on line 42, can you investigate?",
    "update {file} to handle the new {noun} response format from the v2 API",
    "review {file} for security issues, especially around input validation",
    "explain how the {noun} flow works in {file}, I need to extend it",
    "add retry logic with exponential backoff to the {noun} client in {file}",
    "the {noun} query in {file} is slow — add an index or optimise the join",
    "implement rate limiting in {file} using a sliding window approach",
    "migrate the {noun} handler in {file} from callbacks to async/await",
]

# Detailed prompts (~200-500 chars, ~30% of prompts)
DETAILED_TEMPLATES = [
    (
        "I'm seeing intermittent failures in the {noun} service. The error is "
        "'connection reset by peer' in {file} around line 85. It happens under "
        "load when we have >100 concurrent requests. I think the connection pool "
        "is exhausted but I'm not sure. Can you investigate the pool config and "
        "add proper connection lifecycle management?"
    ),
    (
        "We need to add {noun} caching to {file}. Requirements: 1) cache TTL of "
        "5 minutes for list endpoints, 30 seconds for detail endpoints, 2) cache "
        "invalidation on writes, 3) use Redis with a fallback to in-memory for "
        "local dev. Follow the pattern we established in the auth module."
    ),
    (
        "The {noun} page is rendering slowly. Profile shows {file} is doing N+1 "
        "queries — one query per item in the list. Refactor to use a batch query "
        "with a JOIN. Make sure the existing tests still pass and add a test that "
        "asserts we only make 2 queries regardless of list size."
    ),
    (
        "I need to implement a new {noun} workflow. When a user triggers it from "
        "the dashboard, it should: 1) validate the input against the schema in "
        "{file}, 2) queue a background job, 3) send a webhook notification on "
        "completion, 4) update the status in real-time via SSE. Start with the "
        "validation and queueing — we can add the webhook in a follow-up."
    ),
    (
        "The {noun} feature has a race condition in {file}. Two concurrent "
        "requests can both pass the uniqueness check and create duplicate records. "
        "Add a database-level unique constraint and handle the IntegrityError "
        "gracefully by returning the existing record instead of a 500 error."
    ),
    (
        "Can you refactor the {noun} module? Currently {file} has 400 lines with "
        "mixed concerns — HTTP handling, business logic, and database queries all "
        "in one function. Split into: 1) a thin route handler, 2) a service layer "
        "for business logic, 3) a repository for data access. Move tests accordingly."
    ),
]

random.seed(42)

START_DATE = datetime(2025, 10, 1, tzinfo=timezone.utc)
END_DATE = datetime(2026, 3, 20, tzinfo=timezone.utc)
DAYS = (END_DATE - START_DATE).days


def random_prompt_text() -> str:
    """Generate a realistic prompt with varied lengths and patterns.

    Distribution mirrors real-world usage:
    - 25% short (slash commands, confirmations, corrections)
    - 40% medium (task with file reference)
    - 35% detailed (multi-sentence with context)
    """
    roll = random.random()
    if roll < 0.25:
        return random.choice(SHORT_PROMPTS)
    if roll < 0.65:
        template = random.choice(MEDIUM_TEMPLATES)
        return template.format(
            noun=random.choice(NOUNS),
            file=random.choice(FILES),
        )
    template = random.choice(DETAILED_TEMPLATES)
    return template.format(
        noun=random.choice(NOUNS),
        file=random.choice(FILES),
    )


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
        num_sessions = random.randint(0, 3) if weekday >= 5 else random.randint(2, 8)

        for _ in range(num_sessions):
            session_counter += 1
            session_id = f"sess-{session_counter:05d}"
            project = random.choice(PROJECTS)
            model = random.choices(MODELS, MODEL_WEIGHTS)[0]
            branch = random.choice(GIT_BRANCHES)
            hour = random.randint(7, 22)
            minute = random.randint(0, 59)
            session_start = day.replace(hour=hour, minute=minute)

            # Varied session depths: many shallow, some deep
            depth_roll = random.random()
            if depth_roll < 0.25:
                num_prompts = random.randint(1, 2)  # shallow
            elif depth_roll < 0.70:
                num_prompts = random.randint(3, 15)  # normal
            else:
                num_prompts = random.randint(16, 45)  # deep
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
                    input_tok = random.randint(2000, 15000)
                    output_tok = random.randint(100, 3000)
                    cache_read = random.randint(0, int(input_tok * 0.6))
                    cache_write = random.randint(0, int(input_tok * 0.4))

                    tool = (
                        random.choices(TOOLS, TOOL_WEIGHTS)[0]
                        if random.random() < 0.7
                        else None
                    )
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
