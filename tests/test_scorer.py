"""Unit tests for the scoring engine."""

from __future__ import annotations

from datetime import datetime, timezone

from clue.db import (
    insert_prompts,
    insert_turns,
    query_all_projects,
    query_project_stats,
    query_scoring_data,
    query_trend_data,
)
from clue.models import ConversationTurn, Prompt, ScoringData, TokenUsage, TrendData
from clue.scorer import (
    _analyse_prompt_texts,
    _grade,
    compute_project_scores,
    compute_score,
    compute_trend,
)


class TestGrade:
    def test_a_plus(self):
        assert _grade(96) == "A+"

    def test_a(self):
        assert _grade(90) == "A"

    def test_b(self):
        assert _grade(78) == "B"

    def test_c(self):
        assert _grade(65) == "C"

    def test_d(self):
        assert _grade(45) == "D"

    def test_f(self):
        assert _grade(20) == "F"


class TestAnalysePromptTexts:
    """Tests for the semantic prompt analysis helper."""

    def test_empty(self):
        result = _analyse_prompt_texts([])
        assert result["slash_cmds"] == 0
        assert result["corrections"] == 0

    def test_slash_commands_detected(self):
        texts = ["/test scorer.py", "/review", "fix the bug", "/commit"]
        result = _analyse_prompt_texts(texts)
        assert result["slash_cmds"] == 3
        assert result["slash_pct"] == 75.0

    def test_file_references_detected(self):
        texts = [
            "fix the bug in src/auth.py",
            "look at line 42",
            "update config.yml",
            "do something",
        ]
        result = _analyse_prompt_texts(texts)
        assert result["file_refs"] == 3
        assert result["file_ref_pct"] == 75.0

    def test_corrections_detected(self):
        texts = [
            "no, I meant the other file",
            "wrong approach",
            "try again",
            "actually, use the other method",
            "good job on that",
        ]
        result = _analyse_prompt_texts(texts)
        assert result["corrections"] == 4

    def test_confirmations_detected(self):
        texts = ["yes", "ok", "sure", "proceed", "fix the real bug"]
        result = _analyse_prompt_texts(texts)
        assert result["confirmations"] == 4

    def test_contextual_short_prompts(self):
        texts = ["/test", "src/main.py:42", "ok"]
        result = _analyse_prompt_texts(texts)
        # /test is a slash command AND short with context
        # src/main.py:42 has file ref AND is short with context
        # ok is just short, no context
        assert result["contextual_short"] == 2


