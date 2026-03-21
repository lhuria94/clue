"""CLI entry point for Clue — AI efficiency scoring for Claude Code.

Commands:
    python -m clue setup     # Install hook + first extract + open dashboard
    python -m clue dashboard # Extract + serve
    python -m clue extract   # Just extract data
    python -m clue export    # Export JSON (add --scrub for team sharing)
    python -m clue merge     # Merge multiple exports for team view
    python -m clue score     # Print efficiency score to terminal
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

from .db import DEFAULT_DB_PATH, init_db, query_scoring_data
from .export import generate_dashboard_data
from .extractor import DEFAULT_CLAUDE_DIR
from .pipeline import run_extract
from .scorer import compute_project_scores, compute_score, compute_trend

# Backwards-compatible alias for any external callers
_run_extract = run_extract


def cmd_extract(args: argparse.Namespace) -> None:
    """Extract data from ~/.claude/ into SQLite."""
    claude_dir = Path(args.claude_dir)
    db_path = Path(args.db)
    incremental = getattr(args, "incremental", False)

    mode = "incremental" if incremental else "full"
    print(f"Extracting ({mode}) from {claude_dir}")

    stats = run_extract(claude_dir, db_path, incremental=incremental)

    print(f"  Prompts: {stats['prompts']}")
    print(f"  AI Responses: {stats['turns']}")
    print(f"  Sessions: {stats['sessions']}")
    print("Done.")


def cmd_export(args: argparse.Namespace) -> None:
    """Export dashboard JSON from SQLite."""
    db_path = Path(args.db)
    conn = init_db(db_path)
    data = generate_dashboard_data(
        conn,
        scrub=getattr(args, "scrub", False),
        user_label=getattr(args, "user_label", None),
        git_correlation=getattr(args, "git_correlation", False),
    )
    conn.close()

    output = Path(args.output)
    output.write_text(json.dumps(data, indent=2))
    print(f"Exported dashboard data to {output}")
    if getattr(args, "scrub", False):
        print("  (prompt text scrubbed for team sharing)")


def cmd_merge(args: argparse.Namespace) -> None:
    """Merge multiple exported JSON files for team dashboard."""
    files = args.files
    if len(files) < 2:
        print("Need at least 2 files to merge.")
        sys.exit(1)

    merged = None
    for f in files:
        path = Path(f)
        if not path.exists():
            print(f"File not found: {f}")
            sys.exit(1)
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"Error: {f} is not valid JSON: {exc}")
            sys.exit(1)
        if merged is None:
            merged = data
            merged["users"] = [data.get("user_label", path.stem)]
            continue

        merged["users"].append(data.get("user_label", path.stem))

        # Merge overview (sum)
        for key in merged["overview"]:
            if isinstance(merged["overview"][key], (int, float)):
                merged["overview"][key] += data["overview"].get(key, 0)

        # Merge lists (concatenate + deduplicate where possible)
        for list_key in (
            "daily_usage",
            "daily_tokens",
            "daily_cost",
            "daily_project",
            "daily_project_tokens",
            "daily_tools",
            "daily_models",
            "prompt_lengths",
            "model_totals",
            "branch_usage",
            "project_scores",
        ):
            if list_key in data:
                merged.setdefault(list_key, []).extend(data[list_key])

        # Merge distributions (sum counts per bucket)
        for dist_key in ("hourly_distribution", "day_of_week_distribution"):
            if dist_key in data and dist_key in merged:
                existing = {
                    item.get("hour", item.get("day", item.get("bucket"))): item
                    for item in merged[dist_key]
                }
                for item in data[dist_key]:
                    key = item.get("hour", item.get("day", item.get("bucket")))
                    if key in existing:
                        existing[key]["prompts"] = existing[key].get("prompts", 0) + item.get(
                            "prompts", 0
                        )
                        existing[key]["count"] = existing[key].get("count", 0) + item.get(
                            "count", 0
                        )

    output = Path(args.output)
    output.write_text(json.dumps(merged, indent=2))
    print(f"Merged {len(files)} files → {output}")
    print(f"  Users: {', '.join(merged.get('users', []))}")


def cmd_score(args: argparse.Namespace) -> None:
    """Print efficiency score to terminal."""
    from .db import query_all_projects, query_project_stats, query_trend_data

    db_path = Path(args.db)
    conn = init_db(db_path)
    scoring_data = query_scoring_data(conn)
    score = compute_score(scoring_data)
    trend_data = query_trend_data(conn)
    trend, trend_delta = compute_trend(trend_data)

    trend_arrow = {"improving": "+", "declining": "-", "stable": "="}[trend]

    print(
        f"\n  AI Efficiency Score: {score.overall:.0f}/100  [{score.grade}]"
        f"  {trend_arrow}{abs(trend_delta):.1f}%\n"
    )
    print("  Dimension Scores:")
    print(f"  {'Dimension':<22} {'Score':>6} {'Grade':>6} {'Weight':>7}")
    print(f"  {'─' * 45}")
    for d in score.dimensions:
        bar = "█" * int(d.score / 5) + "░" * (20 - int(d.score / 5))
        print(f"  {d.name:<22} {d.score:>5.0f}  {d.grade:>5}  {d.weight:>5.0%}")
        print(f"    {bar}  {d.explanation}")

    if score.top_recommendations:
        print("\n  Top Recommendations:")
        for i, rec in enumerate(score.top_recommendations, 1):
            print(f"  {i}. {rec}")

    # Per-project scores
    projects = query_all_projects(conn)
    per_project_data = {p: query_scoring_data(conn, project=p) for p in projects}
    per_project_stats = {p: query_project_stats(conn, p) for p in projects}
    project_scores = compute_project_scores(projects, per_project_data, per_project_stats)
    if project_scores:
        print("\n  Per-Project Scores:")
        print(f"  {'Project':<30} {'Score':>6} {'Grade':>6} {'Prompts':>8} {'Tokens':>10}")
        print(f"  {'─' * 65}")
        for ps in project_scores:
            tokens_str = (
                f"{ps.token_count / 1_000_000:.1f}M"
                if ps.token_count > 1_000_000
                else f"{ps.token_count / 1_000:.0f}K"
            )
            print(
                f"  {ps.project:<30} {ps.score.overall:>5.0f}  {ps.score.grade:>5}"
                f"  {ps.prompt_count:>7}  {tokens_str:>9}"
            )

    conn.close()
    print()


def cmd_doctor(args: argparse.Namespace) -> None:
    """Validate all prerequisites and tech stack components."""
    checks_passed = 0
    checks_failed = 0
    is_windows = platform.system() == "Windows"

    def check(name: str, passed: bool, detail: str = "", fix: str = "") -> bool:
        nonlocal checks_passed, checks_failed
        if passed:
            checks_passed += 1
            print(f"  [OK]   {name}" + (f"  ({detail})" if detail else ""))
        else:
            checks_failed += 1
            print(f"  [FAIL] {name}" + (f"  ({detail})" if detail else ""))
            if fix:
                print(f"         Fix: {fix}")
        return passed

    print("\nClue doctor")
    print("=" * 50)

    # 1. Python version
    v = sys.version_info
    check(
        "Python >= 3.10",
        v.major >= 3 and v.minor >= 10,
        f"{v.major}.{v.minor}.{v.micro} at {sys.executable}",
        fix="Install Python 3.10+:\n"
        "         macOS:   brew install python@3.12\n"
        "         Ubuntu:  sudo apt install python3.12 python3.12-venv\n"
        "         Fedora:  sudo dnf install python3.12\n"
        "         Windows: winget install Python.Python.3.12\n"
        "                  or https://python.org/downloads/",
    )

    # 2. SQLite
    try:
        import sqlite3

        sqlite_version = sqlite3.sqlite_version
        check("sqlite3 module", True, f"SQLite {sqlite_version}")
    except ImportError:
        check("sqlite3 module", False, fix="Rebuild Python with SQLite support")

    # 3. venv module
    try:
        import venv  # noqa: F401

        check("venv module", True)
    except ImportError:
        check(
            "venv module",
            False,
            fix="Ubuntu/Debian: sudo apt install python3-venv\n"
            "         Fedora: sudo dnf install python3-venv",
        )

    # 4. Claude Code data directory
    claude_dir = Path(args.claude_dir)
    check(
        "Claude Code data (~/.claude/)",
        claude_dir.exists(),
        str(claude_dir),
        fix="Install Claude Code: npm install -g @anthropic-ai/claude-code\n"
        "         Then use it at least once to generate data.",
    )

    # 5. history.jsonl
    history_file = claude_dir / "history.jsonl"
    if history_file.exists():
        with open(history_file, "rb") as _fh:
            line_count = sum(1 for _ in _fh)
        check("history.jsonl", True, f"{line_count} prompts")
    else:
        check(
            "history.jsonl", False, fix="Use Claude Code at least once to generate prompt history."
        )

    # 6. Conversation files
    projects_dir = claude_dir / "projects"
    if projects_dir.exists():
        conv_count = sum(1 for _ in projects_dir.rglob("*.jsonl"))
        check("Conversation files", conv_count > 0, f"{conv_count} JSONL files")
    else:
        check("Conversation files", False, fix="Use Claude Code to generate conversation data.")

    # 7. Settings.json (for hooks)
    settings_file = claude_dir / "settings.json"
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
            has_hook = "Stop" in settings.get("hooks", {})
            check(
                "PostStop hook",
                has_hook,
                "continuous capture enabled" if has_hook else "not installed",
                fix="Run: python -m clue setup",
            )
        except json.JSONDecodeError:
            check(
                "settings.json",
                False,
                "malformed JSON",
                fix="Check ~/.claude/settings.json for syntax errors",
            )
    else:
        check("settings.json", False, fix="Run: python -m clue setup")

    # 8. Database
    db_path = Path(args.db)
    if db_path.exists():
        try:
            conn = init_db(db_path)
            cur = conn.execute("SELECT COUNT(*) FROM prompts")
            prompt_count = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM turns")
            turn_count = cur.fetchone()[0]
            conn.close()
            check("SQLite database", True, f"{prompt_count} prompts, {turn_count} AI responses")
        except Exception as e:
            check("SQLite database", False, str(e))
    else:
        check("SQLite database", False, "not yet created", fix="Run: python -m clue extract")

    # 9. Dashboard app
    dashboard_app = Path(__file__).parent / "dashboard" / "app.py"
    check("Dashboard app", dashboard_app.exists(), str(dashboard_app))

    # 10. Platform-specific checks
    if is_windows:
        check("Platform", True, "Windows — paths use backslash encoding")
    elif platform.system() == "Darwin":
        check("Platform", True, f"macOS {platform.mac_ver()[0]}")
    else:
        check("Platform", True, f"Linux {platform.release()}")

    # 11. Optional: Taskfile
    import shutil

    task_bin = shutil.which("task")
    if task_bin:
        check("Taskfile (optional)", True, task_bin)
    else:
        print("  [SKIP] Taskfile (optional) — not installed")
        print("         Install: https://taskfile.dev/installation/")
        print("         macOS: brew install go-task")
        print("         Or just use: python -m clue <command>")

    # 12. Optional: Git
    git_bin = shutil.which("git")
    if git_bin:
        check("Git (optional)", True, git_bin)
    else:
        print("  [SKIP] Git (optional) — not installed")

    # Summary
    total = checks_passed + checks_failed
    print(f"\n  {checks_passed}/{total} checks passed", end="")
    if checks_failed:
        print(f", {checks_failed} failed")
        sys.exit(1)
    else:
        print(" — all good!\n")


def cmd_setup(args: argparse.Namespace) -> None:
    """One-command setup: install hook + extract + open dashboard."""
    claude_dir = Path(args.claude_dir)
    db_path = Path(args.db)

    print("Clue — Setup")
    print("=" * 40)

    # 1. Verify .claude directory exists
    if not claude_dir.exists():
        print(f"Error: {claude_dir} not found. Is Claude Code installed?")
        sys.exit(1)

    print(f"  Found Claude Code data at {claude_dir}")

    # 2. Install PostStop hook for continuous capture
    settings_file = claude_dir / "settings.json"

    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            settings = {}
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})

    # Build the hook command — cross-platform Python invocation
    python_cmd = sys.executable
    if platform.system() == "Windows":
        def _quote(s: str) -> str:
            return f'"{s}"' if " " in s else s
    else:
        _quote = shlex.quote
    hook_command = (
        f"{_quote(python_cmd)} -m clue extract --incremental"
        f" --claude-dir {_quote(str(claude_dir))}"
        f" --db {_quote(str(db_path))}"
    )

    # Check if hook already exists
    stop_hooks = hooks.get("Stop", [])
    already_installed = any(
        any(h.get("command", "") == hook_command for h in entry.get("hooks", []))
        for entry in stop_hooks
        if isinstance(entry, dict)
    )

    if not already_installed:
        stop_hooks.append(
            {
                "hooks": [{"type": "command", "command": hook_command}],
            }
        )
        hooks["Stop"] = stop_hooks
        settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        print("  Installed PostStop hook for continuous capture")
    else:
        print("  PostStop hook already installed")

    # 3. Run initial extraction
    print("  Running initial extraction...")
    stats = run_extract(claude_dir, db_path)
    prompts, resps, sess = stats["prompts"], stats["turns"], stats["sessions"]
    print(f"    {prompts} prompts, {resps} AI responses, {sess} sessions")

    # 4. Print initial score
    conn = init_db(db_path)
    scoring_data = query_scoring_data(conn)
    score = compute_score(scoring_data)
    conn.close()

    print(f"\n  AI Efficiency Score: {score.overall:.0f}/100  [{score.grade}]")
    if score.top_recommendations:
        print("\n  Quick wins:")
        for i, rec in enumerate(score.top_recommendations[:3], 1):
            print(f"    {i}. {rec}")

    print("\n  Setup complete. Run 'python -m clue dashboard' to open.")
    print("  Data auto-captures after each Claude Code session via hook.\n")


def cmd_digest(args: argparse.Namespace) -> None:
    """Print a data-driven weekly digest to terminal."""

    db_path = Path(args.db)
    if not db_path.exists():
        print("No data yet. Run: clue extract")
        sys.exit(1)

    conn = init_db(db_path)
    data = generate_dashboard_data(conn)
    conn.close()

    digest = data.get("weekly_digest", {})
    if not digest.get("has_data"):
        print("Not enough data for a weekly digest yet.")
        return

    tw = digest["this_week"]
    lw = digest["last_week"]

    tw_label = digest.get("this_week_label", "This week")
    print(f"\n  Weekly Digest ({tw_label})")
    print(f"  {'─' * 50}")

    # Line 1: Activity delta
    if lw["prompts"] > 0:
        delta = ((tw["prompts"] - lw["prompts"]) / lw["prompts"]) * 100
        arrow = "+" if delta > 0 else ""
        print(f"  {tw['prompts']} prompts across {tw['sessions']} sessions "
              f"({arrow}{delta:.0f}% vs last week)")
    else:
        print(f"  {tw['prompts']} prompts across {tw['sessions']} sessions")

    # Line 2: Cost delta
    if lw["cost"] > 0:
        cost_delta = tw["cost"] - lw["cost"]
        arrow = "+" if cost_delta > 0 else ""
        print(f"  Spent ${tw['cost']:.2f} ({arrow}${cost_delta:.2f} vs last week)")
    else:
        print(f"  Spent ${tw['cost']:.2f}")

    # Line 3: Prompt quality delta
    if lw["avg_prompt_length"] > 0:
        len_delta = tw["avg_prompt_length"] - lw["avg_prompt_length"]
        direction = "longer" if len_delta > 0 else "shorter"
        print(f"  Avg prompt length: {tw['avg_prompt_length']:.0f} chars "
              f"({abs(len_delta):.0f} chars {direction})")

    # Line 4-5: Data-driven recommendations
    eff = data.get("efficiency_score", {})
    recs = eff.get("top_recommendations", [])
    if recs:
        print("\n  This week, try:")
        for r in recs[:2]:
            print(f"  → {r}")

    # Line 6: Prompt learning insight
    prompt_learning = data.get("prompt_learning", [])
    with_refs = next((p for p in prompt_learning if p["pattern"] == "With file references"), None)
    without_refs = next(
        (p for p in prompt_learning if p["pattern"] == "Without file references"), None
    )
    if with_refs and without_refs:
        print(f"\n  Prompt insight: file-ref prompts have "
              f"{with_refs['correction_rate']:.0f}% correction rate "
              f"vs {without_refs['correction_rate']:.0f}% without.")

    print()


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Run extract + serve the Streamlit dashboard."""
    claude_dir = Path(args.claude_dir)
    db_path = Path(args.db)
    port = args.port

    if not claude_dir.exists():
        print(f"Error: {claude_dir} not found. Is Claude Code installed?")
        print("  Install: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    # Initial extract
    print(f"Extracting from {claude_dir}...")
    stats = run_extract(claude_dir, db_path)
    prompts, resps, sess = stats["prompts"], stats["turns"], stats["sessions"]
    print(f"  {prompts} prompts, {resps} AI responses, {sess} sessions")

    # Launch Streamlit — dashboard queries SQLite directly
    app_path = Path(__file__).parent / "dashboard" / "app.py"

    _SAFE_ENV_KEYS = {"PATH", "HOME", "USER", "LANG", "TERM", "PYTHONPATH", "VIRTUAL_ENV"}
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    env["CLUE_DB_PATH"] = str(db_path)
    env["CLUE_CLAUDE_DIR"] = str(claude_dir)

    print(f"Dashboard → http://localhost:{port}")
    print("  Live data — auto-refreshes every 2 minutes")
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "streamlit", "run", str(app_path),
                "--server.port", str(port),
                "--server.headless", "true",
                "--theme.primaryColor", "#6366f1",
                "--browser.gatherUsageStats", "false",
            ],
            env=env,
        )
        if result.returncode != 0:
            print("Error: Streamlit failed to start.")
            print("  Fix: pip install 'clue[dev]'  (or: uv sync --group dev)")
            sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nStopped.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="clue",
        description="Clue — AI efficiency scoring for Claude Code",
    )
    parser.add_argument(
        "--claude-dir",
        default=str(DEFAULT_CLAUDE_DIR),
        help="Path to .claude directory (default: ~/.claude)",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to SQLite database (default: ~/.claude/usage.db)",
    )

    sub = parser.add_subparsers(dest="command")

    # doctor
    sub.add_parser("doctor", help="Validate all prerequisites and tech stack")

    # setup
    sub.add_parser("setup", help="One-command setup: install hook + extract + score")

    # extract
    extract_p = sub.add_parser("extract", help="Extract data from Claude Code local files")
    extract_p.add_argument(
        "--incremental", action="store_true", help="Only extract new data since last run"
    )

    # export
    export_p = sub.add_parser("export", help="Export dashboard data as JSON")
    export_p.add_argument("-o", "--output", default="clue-data.json")
    export_p.add_argument("--scrub", action="store_true", help="Strip prompt text for team sharing")
    export_p.add_argument("--user-label", help="Label for team aggregation (e.g. your name)")
    export_p.add_argument(
        "--git-correlation", action="store_true",
        help="Correlate sessions with git commits (slower, requires local repos)",
    )

    # merge
    merge_p = sub.add_parser("merge", help="Merge multiple exported JSON files")
    merge_p.add_argument("files", nargs="+", help="JSON files to merge")
    merge_p.add_argument("-o", "--output", default="team-dashboard-data.json")

    # score
    sub.add_parser("score", help="Print efficiency score to terminal")

    # digest
    sub.add_parser("digest", help="Weekly digest — what improved, what to try next")

    # dashboard
    dash_p = sub.add_parser("dashboard", help="Extract data and serve the dashboard")
    dash_p.add_argument("-p", "--port", type=int, default=8484)

    args = parser.parse_args()

    commands = {
        "doctor": cmd_doctor,
        "setup": cmd_setup,
        "extract": cmd_extract,
        "export": cmd_export,
        "merge": cmd_merge,
        "score": cmd_score,
        "digest": cmd_digest,
        "dashboard": cmd_dashboard,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        # Default: show score if data exists, else run setup
        db_path = Path(args.db)
        if db_path.exists():
            args.port = 8484
            cmd_dashboard(args)
        else:
            cmd_setup(args)


if __name__ == "__main__":
    main()
