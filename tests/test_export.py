"""Unit tests for the export module."""

from __future__ import annotations

import subprocess

import pytest

from clue.db import insert_prompts, insert_sessions, insert_turns
from clue.export import _estimate_cost, generate_dashboard_data
from clue.models import Session


class TestEstimateCost:
    def test_sonnet_cost(self):
        cost = _estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000, 0, 0)
        assert cost == 3.0 + 15.0  # $3/M input + $15/M output

    def test_opus_cost(self):
        cost = _estimate_cost("claude-opus-4-6", 1_000_000, 1_000_000, 0, 0)
        assert cost == 15.0 + 75.0

    def test_unknown_model_uses_default(self):
        cost = _estimate_cost("claude-unknown-99", 1_000_000, 0, 0, 0)
        assert cost == 3.0  # Default = Sonnet pricing

    def test_cache_pricing(self):
        cost = _estimate_cost("claude-sonnet-4-6", 0, 0, 1_000_000, 1_000_000)
        assert cost == 3.75 + 0.30


class TestGenerateDashboardData:
    def test_empty_db(self, db_conn):
        data = generate_dashboard_data(db_conn)
        assert data["overview"]["total_prompts"] == 0
        assert data["overview"]["total_tokens"] == 0
        assert "efficiency_score" in data
        assert "project_scores" in data
        assert data["schema_version"] == 5

    def test_with_data(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)

        assert data["overview"]["total_prompts"] == 3
        assert data["overview"]["total_input_tokens"] == 1600
        assert data["overview"]["total_output_tokens"] == 450
        assert len(data["daily_usage"]) >= 1
        assert len(data["model_totals"]) >= 1
        # daily_tools/daily_models require timestamps on turns (covered by integration tests)
        assert "daily_tools" in data
        assert "daily_models" in data

    def test_efficiency_score_included(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)

        score = data["efficiency_score"]
        assert "overall" in score
        assert "grade" in score
        assert "dimensions" in score
        assert "top_recommendations" in score
        assert len(score["dimensions"]) == 7

    def test_project_scores_included(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)

        assert len(data["project_scores"]) >= 1
        ps = data["project_scores"][0]
        assert "project" in ps
        assert "score" in ps
        assert "grade" in ps

    def test_user_label(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn, user_label="alice")
        assert data["user_label"] == "alice"

    def test_scrub_mode(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn, scrub=True)
        # Scrub mode should still produce valid data
        assert "overview" in data
        assert "efficiency_score" in data

    def test_hourly_distribution_complete(self, db_conn, sample_prompts):
        insert_prompts(db_conn, sample_prompts)
        data = generate_dashboard_data(db_conn)
        assert len(data["hourly_distribution"]) == 24

    def test_day_of_week_distribution_complete(self, db_conn, sample_prompts):
        insert_prompts(db_conn, sample_prompts)
        data = generate_dashboard_data(db_conn)
        assert len(data["day_of_week_distribution"]) == 7

    def test_prompt_lengths_present(self, db_conn, sample_prompts):
        insert_prompts(db_conn, sample_prompts)
        data = generate_dashboard_data(db_conn)
        assert len(data["prompt_lengths"]) >= 1
        assert "d" in data["prompt_lengths"][0]
        assert "l" in data["prompt_lengths"][0]

    def test_stop_reason_totals_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "stop_reason_totals" in data
        assert "daily_stop_reasons" in data
        assert isinstance(data["stop_reason_totals"], list)

    def test_agentic_data_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "daily_agentic" in data
        assert "agentic_cost_split" in data
        assert "agent" in data["agentic_cost_split"]
        assert "main" in data["agentic_cost_split"]

    def test_project_cost_efficiency_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "project_cost_efficiency" in data
        assert isinstance(data["project_cost_efficiency"], list)

    def test_correction_cost_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "correction_cost" in data
        cc = data["correction_cost"]
        assert "cost" in cc
        assert "pct" in cc
        assert "sessions" in cc

    def test_prompt_pattern_stats_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "prompt_pattern_stats" in data
        assert isinstance(data["prompt_pattern_stats"], list)
        if data["prompt_pattern_stats"]:
            ps = data["prompt_pattern_stats"][0]
            assert "pattern" in ps
            assert "count" in ps
            assert "avg_session_tokens" in ps

    def test_git_correlation_disabled_by_default(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "session_outcomes" not in data
        assert "time_to_value" not in data


class TestGitCorrelation:
    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a temporary git repo with a known commit."""
        repo = tmp_path / "test-repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@t.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "T"],
            capture_output=True, check=True,
        )
        (repo / "f.py").write_text("# code")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"],
            capture_output=True, check=True,
            env={
                **subprocess.os.environ,
                "GIT_AUTHOR_DATE": "2025-03-21T10:30:00+00:00",
                "GIT_COMMITTER_DATE": "2025-03-21T10:30:00+00:00",
            },
        )
        return repo

    def test_git_correlation_with_repo(
        self, db_conn, sample_prompts, sample_turns, git_repo,
    ):
        from datetime import datetime, timezone

        from clue.models import ConversationTurn, TokenUsage

        insert_prompts(db_conn, sample_prompts)
        # Insert turns with cwd pointing at git repo
        turns_with_cwd = [
            ConversationTurn(
                session_id="session-001",
                project="project-alpha",
                role="assistant",
                model="claude-sonnet-4-6",
                tool_name="Read",
                usage=TokenUsage(input_tokens=500, output_tokens=200),
                timestamp="2025-03-21T10:00:00.000Z",
                cwd=str(git_repo),
            ),
            ConversationTurn(
                session_id="session-001",
                project="project-alpha",
                role="assistant",
                model="claude-sonnet-4-6",
                tool_name="Edit",
                usage=TokenUsage(input_tokens=300, output_tokens=100),
                timestamp="2025-03-21T10:40:00.000Z",
                cwd=str(git_repo),
            ),
        ]
        insert_turns(db_conn, turns_with_cwd)
        # Insert a session
        insert_sessions(db_conn, [
            Session(
                session_id="session-001",
                project="project-alpha",
                started_at=datetime(2025, 3, 21, 10, 0, tzinfo=timezone.utc),
                prompt_count=3,
                total_input_tokens=800,
                total_output_tokens=300,
                turn_count=2,
            ),
        ])

        data = generate_dashboard_data(db_conn, git_correlation=True)

        assert "session_outcomes" in data
        assert "outcome_counts" in data
        assert "time_to_value" in data
        assert "git_repos_available" in data

        # Should find the repo and classify the session
        assert data["git_repos_available"] >= 1
        outcomes = data["session_outcomes"]
        assert len(outcomes) >= 1
        assert outcomes[0]["has_git"] is True
        assert outcomes[0]["outcome"] == "productive"  # commit found in window

    def test_git_correlation_no_repo(self, db_conn, sample_prompts, sample_turns):
        from datetime import datetime, timezone

        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        insert_sessions(db_conn, [
            Session(
                session_id="session-001",
                project="project-alpha",
                started_at=datetime(2025, 3, 21, 10, 0, tzinfo=timezone.utc),
                prompt_count=3,
                turn_count=3,
            ),
        ])

        data = generate_dashboard_data(db_conn, git_correlation=True)
        assert "session_outcomes" in data
        # Without git repo, sessions classified based on turn count only
        outcomes = data["session_outcomes"]
        if outcomes:
            assert outcomes[0]["has_git"] is False

    def test_git_correlation_empty_db(self, db_conn):
        data = generate_dashboard_data(db_conn, git_correlation=True)
        assert data["session_outcomes"] == []
        assert data["outcome_counts"] == {
            "productive": 0, "exploratory": 0, "abandoned": 0,
        }
        assert data["time_to_value"] == []
