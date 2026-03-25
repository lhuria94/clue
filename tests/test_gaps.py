"""Tests covering gaps identified during quality review.

Covers:
- delete_turns_by_sessions (new db function)
- find_changed_conversation_files (incremental conversation detection)
- Incremental turn deduplication correctness
- Scrub mode completeness (prompt_lengths removed)
- SQL injection resistance in db query layer
- Parameterised scorer with project scope
- Merge distribution logic
- Pure scorer tests (no database)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from clue.db import (
    delete_turns_by_sessions,
    get_watermark,
    init_db,
    insert_prompts,
    insert_sessions,
    insert_turns,
    query_scoring_data,
    set_watermark,
)
from clue.export import generate_dashboard_data
from clue.extractor import (
    build_sessions,
    extract_conversations,
    extract_prompts,
    find_changed_conversation_files,
)
from clue.models import ConversationTurn, Prompt, TokenUsage
from clue.scorer import compute_score

# ---------------------------------------------------------------------------
# delete_turns_by_sessions
# ---------------------------------------------------------------------------


class TestDeleteTurnsBySessions:
    def _insert_turns(self, conn, session_id, count):
        turns = [
            ConversationTurn(
                session_id=session_id,
                project="proj",
                role="assistant",
                model="claude-sonnet-4-6",
                usage=TokenUsage(input_tokens=100, output_tokens=50),
            )
            for _ in range(count)
        ]
        insert_turns(conn, turns)
        return turns

    def test_deletes_matching_session(self, db_conn):
        self._insert_turns(db_conn, "s1", 3)
        self._insert_turns(db_conn, "s2", 2)

        deleted = delete_turns_by_sessions(db_conn, {"s1"})

        assert deleted == 3
        cur = db_conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = 's1'")
        assert cur.fetchone()[0] == 0
        cur = db_conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = 's2'")
        assert cur.fetchone()[0] == 2

    def test_deletes_multiple_sessions(self, db_conn):
        self._insert_turns(db_conn, "s1", 2)
        self._insert_turns(db_conn, "s2", 3)
        self._insert_turns(db_conn, "s3", 1)

        deleted = delete_turns_by_sessions(db_conn, {"s1", "s3"})

        assert deleted == 3
        cur = db_conn.execute("SELECT COUNT(*) FROM turns")
        assert cur.fetchone()[0] == 3  # only s2 remains

    def test_empty_set_deletes_nothing(self, db_conn):
        self._insert_turns(db_conn, "s1", 2)
        deleted = delete_turns_by_sessions(db_conn, set())
        assert deleted == 0
        cur = db_conn.execute("SELECT COUNT(*) FROM turns")
        assert cur.fetchone()[0] == 2

    def test_nonexistent_session_returns_zero(self, db_conn):
        self._insert_turns(db_conn, "s1", 2)
        deleted = delete_turns_by_sessions(db_conn, {"nonexistent"})
        assert deleted == 0


# ---------------------------------------------------------------------------
# find_changed_conversation_files
# ---------------------------------------------------------------------------


class TestFindChangedConversationFiles:
    def test_detects_new_files(self, mock_claude_dir, db_conn):
        changed = find_changed_conversation_files(
            mock_claude_dir,
            get_wm=lambda key: get_watermark(db_conn, key),
            set_wm=lambda key, mtime, lines: set_watermark(db_conn, key, mtime, lines),
        )
        # First run: all files should be detected as changed
        assert len(changed) >= 1
        assert all(f.endswith(".jsonl") for f in changed)

    def test_no_changes_on_second_run(self, mock_claude_dir, db_conn):
        # First run records watermarks
        find_changed_conversation_files(
            mock_claude_dir,
            get_wm=lambda key: get_watermark(db_conn, key),
            set_wm=lambda key, mtime, lines: set_watermark(db_conn, key, mtime, lines),
        )
        # Second run — nothing changed
        changed = find_changed_conversation_files(
            mock_claude_dir,
            get_wm=lambda key: get_watermark(db_conn, key),
            set_wm=lambda key, mtime, lines: set_watermark(db_conn, key, mtime, lines),
        )
        assert len(changed) == 0

    def test_detects_modified_file(self, mock_claude_dir, db_conn):
        # First run
        find_changed_conversation_files(
            mock_claude_dir,
            get_wm=lambda key: get_watermark(db_conn, key),
            set_wm=lambda key, mtime, lines: set_watermark(db_conn, key, mtime, lines),
        )

        # Modify a file (touch it to update mtime)
        project_dir = mock_claude_dir / "projects" / "-home-user-project-alpha"
        conv_file = next(project_dir.glob("*.jsonl"))
        time.sleep(0.05)  # ensure mtime changes
        conv_file.write_text(conv_file.read_text() + "\n")

        changed = find_changed_conversation_files(
            mock_claude_dir,
            get_wm=lambda key: get_watermark(db_conn, key),
            set_wm=lambda key, mtime, lines: set_watermark(db_conn, key, mtime, lines),
        )
        assert str(conv_file) in changed

    def test_handles_missing_projects_dir(self, tmp_path, db_conn):
        empty_dir = tmp_path / ".claude-empty"
        empty_dir.mkdir()
        changed = find_changed_conversation_files(
            empty_dir,
            get_wm=lambda key: get_watermark(db_conn, key),
            set_wm=lambda key, mtime, lines: set_watermark(db_conn, key, mtime, lines),
        )
        assert changed == set()

    def test_detects_subagent_files(self, mock_claude_dir, db_conn):
        changed = find_changed_conversation_files(
            mock_claude_dir,
            get_wm=lambda key: get_watermark(db_conn, key),
            set_wm=lambda key, mtime, lines: set_watermark(db_conn, key, mtime, lines),
        )
        subagent_files = [f for f in changed if "subagent" in f]
        assert len(subagent_files) >= 1


# ---------------------------------------------------------------------------
# Incremental turn deduplication
# ---------------------------------------------------------------------------


class TestIncrementalTurnDeduplication:
    """Verify that re-extracting changed sessions doesn't duplicate turns."""

    def test_no_duplicates_after_reextract(self, mock_claude_dir, tmp_path):
        db_path = tmp_path / "dedup.db"
        conn, _ = init_db(db_path)

        # Full extraction
        prompts = extract_prompts(mock_claude_dir)
        turns = extract_conversations(mock_claude_dir)
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)

        initial_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]

        # Simulate incremental: re-extract same sessions
        affected_sessions = {t.session_id for t in turns}
        delete_turns_by_sessions(conn, affected_sessions)
        insert_turns(conn, turns)

        final_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        assert final_count == initial_count

        conn.close()

    def test_session_rebuild_preserves_totals(self, mock_claude_dir, tmp_path):
        """Sessions rebuilt after incremental extraction should have correct totals."""
        db_path = tmp_path / "rebuild.db"
        conn, _ = init_db(db_path)

        prompts = extract_prompts(mock_claude_dir)
        turns = extract_conversations(mock_claude_dir)
        sessions = build_sessions(prompts, turns)
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)
        insert_sessions(conn, sessions)

        # Record original session totals
        cur = conn.execute(
            "SELECT session_id, total_input_tokens, total_output_tokens, turn_count "
            "FROM sessions ORDER BY session_id"
        )
        original = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}

        # Simulate incremental: delete + reinsert turns, rebuild sessions
        affected = {t.session_id for t in turns}
        delete_turns_by_sessions(conn, affected)
        insert_turns(conn, turns)
        new_sessions = build_sessions(prompts, turns)
        insert_sessions(conn, new_sessions)

        cur = conn.execute(
            "SELECT session_id, total_input_tokens, total_output_tokens, turn_count "
            "FROM sessions ORDER BY session_id"
        )
        rebuilt = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}

        assert rebuilt == original
        conn.close()


