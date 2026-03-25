"""Unit tests for the database module."""

from __future__ import annotations

from clue.db import (
    clear_db,
    get_watermark,
    init_db,
    insert_prompts,
    insert_turns,
    set_watermark,
)
from clue.models import ConversationTurn, TokenUsage


class TestInitDb:
    def test_creates_tables(self, db_conn):
        cur = db_conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {r[0] for r in cur.fetchall()}
        assert "prompts" in tables
        assert "turns" in tables
        assert "sessions" in tables
        assert "watermarks" in tables
        assert "schema_version" in tables

    def test_creates_indexes(self, db_conn):
        cur = db_conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {r[0] for r in cur.fetchall()}
        assert "idx_prompts_date" in indexes
        assert "idx_turns_session" in indexes

    def test_schema_version(self, db_conn):
        cur = db_conn.execute("SELECT MAX(version) FROM schema_version")
        assert cur.fetchone()[0] == 3

    def test_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn1, _ = init_db(db_path)
        conn1.close()
        conn2, _ = init_db(db_path)
        cur = conn2.execute("SELECT MAX(version) FROM schema_version")
        assert cur.fetchone()[0] == 3
        conn2.close()

    def test_wal_mode(self, db_conn):
        cur = db_conn.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0] == "wal"


class TestWatermarks:
    def test_get_empty(self, db_conn):
        mtime, lines = get_watermark(db_conn, "nonexistent")
        assert mtime == 0.0
        assert lines == 0

    def test_set_and_get(self, db_conn):
        set_watermark(db_conn, "history.jsonl", 1234567.89, 100)
        mtime, lines = get_watermark(db_conn, "history.jsonl")
        assert mtime == 1234567.89
        assert lines == 100

    def test_update(self, db_conn):
        set_watermark(db_conn, "file.jsonl", 100.0, 10)
        set_watermark(db_conn, "file.jsonl", 200.0, 20)
        mtime, lines = get_watermark(db_conn, "file.jsonl")
        assert mtime == 200.0
        assert lines == 20


class TestInsertPrompts:
    def test_insert_and_query(self, db_conn, sample_prompts):
        count = insert_prompts(db_conn, sample_prompts)
        assert count == 3
        cur = db_conn.execute("SELECT COUNT(*) FROM prompts")
        assert cur.fetchone()[0] == 3

    def test_empty_list(self, db_conn):
        count = insert_prompts(db_conn, [])
        assert count == 0

    def test_date_extraction(self, db_conn, sample_prompts):
        insert_prompts(db_conn, sample_prompts)
        cur = db_conn.execute("SELECT DISTINCT date FROM prompts")
        dates = [r[0] for r in cur.fetchall()]
        assert "2025-03-21" in dates


class TestInsertTurns:
    def test_insert_with_new_fields(self, db_conn):
        turn = ConversationTurn(
            session_id="s1",
            project="proj",
            role="assistant",
            model="claude-sonnet-4-6",
            tool_name="Read",
            usage=TokenUsage(input_tokens=100, output_tokens=50),
            cwd="/home/user/proj",
            git_branch="main",
            claude_version="2.1.75",
            stop_reason="end_turn",
        )
        count = insert_turns(db_conn, [turn])
        assert count == 1

        cur = db_conn.execute("SELECT cwd, git_branch, claude_version, stop_reason FROM turns")
        row = cur.fetchone()
        assert row == ("/home/user/proj", "main", "2.1.75", "end_turn")

    def test_insert_with_schema3_fields(self, db_conn):
        """Schema-3 advanced usage columns round-trip correctly."""
        turn = ConversationTurn(
            session_id="s1",
            project="proj",
            role="assistant",
            model="claude-sonnet-4-6",
            tool_name="Agent",
            usage=TokenUsage(input_tokens=100, output_tokens=50),
            tool_input_subagent_type="researcher",
            tool_input_run_in_background=True,
            tool_input_skill=None,
        )
        insert_turns(db_conn, [turn])
        cur = db_conn.execute(
            "SELECT tool_input_subagent_type, tool_input_run_in_background, tool_input_skill FROM turns"
        )
        row = cur.fetchone()
        assert row == ("researcher", 1, None)

    def test_insert_with_skill_field(self, db_conn):
        """Schema-3 skill column round-trips correctly."""
        turn = ConversationTurn(
            session_id="s1",
            project="proj",
            role="assistant",
            model="claude-sonnet-4-6",
            tool_name="Skill",
            usage=TokenUsage(input_tokens=50, output_tokens=30),
            tool_input_skill="commit",
        )
        insert_turns(db_conn, [turn])
        cur = db_conn.execute("SELECT tool_input_skill FROM turns")
        row = cur.fetchone()
        assert row == ("commit",)


class TestClearDb:
    def test_clears_all_data(self, db_conn, sample_prompts):
        insert_prompts(db_conn, sample_prompts)
        set_watermark(db_conn, "test", 1.0, 1)
        clear_db(db_conn)
        cur = db_conn.execute("SELECT COUNT(*) FROM prompts")
        assert cur.fetchone()[0] == 0
        mtime, _ = get_watermark(db_conn, "test")
        assert mtime == 0.0
