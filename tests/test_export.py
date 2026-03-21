"""Unit tests for the export module."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

import pytest

from clue.db import insert_prompts, insert_sessions, insert_turns
from clue.export import (
    _compute_prompt_learning,
    _compute_session_insights,
    _compute_weekly_digest,
    _estimate_cost,
    generate_dashboard_data,
)
from clue.models import ConversationTurn, Prompt, ScoringData, Session, SessionMetrics, TokenUsage


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
        assert data["schema_version"] == 6

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
        assert 0 <= score["overall"] <= 100
        assert score["grade"] in ("A", "B", "C", "D", "F")
        assert len(score["dimensions"]) == 7
        assert isinstance(score["top_recommendations"], list)

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
        assert data["agentic_cost_split"]["agent"] >= 0
        assert data["agentic_cost_split"]["main"] >= 0

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
        assert cc["cost"] >= 0
        assert 0 <= cc["pct"] <= 100
        assert cc["sessions"] >= 0

    def test_prompt_pattern_stats_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "prompt_pattern_stats" in data
        assert isinstance(data["prompt_pattern_stats"], list)
        if data["prompt_pattern_stats"]:
            ps = data["prompt_pattern_stats"][0]
            assert isinstance(ps["pattern"], str)
            assert ps["count"] > 0
            assert ps["avg_session_tokens"] >= 0

    def test_git_correlation_disabled_by_default(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "session_outcomes" not in data
        assert "time_to_value" not in data

    def test_session_insights_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "session_insights" in data
        si = data["session_insights"]
        assert "best_worst" in si
        assert "project_coaching" in si

    def test_weekly_digest_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "weekly_digest" in data
        wd = data["weekly_digest"]
        assert "has_data" in wd

    def test_prompt_learning_present(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert "prompt_learning" in data
        assert isinstance(data["prompt_learning"], list)

    def test_schema_version_6(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        assert data["schema_version"] == 6

    def test_daily_usage_sessions_are_counts(self, db_conn, sample_prompts, sample_turns):
        """daily_usage[*]['s'] must be session counts, not day flags."""
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = generate_dashboard_data(db_conn)
        total_sessions = sum(r["s"] for r in data["daily_usage"])
        # sample data has 1 session (session-001), so total must be 1
        assert total_sessions == 1

    def test_branch_coaching_cost_includes_all_token_types(self, db_conn, sample_prompts):
        """Branch cost must include input + output + cache tokens, not just output."""
        insert_prompts(db_conn, sample_prompts)
        turns_with_branch = [
            ConversationTurn(
                session_id="session-001",
                project="project-alpha",
                role="assistant",
                model="claude-sonnet-4-6",
                tool_name="Read",
                git_branch="feat/test-branch",
                usage=TokenUsage(
                    input_tokens=500_000,
                    output_tokens=100_000,
                    cache_creation_tokens=200_000,
                    cache_read_tokens=300_000,
                ),
            ),
        ]
        insert_turns(db_conn, turns_with_branch)
        data = generate_dashboard_data(db_conn)
        bc = data.get("branch_coaching", [])
        assert len(bc) >= 1
        branch = next(b for b in bc if b["branch"] == "feat/test-branch")
        # Output-only cost: 100k/1M * $15 = $1.50
        output_only_cost = _estimate_cost("_default", 0, 100_000, 0, 0)
        # Full cost must be strictly greater (input + cache tokens add cost)
        assert branch["est_cost"] > output_only_cost

    def test_prompt_pattern_stats_deduplicates_by_session(self, db_conn):
        """avg_session_tokens must average per unique session, not per prompt."""
        # Session A: 2 prompts, 10000 session tokens
        # Session B: 1 prompt, 4000 session tokens
        # Correct avg (2 sessions): (10000 + 4000) / 2 = 7000
        # Bug avg (3 prompts): (10000 + 10000 + 4000) / 3 = 8000
        prompts = [
            Prompt(
                timestamp=datetime(2025, 3, 21, 10, 0, tzinfo=timezone.utc),
                project="project-alpha",
                session_id="session-A",
                text="fix the login bug",
                char_length=17,
            ),
            Prompt(
                timestamp=datetime(2025, 3, 21, 10, 1, tzinfo=timezone.utc),
                project="project-alpha",
                session_id="session-A",
                text="add error handling",
                char_length=18,
            ),
            Prompt(
                timestamp=datetime(2025, 3, 21, 10, 2, tzinfo=timezone.utc),
                project="project-alpha",
                session_id="session-B",
                text="update the readme",
                char_length=17,
            ),
        ]
        turns = [
            ConversationTurn(
                session_id="session-A",
                project="project-alpha",
                role="assistant",
                model="claude-sonnet-4-6",
                tool_name="Read",
                usage=TokenUsage(
                    input_tokens=5000, output_tokens=5000,
                    cache_creation_tokens=0, cache_read_tokens=0,
                ),
            ),
            ConversationTurn(
                session_id="session-B",
                project="project-alpha",
                role="assistant",
                model="claude-sonnet-4-6",
                tool_name="Read",
                usage=TokenUsage(
                    input_tokens=2000, output_tokens=2000,
                    cache_creation_tokens=0, cache_read_tokens=0,
                ),
            ),
        ]
        insert_prompts(db_conn, prompts)
        insert_turns(db_conn, turns)
        data = generate_dashboard_data(db_conn)
        all_bucket = next(
            p for p in data["prompt_pattern_stats"] if p["pattern"] == "all"
        )
        # Deduped: (10000 + 4000) / 2 = 7000
        assert all_bucket["avg_session_tokens"] == 7000


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


class TestComputeSessionInsights:
    """Tests for _compute_session_insights helper."""

    def _make_metrics(self, count, **overrides):
        metrics = []
        for i in range(count):
            m = SessionMetrics(
                session_id=f"s{i}",
                project=overrides.get("project", "proj-a"),
                prompt_count=overrides.get("prompt_count", 10),
                turn_count=overrides.get("turn_count", 20),
                total_tokens=overrides.get("total_tokens", 5000),
                correction_count=overrides.get("correction_count", 1),
                read_count=overrides.get("read_count", 5),
                edit_count=overrides.get("edit_count", 3),
                has_read_before_edit=overrides.get("has_read_before_edit", True),
                tool_diversity=overrides.get("tool_diversity", 5),
                avg_prompt_length=overrides.get("avg_prompt_length", 80.0),
                file_ref_count=overrides.get("file_ref_count", 3),
                cost=overrides.get("cost", 0.50),
            )
            metrics.append(m)
        return metrics

    def test_returns_empty_with_few_sessions(self):
        data = ScoringData(session_metrics=self._make_metrics(3))
        result = _compute_session_insights(data, {}, [])
        assert result["best_worst"] is None
        assert result["project_coaching"] == []

    def test_best_worst_with_enough_sessions(self):
        """With 10+ costed sessions, should compute best/worst comparison."""
        metrics = []
        for i in range(12):
            m = SessionMetrics(
                session_id=f"s{i}",
                project="proj-a",
                prompt_count=10,
                turn_count=20,
                total_tokens=5000,
                cost=0.10 * (i + 1),  # varying costs
                avg_prompt_length=50.0 + i * 10,
                correction_count=i % 3,
                has_read_before_edit=i % 2 == 0,
                tool_diversity=3 + i % 3,
            )
            metrics.append(m)
        data = ScoringData(session_metrics=metrics)
        result = _compute_session_insights(data, {}, ["proj-a"])
        assert result["best_worst"] is not None
        assert "top10" in result["best_worst"]
        assert "bottom10" in result["best_worst"]
        top = result["best_worst"]["top10"]
        assert "avg_prompt_length" in top
        assert "avg_turns" in top
        assert "correction_rate" in top

    def test_project_coaching_with_enough_data(self):
        """Per-project coaching with 3+ sessions per project."""
        metrics_a = self._make_metrics(4, project="proj-a", cost=0.30)
        metrics_b = self._make_metrics(4, project="proj-b", cost=0.80)
        for i, m in enumerate(metrics_b):
            m.session_id = f"b{i}"
        data = ScoringData(session_metrics=metrics_a + metrics_b)
        result = _compute_session_insights(
            data, {}, ["proj-a", "proj-b"],
        )
        assert len(result["project_coaching"]) == 2
        # Sorted by cost desc — proj-b should be first
        assert result["project_coaching"][0]["project"] == "proj-b"
        coaching = result["project_coaching"][0]
        assert "sessions" in coaching
        assert "correction_rate" in coaching
        assert "cost_per_session" in coaching


class TestComputeWeeklyDigest:
    """Tests for _compute_weekly_digest helper."""

    def test_empty_db(self, db_conn):
        cur = db_conn.cursor()
        result = _compute_weekly_digest(cur, 0.0)
        assert result == {"has_data": False}

    def test_with_data(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        cur = db_conn.cursor()
        result = _compute_weekly_digest(cur, 1.50)
        assert result["has_data"] is True
        assert "this_week" in result
        assert "last_week" in result
        tw = result["this_week"]
        assert "prompts" in tw
        assert "sessions" in tw
        assert "avg_prompt_length" in tw
        assert "cost" in tw

    def test_last_week_zeros_when_no_prior_data(self, db_conn, sample_prompts):
        """If all data is in one week, last_week should be zeros."""
        insert_prompts(db_conn, sample_prompts)
        cur = db_conn.cursor()
        result = _compute_weekly_digest(cur, 0.50)
        assert result["has_data"] is True
        lw = result["last_week"]
        assert lw["prompts"] == 0


class TestComputePromptLearning:
    """Tests for _compute_prompt_learning helper."""

    def test_empty_db(self, db_conn):
        cur = db_conn.cursor()
        result = _compute_prompt_learning(cur)
        assert result == []

    def test_with_correction_patterns(self, db_conn):
        """Prompts followed by corrections should be counted."""
        prompts = []
        texts = [
            "fix the bug in src/auth.py",
            "no, wrong file",
            "look at config.yml line 10",
            "try again",
            "update the README.md",
            "add tests for login.py",
            "wrong approach",
            "refactor the payment module with proper error handling",
            "check src/utils.py for the helper function",
            "actually, use the other method",
            "deploy the changes to staging",
        ]
        for i, text in enumerate(texts):
            prompts.append(Prompt(
                timestamp=datetime(2025, 3, 21, 10, i, tzinfo=timezone.utc),
                project="proj-a",
                session_id="s1",
                text=text,
                char_length=len(text),
            ))
        insert_prompts(db_conn, prompts)
        cur = db_conn.cursor()
        result = _compute_prompt_learning(cur)
        # With 11 prompts, some patterns may have >=5 entries
        assert isinstance(result, list)
        # Each entry has expected keys
        for entry in result:
            assert "pattern" in entry
            assert "count" in entry
            assert "correction_rate" in entry