# ---------------------------------------------------------------------------
# Scrub mode completeness
# ---------------------------------------------------------------------------


class TestScrubModeCompleteness:
    def test_prompt_lengths_removed(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn, scrub=True)
        assert "prompt_lengths" not in data

    def test_non_scrub_has_prompt_lengths(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn, scrub=False)
        assert "prompt_lengths" in data
        assert len(data["prompt_lengths"]) >= 1


# ---------------------------------------------------------------------------
# SQL injection resistance in db query layer
# ---------------------------------------------------------------------------


class TestQuerySQLInjectionResistance:
    """Verify that project names with special characters don't break queries."""

    def _seed_with_project(self, conn, project_name):
        prompts = [
            Prompt(
                timestamp=datetime(2025, 3, 21, 10, 0, tzinfo=timezone.utc),
                project=project_name,
                session_id="s1",
                text="a detailed prompt about fixing authentication in the login flow",
                char_length=63,
            ),
        ]
        turns = [
            ConversationTurn(
                session_id="s1",
                project=project_name,
                role="assistant",
                model="claude-sonnet-4-6",
                tool_name="Read",
                usage=TokenUsage(
                    input_tokens=500,
                    output_tokens=200,
                    cache_creation_tokens=100,
                    cache_read_tokens=900,
                ),
                timestamp="2025-03-21T10:00:00.000Z",
            ),
        ]
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)

    def test_single_quote_in_project(self, db_conn):
        self._seed_with_project(db_conn, "O'Reilly's project")
        data = query_scoring_data(db_conn, project="O'Reilly's project")
        score = compute_score(data)
        assert score.overall >= 0

    def test_double_quote_in_project(self, db_conn):
        self._seed_with_project(db_conn, 'project "alpha"')
        data = query_scoring_data(db_conn, project='project "alpha"')
        score = compute_score(data)
        assert score.overall >= 0

    def test_semicolon_in_project(self, db_conn):
        self._seed_with_project(db_conn, "proj; DROP TABLE turns;--")
        data = query_scoring_data(db_conn, project="proj; DROP TABLE turns;--")
        score = compute_score(data)
        assert score.overall >= 0
        # Verify table still exists
        cur = db_conn.execute("SELECT COUNT(*) FROM turns")
        assert cur.fetchone()[0] > 0

    def test_percent_in_project(self, db_conn):
        self._seed_with_project(db_conn, "project%20name")
        data = query_scoring_data(db_conn, project="project%20name")
        score = compute_score(data)
        assert score.overall >= 0


