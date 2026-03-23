"""Integration tests — full pipeline from files to dashboard JSON."""

from __future__ import annotations

import json

from clue.db import (
    init_db,
    insert_prompts,
    insert_sessions,
    insert_turns,
    set_watermark,
)
from clue.export import generate_dashboard_data
from clue.extractor import build_sessions, extract_conversations, extract_prompts


class TestFullPipeline:
    """End-to-end: mock files → extract → SQLite → export → JSON."""

    def test_full_extract_and_export(self, mock_claude_dir, tmp_path):
        db_path = tmp_path / "integration.db"
        conn = init_db(db_path)

        # Extract
        prompts = extract_prompts(mock_claude_dir)
        turns = extract_conversations(mock_claude_dir)
        sessions = build_sessions(prompts, turns)

        # Store
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)
        insert_sessions(conn, sessions)

        # Export
        data = generate_dashboard_data(conn)
        conn.close()

        # Validate structure
        assert data["overview"]["total_prompts"] == 5
        assert data["overview"]["total_sessions"] >= 1
        assert data["overview"]["total_projects"] >= 1
        assert data["overview"]["total_tokens"] > 0
        assert data["overview"]["estimated_cost_usd"] > 0

        # Efficiency score
        assert 0 <= data["efficiency_score"]["overall"] <= 100
        assert len(data["efficiency_score"]["dimensions"]) == 7

        # Project scores
        assert len(data["project_scores"]) >= 1

        # Charts data
        assert len(data["daily_usage"]) >= 1
        assert len(data["daily_tools"]) >= 1
        assert len(data["daily_models"]) >= 1

    def test_json_serialisable(self, mock_claude_dir, tmp_path):
        """Verify the export is fully JSON-serialisable."""
        db_path = tmp_path / "serial.db"
        conn = init_db(db_path)
        prompts = extract_prompts(mock_claude_dir)
        turns = extract_conversations(mock_claude_dir)
        sessions = build_sessions(prompts, turns)
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)
        insert_sessions(conn, sessions)
        data = generate_dashboard_data(conn)
        conn.close()

        # This will raise if any value is not JSON-serialisable
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["overview"]["total_prompts"] == 5


class TestIncrementalExtraction:
    """Test that incremental extraction works correctly."""

    def test_watermark_skips_old_prompts(self, mock_claude_dir, tmp_path):
        db_path = tmp_path / "incr.db"
        conn = init_db(db_path)

        # First extract — all prompts
        prompts_1 = extract_prompts(mock_claude_dir)
        assert len(prompts_1) == 5
        insert_prompts(conn, prompts_1)

        # Set watermark at line 3
        set_watermark(conn, "history", 0, 3)

        # Second extract — only new prompts (lines 3+)
        prompts_2 = extract_prompts(mock_claude_dir, since_line=3)
        assert len(prompts_2) == 2  # Lines 4 and 5

        conn.close()


class TestMultiProjectPipeline:
    def test_multiple_projects_in_single_export(self, mock_claude_dir, tmp_path):
        db_path = tmp_path / "multi.db"
        conn = init_db(db_path)
        prompts = extract_prompts(mock_claude_dir)
        turns = extract_conversations(mock_claude_dir)
        sessions = build_sessions(prompts, turns)
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)
        insert_sessions(conn, sessions)
        data = generate_dashboard_data(conn)
        conn.close()

        projects = {p["pj"] for p in data["daily_project"]}
        assert len(projects) >= 2


class TestSecurityConstraints:
    """Verify that sensitive data is handled correctly."""

    def test_scrub_mode_no_prompt_text_in_json(self, mock_claude_dir, tmp_path):
        db_path = tmp_path / "scrub.db"
        conn = init_db(db_path)
        prompts = extract_prompts(mock_claude_dir)
        turns = extract_conversations(mock_claude_dir)
        sessions = build_sessions(prompts, turns)
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)
        insert_sessions(conn, sessions)
        data = generate_dashboard_data(conn, scrub=True)
        conn.close()

        json_str = json.dumps(data)
        # Prompt text should not appear in the exported JSON
        # (the export doesn't include prompt text in any mode, only char_length)
        assert "fix the login bug" not in json_str

    def test_export_contains_no_file_paths(self, mock_claude_dir, tmp_path):
        db_path = tmp_path / "paths.db"
        conn = init_db(db_path)
        prompts = extract_prompts(mock_claude_dir)
        turns = extract_conversations(mock_claude_dir)
        sessions = build_sessions(prompts, turns)
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)
        insert_sessions(conn, sessions)
        data = generate_dashboard_data(conn)
        conn.close()

        json_str = json.dumps(data)
        # Absolute paths should not leak into the dashboard JSON
        assert "/home/user/project-alpha" not in json_str

    def test_scrub_mode_no_project_names_in_json(self, mock_claude_dir, tmp_path):
        """Project names must be stripped from all fields in scrub mode."""
        db_path = tmp_path / "scrub_proj.db"
        conn = init_db(db_path)
        prompts = extract_prompts(mock_claude_dir)
        turns = extract_conversations(mock_claude_dir)
        sessions = build_sessions(prompts, turns)
        insert_prompts(conn, prompts)
        insert_turns(conn, turns)
        insert_sessions(conn, sessions)
        data = generate_dashboard_data(conn, scrub=True)
        conn.close()

        json_str = json.dumps(data)
        # Real project names (derived from mock data) must not survive scrub
        assert "alpha" not in json_str.lower()
        assert "beta" not in json_str.lower()
        # Only the placeholder "project" should appear where project names were
        for entry in data.get("daily_project", []):
            assert entry["pj"] == "project"
        for entry in data.get("daily_project_tokens", []):
            assert entry["pj"] == "project"
        for ps in data.get("project_scores", []):
            assert ps["project"] == "project"
        for pce in data.get("project_cost_efficiency", []):
            assert pce["pj"] == "project"
