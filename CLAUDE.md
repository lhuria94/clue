# Clue — AI Efficiency Index for Engineering Teams

## Quick Reference

```bash
task test               # Run 186 tests with 87% coverage ratchet
task lint               # Ruff lint
task lint-imports       # Import-linter architecture check
task check              # All three above
task start              # Launch Streamlit dashboard (default port 8484, PORT=8486 task start)
```

Without Taskfile: `.venv/bin/pytest tests/ -v`

## Package

- Name: `clue` — AI Efficiency Index for Engineering Teams
- Entry point: `python -m clue` or `clue` CLI
- Source: `src/clue/`
- Tests: `tests/`

## Architecture

```
patterns.py    ← Shared regex patterns (no internal imports)
models.py      ← Pure domain (dataclasses, no imports from clue)
scorer.py      ← Domain logic: 7-dimension scoring engine (depends on models + patterns)
extractor.py   ← Infrastructure: reads ~/.claude/ JSONL files
db.py          ← Infrastructure: SQLite persistence (uses patterns)
export.py      ← Application: SQL queries → dashboard data dict (uses patterns)
pipeline.py    ← Extraction orchestration (shared by cli + dashboard)
cli.py         ← Interface: argparse commands
dashboard/     ← Interface: Streamlit UI
```

Dependency direction enforced by import-linter (8 contracts in `pyproject.toml`).
Key rule: `dashboard` must not import from `cli`. Both use `pipeline` for extraction.

## Coverage

- Ratchet: 87% (`--cov-fail-under=87`)
- `dashboard/app.py` and `__main__.py` are excluded from coverage (Streamlit can't be unit-tested)
- Coverage can only go up, never down

## Setup

- Preferred: `mise install && uv sync --group dev && task setup`
- Fallback: `./setup.sh` (macOS/Linux) or `.\setup.ps1` (Windows)