# ---------------------------------------------------------------------------
# Parameterised scorer with project scope
# ---------------------------------------------------------------------------


class TestScorerProjectScope:
    """Verify scoring is correctly scoped to a single project."""

    def test_project_score_isolated(self, db_conn):
        """Scores for project A should not include project B data."""
        # Project A: good prompts, diverse tools
        for i in range(10):
            insert_prompts(
                db_conn,
                [
                    Prompt(
                        timestamp=datetime(2025, 3, 21, 10, i, tzinfo=timezone.utc),
                        project="good-proj",
                        session_id="s-good",
                        text="a" * 120,
                        char_length=120,
                    )
                ],
            )
        insert_turns(
            db_conn,
            [
                ConversationTurn(
                    session_id="s-good",
                    project="good-proj",
                    role="assistant",
                    model="claude-sonnet-4-6",
                    tool_name=tool,
                    usage=TokenUsage(
                        input_tokens=500,
                        output_tokens=200,
                        cache_creation_tokens=100,
                        cache_read_tokens=900,
                    ),
                    timestamp="2025-03-21T10:00:00.000Z",
                )
                for tool in ["Read", "Edit", "Bash", "Grep", "Agent"]
            ],
        )

        # Project B: bad prompts, single tool
        for i in range(10):
            insert_prompts(
                db_conn,
                [
                    Prompt(
                        timestamp=datetime(2025, 3, 21, 11, i, tzinfo=timezone.utc),
                        project="bad-proj",
                        session_id="s-bad",
                        text="ok",
                        char_length=2,
                    )
                ],
            )
        insert_turns(
            db_conn,
            [
                ConversationTurn(
                    session_id="s-bad",
                    project="bad-proj",
                    role="assistant",
                    model="claude-sonnet-4-6",
                    tool_name="Bash",
                    usage=TokenUsage(input_tokens=5000, output_tokens=50),
                    timestamp="2025-03-21T11:00:00.000Z",
                )
                for _ in range(10)
            ],
        )

        good_data = query_scoring_data(db_conn, project="good-proj")
        bad_data = query_scoring_data(db_conn, project="bad-proj")
        good_score = compute_score(good_data)
        bad_score = compute_score(bad_data)

        # Good project should score higher than bad project
        assert good_score.overall > bad_score.overall

    def test_nonexistent_project_returns_low_score(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = query_scoring_data(db_conn, project="does-not-exist")
        score = compute_score(data)
        assert score.overall <= 50


# ---------------------------------------------------------------------------
# Merge distribution logic
# ---------------------------------------------------------------------------


class TestMergeDistributions:
    def test_hourly_distribution_merged(self, mock_claude_dir, tmp_path):
        from clue.cli import cmd_export, cmd_merge

        class _Args:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        db_path = str(tmp_path / "test.db")
        from clue.cli import cmd_extract

        cmd_extract(_Args(claude_dir=str(mock_claude_dir), db=db_path, incremental=False))

        f1 = str(tmp_path / "a.json")
        f2 = str(tmp_path / "b.json")
        cmd_export(_Args(db=db_path, output=f1, scrub=False, user_label="a"))
        cmd_export(_Args(db=db_path, output=f2, scrub=False, user_label="b"))

        output = str(tmp_path / "team.json")
        cmd_merge(_Args(files=[f1, f2], output=output))

        merged = json.loads(Path(output).read_text())

        # Hourly distribution should have 24 entries
        assert len(merged["hourly_distribution"]) == 24
        # Day of week should have 7 entries
        assert len(merged["day_of_week_distribution"]) == 7
        # Values should be summed (doubled since same data twice)
        single = json.loads(Path(f1).read_text())
        for i, entry in enumerate(merged["hourly_distribution"]):
            assert entry["prompts"] == single["hourly_distribution"][i]["prompts"] * 2

    def test_daily_usage_merged(self, mock_claude_dir, tmp_path):
        from clue.cli import cmd_export, cmd_extract, cmd_merge

        class _Args:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        db_path = str(tmp_path / "test.db")
        cmd_extract(_Args(claude_dir=str(mock_claude_dir), db=db_path, incremental=False))

        f1 = str(tmp_path / "a.json")
        f2 = str(tmp_path / "b.json")
        cmd_export(_Args(db=db_path, output=f1, scrub=False, user_label="a"))
        cmd_export(_Args(db=db_path, output=f2, scrub=False, user_label="b"))

        output = str(tmp_path / "team.json")
        cmd_merge(_Args(files=[f1, f2], output=output))

        merged = json.loads(Path(output).read_text())
        assert "daily_usage" in merged
        assert len(merged["daily_usage"]) >= 1


# ---------------------------------------------------------------------------
# Edge cases in scoring functions
# ---------------------------------------------------------------------------


class TestScorerEdgeCases:
    def test_all_short_prompts(self, db_conn):
        """All prompts very short — should get low prompt quality score."""
        prompts = [
            Prompt(
                timestamp=datetime(2025, 3, 21, 10, i, tzinfo=timezone.utc),
                project="proj",
                session_id="s1",
                text="ok",
                char_length=2,
            )
            for i in range(20)
        ]
        insert_prompts(db_conn, prompts)
        data = query_scoring_data(db_conn)
        score = compute_score(data)
        pq = next(d for d in score.dimensions if d.name == "Prompt Quality")
        assert pq.score < 30
        assert len(pq.recommendations) > 0

    def test_single_session_many_prompts(self, db_conn):
        """Very deep session — should trigger session discipline warning."""
        prompts = [
            Prompt(
                timestamp=datetime(2025, 3, 21, 10, i % 60, tzinfo=timezone.utc),
                project="proj",
                session_id="s1",
                text="x" * 100,
                char_length=100,
            )
            for i in range(70)
        ]
        insert_prompts(db_conn, prompts)
        data = query_scoring_data(db_conn)
        score = compute_score(data)
        sd = next(d for d in score.dimensions if d.name == "Session Discipline")
        assert any("exceed 60" in r for r in sd.recommendations)

    def test_only_opus_usage(self, db_conn, sample_prompts):
        """All Opus — should trigger cost awareness recommendation."""
        insert_prompts(db_conn, sample_prompts)
        turns = [
            ConversationTurn(
                session_id="s1",
                project="project-alpha",
                role="assistant",
                model="claude-opus-4-6",
                usage=TokenUsage(input_tokens=1000, output_tokens=500),
                timestamp="2025-03-21T10:00:00.000Z",
            )
            for _ in range(10)
        ]
        insert_turns(db_conn, turns)
        data = query_scoring_data(db_conn)
        score = compute_score(data)
        ca = next(d for d in score.dimensions if d.name == "Cost Awareness")
        assert ca.score == 60  # single model = 60 (softened for Max plan users)