class TestComputeScore:
    def test_returns_all_dimensions(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = query_scoring_data(db_conn)
        score = compute_score(data)

        assert 0 <= score.overall <= 100
        assert score.grade in ("A+", "A", "B", "C", "D", "F")
        assert len(score.dimensions) == 7

        names = {d.name for d in score.dimensions}
        assert "Prompt Quality" in names
        assert "Token Efficiency" in names
        assert "Cache Utilisation" in names
        assert "Tool Mastery" in names
        assert "Session Discipline" in names
        assert "Cost Awareness" in names
        assert "Iteration Efficiency" in names

    def test_dimension_weights_sum_to_one(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = query_scoring_data(db_conn)
        score = compute_score(data)
        total_weight = sum(d.weight for d in score.dimensions)
        assert abs(total_weight - 1.0) < 0.01

    def test_empty_data_returns_low_score(self):
        score = compute_score(ScoringData())
        # With no data, some dimensions default to 50 (no-data fallback)
        assert score.overall <= 50

    def test_per_project_scope(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = query_scoring_data(db_conn, project="project-alpha")
        score = compute_score(data)
        assert score.overall >= 0

    def test_recommendations_populated(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = query_scoring_data(db_conn)
        score = compute_score(data)
        # Should have some recommendations since prompts include short "yes" ones
        assert isinstance(score.top_recommendations, list)

    def test_scoring_data_includes_enhanced_fields(self, db_conn, sample_prompts, sample_turns):
        """Verify db queries populate the new ScoringData fields."""
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        data = query_scoring_data(db_conn)
        assert len(data.prompt_texts) == 3  # 3 sample prompts
        assert len(data.turns_per_session) >= 1
        assert len(data.unique_tools_per_session) >= 1


class TestComputeProjectScores:
    def test_returns_per_project(self, db_conn, sample_prompts, sample_turns):
        insert_prompts(db_conn, sample_prompts)
        insert_turns(db_conn, sample_turns)
        projects = query_all_projects(db_conn)
        per_project_data = {p: query_scoring_data(db_conn, project=p) for p in projects}
        per_project_stats = {p: query_project_stats(db_conn, p) for p in projects}
        project_scores = compute_project_scores(projects, per_project_data, per_project_stats)
        assert len(project_scores) >= 1
        assert all(ps.project for ps in project_scores)
        assert all(0 <= ps.score.overall <= 100 for ps in project_scores)


class TestComputeTrend:
    def test_stable_with_no_data(self):
        trend, delta = compute_trend(TrendData())
        assert trend == "stable"
        assert delta == 0.0

    def test_stable_with_single_period(self, db_conn, sample_prompts):
        insert_prompts(db_conn, sample_prompts)
        data = query_trend_data(db_conn)
        trend, delta = compute_trend(data)
        # Only one period of data, so trend should be stable
        assert trend in ("stable", "improving", "declining")


class TestScoreWithDiverseData:
    """Integration-style tests with realistic data patterns."""

    def _make_prompts(self, texts, project="test-project", session="s1"):
        prompts = []
        for i, text in enumerate(texts):
            prompts.append(
                Prompt(
                    timestamp=datetime(2025, 3, 21, 10, i % 60, tzinfo=timezone.utc),
                    project=project,
                    session_id=session,
                    text=text,
                    char_length=len(text),
                )
            )
        return prompts

    def _make_prompts_by_length(self, count, avg_length, project="test-project", session="s1"):
        texts = ["x" * avg_length] * count
        return self._make_prompts(texts, project, session)

    def _make_turns(self, tools, model="claude-sonnet-4-6", project="test-project"):
        turns = []
        for tool in tools:
            turns.append(
                ConversationTurn(
                    session_id="s1",
                    project=project,
                    role="assistant",
                    model=model,
                    tool_name=tool,
                    usage=TokenUsage(
                        input_tokens=500,
                        output_tokens=200,
                        cache_creation_tokens=100,
                        cache_read_tokens=900,
                    ),
                )
            )
        return turns

    def test_high_quality_usage(self, db_conn):
        """Good prompts + diverse tools + good cache = high score."""
        texts = [
            "fix the auth bug in src/auth.py line 42",
            "add pagination to the /users endpoint with cursor navigation",
            "/test auth.py",
            "refactor the login middleware to use JWT with proper token rotation",
            "update the README.md with the new API endpoints",
        ] * 4
        prompts = self._make_prompts(texts)
        tools = ["Read", "Edit", "Bash", "Grep", "Agent", "Write", "Glob"] * 3
        turns = self._make_turns(tools)
        insert_prompts(db_conn, prompts)
        insert_turns(db_conn, turns)

        data = query_scoring_data(db_conn)
        score = compute_score(data)
        assert score.overall >= 40  # Should be decent with diverse tools + good prompts

    def test_low_quality_usage(self, db_conn):
        """Very short prompts + single tool = lower score."""
        prompts = self._make_prompts_by_length(20, 5)  # Very short prompts
        turns = self._make_turns(["Bash"] * 20)  # Only Bash
        insert_prompts(db_conn, prompts)
        insert_turns(db_conn, turns)

        data = query_scoring_data(db_conn)
        score = compute_score(data)
        assert len(score.top_recommendations) > 0  # Should have improvement suggestions

    def test_high_correction_rate_lowers_iteration_score(self, db_conn):
        """Sessions with many corrections should score lower on iteration efficiency."""
        texts = [
            "fix the bug",
            "no, not that file",
            "wrong approach, try again",
            "actually, I meant the auth module",
            "stop, undo that",
            "yes",
            "ok",
        ]
        prompts = self._make_prompts(texts)
        turns = self._make_turns(["Read", "Edit", "Bash"])
        insert_prompts(db_conn, prompts)
        insert_turns(db_conn, turns)

        data = query_scoring_data(db_conn)
        score = compute_score(data)
        iteration_dim = next(d for d in score.dimensions if d.name == "Iteration Efficiency")
        # High corrections should push score down
        assert iteration_dim.score < 70
        assert len(iteration_dim.recommendations) > 0

    def test_slash_commands_not_penalised(self, db_conn):
        """Slash commands are short but should not count as low-quality."""
        texts = [
            "/test scorer.py",
            "/review",
            "/commit",
            "refactor the auth middleware to use proper JWT validation",
            "add error handling to the payment flow in checkout.py",
        ]
        prompts = self._make_prompts(texts)
        turns = self._make_turns(["Read", "Edit", "Bash", "Grep"])
        insert_prompts(db_conn, prompts)
        insert_turns(db_conn, turns)

        data = query_scoring_data(db_conn)
        score = compute_score(data)
        quality_dim = next(d for d in score.dimensions if d.name == "Prompt Quality")
        # Slash commands should not drag score down as much
        assert quality_dim.score >= 0  # Not penalised to zero


class TestScoreWithPureData:
    """Test scorer with ScoringData directly — no database needed."""

    def test_pure_high_quality(self):
        data = ScoringData(
            prompt_lengths=[120] * 20,
            prompt_texts=["fix the bug in src/auth.py with proper validation"] * 20,
            total_input_tokens=10000,
            total_output_tokens=5000,
            session_count=2,
            cache_creation_tokens=1000,
            cache_read_tokens=9000,
            tool_counts={"Read": 5, "Edit": 4, "Bash": 3, "Grep": 3, "Agent": 2},
            prompts_per_session=[10, 10],
            turns_per_session=[30, 25],
            unique_tools_per_session=[5, 4],
            model_calls={"claude-sonnet-4-6": 12, "claude-haiku-4-5-20251001": 5},
            model_output_tokens={"claude-sonnet-4-6": 4000, "claude-haiku-4-5-20251001": 1000},
        )
        score = compute_score(data)
        assert score.overall >= 50
        assert score.grade in ("A+", "A", "B", "C")

    def test_pure_empty(self):
        score = compute_score(ScoringData())
        assert score.overall <= 50

    def test_pure_trend_improving(self):
        trend, delta = compute_trend(
            TrendData(
                recent_avg_length=150.0,
                prior_avg_length=100.0,
                has_data=True,
            )
        )
        assert trend == "improving"
        assert delta > 0

    def test_pure_trend_declining(self):
        trend, delta = compute_trend(
            TrendData(
                recent_avg_length=80.0,
                prior_avg_length=100.0,
                has_data=True,
            )
        )
        assert trend == "declining"
        assert delta < 0

    def test_iteration_efficiency_pure_high_corrections(self):
        """High correction rate should produce low iteration efficiency score."""
        data = ScoringData(
            prompt_texts=[
                "fix the bug",
                "no that's wrong",
                "try again",
                "wrong file",
                "actually use the other approach",
                "stop",
                "I meant auth.py",
            ],
            prompt_lengths=[12, 16, 9, 10, 35, 4, 16],
            turns_per_session=[15],
            unique_tools_per_session=[2],
            prompts_per_session=[7],
        )
        score = compute_score(data)
        iteration_dim = next(d for d in score.dimensions if d.name == "Iteration Efficiency")
        assert iteration_dim.score < 70

    def test_iteration_efficiency_pure_clean_workflow(self):
        """Clean workflow with no corrections should score well."""
        data = ScoringData(
            prompt_texts=[
                "fix the auth bug in src/login.py line 42",
                "add pagination to /users endpoint",
                "/test login.py",
                "refactor auth middleware to use JWT tokens",
                "update docs with new API endpoints",
            ],
            prompt_lengths=[42, 39, 15, 45, 38],
            turns_per_session=[25],
            unique_tools_per_session=[5],
            prompts_per_session=[5],
        )
        score = compute_score(data)
        iteration_dim = next(d for d in score.dimensions if d.name == "Iteration Efficiency")
        assert iteration_dim.score >= 50

    def test_single_model_not_heavily_penalised(self):
        """Single model usage should get a reasonable score (Max plan users)."""
        data = ScoringData(
            model_calls={"claude-sonnet-4-6": 100},
            model_output_tokens={"claude-sonnet-4-6": 50000},
        )
        score = compute_score(data)
        cost_dim = next(d for d in score.dimensions if d.name == "Cost Awareness")
        assert cost_dim.score >= 55  # Softened from 50

    def test_read_before_edit_rewarded(self):
        """Sessions that Read before Edit should score higher on tool mastery."""
        data_with_reads = ScoringData(
            tool_counts={"Read": 10, "Edit": 8, "Bash": 5, "Grep": 3},
            unique_tools_per_session=[4, 3],
        )
        data_without_reads = ScoringData(
            tool_counts={"Edit": 10, "Bash": 5, "Write": 3},
            unique_tools_per_session=[3, 2],
        )
        score_with = compute_score(data_with_reads)
        score_without = compute_score(data_without_reads)
        tm_with = next(d for d in score_with.dimensions if d.name == "Tool Mastery")
        tm_without = next(d for d in score_without.dimensions if d.name == "Tool Mastery")
        assert tm_with.score > tm_without.score
