"""Seed a demo SQLite database with synthetic data for screenshots.

Usage:
    python scripts/seed_demo_db.py [output_path]

Creates a realistic-looking database with fictional project names,
branch names, and session data. Used to capture screenshots that
don't expose real personal data.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure clue package is importable
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from clue.db import init_db, insert_prompts, insert_sessions, insert_turns
from clue.models import ConversationTurn, Prompt, Session, TokenUsage

# ── Fictional data ──────────────────────────────────────────────

PROJECTS = [
    "acme-web-app",
    "acme-api-gateway",
    "acme-data-pipeline",
    "acme-mobile-app",
    "acme-auth-service",
    "acme-dashboard",
    "acme-cli-tools",
]

BRANCHES = [
    "feat/add-user-notifications",
    "fix/token-expiry-bug",
    "feat/pagination-api",
    "chore/upgrade-deps",
    "feat/search-endpoint",
    "fix/login-redirect",
    "refactor/auth-middleware",
    "feat/export-csv",
    "fix/memory-leak",
    "feat/dark-mode",
    "chore/ci-pipeline",
    "feat/webhook-integration",
    "fix/cache-invalidation",
    "feat/rate-limiting",
    "refactor/db-queries",
    "main",
]

MODELS = ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"]
MODEL_WEIGHTS = [0.75, 0.15, 0.10]

TOOLS = [
    "Read", "Edit", "Write", "Bash", "Grep", "Glob",
    "Agent", "Skill", "WebSearch", "WebFetch",
    "TaskCreate", "TaskUpdate", "TaskList",
    "NotebookEdit", "ToolSearch", "SendMessage",
]
TOOL_WEIGHTS = [
    25, 20, 8, 15, 10, 8,
    4, 3, 1, 1,
    1, 1, 0.5,
    0.5, 0.5, 0.5,
]

AGENT_TYPES = ["researcher", "reviewer", "debugger", "security-auditor", "Explore", "planner"]
SKILLS = ["commit", "review", "test", "plan", "verify"]

PROMPT_TEMPLATES = [
    "fix the {thing} bug in {file}",
    "add {feature} to the {component}",
    "refactor {component} to use {pattern}",
    "write tests for {file}",
    "update the {thing} configuration",
    "implement {feature} endpoint",
    "review the changes in {file}",
    "optimize the {thing} query",
    "add error handling to {component}",
    "deploy {component} to staging",
    "yes",
    "ok",
    "go ahead",
    "continue",
    "/commit",
    "/review",
    "no, use {pattern} instead",
    "actually, change {thing} to use {feature}",
    "look at src/{file} line 42",
    "check the {component}.ts file for the {thing} issue",
]

THINGS = ["auth", "cache", "login", "session", "token", "pagination", "rate-limit", "webhook"]
FEATURES = ["JWT rotation", "cursor-based pagination", "rate limiting", "search", "CSV export", "dark mode"]
COMPONENTS = ["middleware", "controller", "service", "gateway", "handler", "router"]
PATTERNS = ["dependency injection", "repository pattern", "event sourcing", "CQRS"]
FILES = ["auth.py", "users.ts", "api_gateway.go", "pipeline.rs", "config.yaml", "schema.sql"]

random.seed(42)  # Reproducible


def _random_prompt_text() -> str:
    template = random.choice(PROMPT_TEMPLATES)
    return template.format(
        thing=random.choice(THINGS),
        feature=random.choice(FEATURES),
        component=random.choice(COMPONENTS),
        pattern=random.choice(PATTERNS),
        file=random.choice(FILES),
    )


def _gen_usage(model: str, is_big: bool = False) -> TokenUsage:
    scale = 3 if is_big else 1
    base_in = random.randint(200, 2000) * scale
    base_out = random.randint(50, 800) * scale
    return TokenUsage(
        input_tokens=base_in,
        output_tokens=base_out,
        cache_creation_tokens=random.randint(0, base_in),
        cache_read_tokens=random.randint(0, base_in * 2),
    )


def seed(db_path: Path, claude_dir: Path | None = None) -> None:
    """Populate db_path with ~90 days of synthetic data."""
    conn = init_db(db_path)

    now = datetime(2025, 6, 25, 18, 0, tzinfo=timezone.utc)
    start = now - timedelta(days=90)

    all_prompts: list[Prompt] = []
    all_turns: list[ConversationTurn] = []
    all_sessions: list[Session] = []

    session_counter = 0
    day = start

    while day < now:
        # 2-6 sessions per day, fewer on weekends
        n_sessions = random.randint(1, 3) if day.weekday() >= 5 else random.randint(2, 6)

        for _ in range(n_sessions):
            session_counter += 1
            sid = f"demo-{session_counter:04d}"
            project = random.choice(PROJECTS)
            branch = random.choice(BRANCHES)
            model = random.choices(MODELS, weights=MODEL_WEIGHTS, k=1)[0]
            hour = random.choice([9, 10, 11, 13, 14, 15, 16, 17, 21, 22])
            session_start = day.replace(hour=hour, minute=random.randint(0, 59))

            # 3-25 prompts per session
            n_prompts = random.randint(3, 25)
            session_tools: dict[str, int] = {}
            session_in = session_out = session_cc = session_cr = 0

            for pi in range(n_prompts):
                ts = session_start + timedelta(minutes=pi * random.randint(1, 5))
                text = _random_prompt_text()

                all_prompts.append(Prompt(
                    timestamp=ts,
                    project=project,
                    session_id=sid,
                    text=text,
                    char_length=len(text),
                ))

                # 1-4 assistant turns per prompt
                n_turns = random.randint(1, 4)
                for ti in range(n_turns):
                    turn_ts = ts + timedelta(seconds=ti + 1)
                    tool = random.choices(TOOLS, weights=TOOL_WEIGHTS, k=1)[0]
                    turn_model = model if random.random() > 0.1 else random.choices(MODELS, weights=MODEL_WEIGHTS, k=1)[0]
                    usage = _gen_usage(turn_model, is_big=(pi == 0 and ti == 0))
                    stop = "tool_use" if ti < n_turns - 1 else random.choice(["end_turn", "tool_use", "stop_sequence"])

                    # Advanced usage fields
                    subagent_type = None
                    run_bg = False
                    skill = None
                    is_subagent = False

                    if tool == "Agent":
                        subagent_type = random.choice(AGENT_TYPES)
                        run_bg = random.random() > 0.6
                    elif tool == "Skill":
                        skill = random.choice(SKILLS)

                    # Some turns are subagent turns
                    if random.random() < 0.08:
                        is_subagent = True
                        turn_model = "claude-haiku-4-5-20251001"

                    session_tools[tool] = session_tools.get(tool, 0) + 1
                    session_in += usage.input_tokens
                    session_out += usage.output_tokens
                    session_cc += usage.cache_creation_tokens
                    session_cr += usage.cache_read_tokens

                    all_turns.append(ConversationTurn(
                        session_id=sid,
                        project=project,
                        role="assistant",
                        timestamp=turn_ts.isoformat(),
                        model=turn_model,
                        usage=usage,
                        tool_name=tool,
                        text_length=random.randint(20, 500),
                        is_subagent=is_subagent,
                        cwd=f"/home/dev/{project}",
                        git_branch=branch,
                        claude_version="2.1.80",
                        stop_reason=stop,
                        tool_input_subagent_type=subagent_type,
                        tool_input_run_in_background=run_bg,
                        tool_input_skill=skill,
                    ))

            all_sessions.append(Session(
                session_id=sid,
                project=project,
                started_at=session_start,
                prompt_count=n_prompts,
                total_input_tokens=session_in,
                total_output_tokens=session_out,
                total_cache_creation_tokens=session_cc,
                total_cache_read_tokens=session_cr,
                models_used={model},
                tools_used=session_tools,
                turn_count=sum(session_tools.values()),
            ))

        day += timedelta(days=1)

    insert_prompts(conn, all_prompts)
    insert_turns(conn, all_turns)
    insert_sessions(conn, all_sessions)
    conn.close()

    print(f"Seeded {db_path}")
    print(f"  Sessions: {len(all_sessions)}")
    print(f"  Prompts:  {len(all_prompts)}")
    print(f"  Turns:    {len(all_turns)}")

    # Create minimal .claude dir structure (empty — no real settings)
    if claude_dir:
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text("{}")
        print(f"  Claude dir: {claude_dir}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/clue-demo.db")
    demo_claude = out.parent / ".claude"
    seed(out, demo_claude)
