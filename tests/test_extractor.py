"""Unit tests for the extractor module."""

from __future__ import annotations

from clue.extractor import (
    _project_from_dir_name,
    _short_project,
    build_sessions,
    extract_conversations,
    extract_prompts,
)


class TestShortProject:
    def test_unix_path(self):
        assert _short_project("/home/user/workspace/my-project") == "my-project"

    def test_windows_path(self):
        assert _short_project("C:\\Users\\dev\\repos\\my-app") == "my-app"

    def test_empty_string(self):
        assert _short_project("") == "unknown"

    def test_single_segment(self):
        assert _short_project("project") == "project"


class TestProjectFromDirName:
    def test_fallback_nonexistent_path(self):
        # When the path doesn't exist on disk, falls back to last segment
        assert _project_from_dir_name("-Users-dev-workspace-my-project") == "project"

    def test_fallback_short_name(self):
        assert _project_from_dir_name("-home-app") == "app"

    def test_single_segment(self):
        assert _project_from_dir_name("standalone") == "standalone"

    def test_empty_string(self):
        assert _project_from_dir_name("") == ""

    def test_no_leading_dash(self):
        assert _project_from_dir_name("no-dash") == "no-dash"

    def test_real_path_with_dashes(self, tmp_path):
        """Filesystem walk resolves ambiguous dashes in directory names."""
        # Create /tmp/.../workspace/my-cool-project/
        workspace = tmp_path / "workspace"
        project = workspace / "my-cool-project"
        project.mkdir(parents=True)
        # Encode as Claude would: replace / with -
        encoded = str(tmp_path).replace("/", "-") + "-workspace-my-cool-project"
        assert _project_from_dir_name(encoded) == "my-cool-project"

    def test_double_dash_hidden_dir(self, tmp_path):
        """Double-dash encodes dot-prefixed (hidden) directories."""
        hidden = tmp_path / ".config" / "tools"
        hidden.mkdir(parents=True)
        encoded = str(tmp_path).replace("/", "-") + "--config-tools"
        assert _project_from_dir_name(encoded) == "tools"

    def test_dot_joined_segment(self, tmp_path):
        """Dot-separated directory names (e.g. user.name) are resolved."""
        dotdir = tmp_path / "alice.smith"
        dotdir.mkdir()
        encoded = str(tmp_path).replace("/", "-") + "-alice-smith"
        assert _project_from_dir_name(encoded) == "alice.smith"


class TestExtractPrompts:
    def test_parses_history(self, mock_claude_dir):
        prompts = extract_prompts(mock_claude_dir)
        assert len(prompts) == 5
        assert prompts[0].text == "fix the login bug"
        assert prompts[0].project == "project-alpha"
        assert prompts[0].session_id == "session-001"
        assert prompts[0].char_length == 17

    def test_incremental_extraction(self, mock_claude_dir):
        _ = extract_prompts(mock_claude_dir)
        partial = extract_prompts(mock_claude_dir, since_line=3)
        assert len(partial) == 2
        assert partial[0].project == "project-beta"

    def test_missing_directory(self, tmp_path):
        prompts = extract_prompts(tmp_path / "nonexistent")
        assert prompts == []

    def test_empty_history(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "history.jsonl").write_text("")
        prompts = extract_prompts(claude_dir)
        assert prompts == []

    def test_malformed_line_skipped(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "history.jsonl").write_text(
            '{"bad json\n'
            '{"display":"good","timestamp":1711000000000,"project":"/x","sessionId":"s1"}\n'
        )
        prompts = extract_prompts(claude_dir)
        assert len(prompts) == 1
        assert prompts[0].text == "good"


class TestExtractConversations:
    def test_parses_all_turns(self, mock_claude_dir):
        turns = extract_conversations(mock_claude_dir)
        # 1 user + 1 assistant (Read tool) + 2 assistant (Edit+Bash) from main
        # + 1 user + 1 assistant from subagent
        # + 1 assistant from project-beta
        assert len(turns) >= 5

    def test_extracts_tool_names(self, mock_claude_dir):
        turns = extract_conversations(mock_claude_dir)
        tool_turns = [t for t in turns if t.tool_name]
        tool_names = {t.tool_name for t in tool_turns}
        assert "Read" in tool_names
        assert "Edit" in tool_names
        assert "Bash" in tool_names

    def test_subagent_flag(self, mock_claude_dir):
        turns = extract_conversations(mock_claude_dir)
        subagent_turns = [t for t in turns if t.is_subagent]
        assert len(subagent_turns) >= 1

    def test_extracts_new_fields(self, mock_claude_dir):
        turns = extract_conversations(mock_claude_dir)
        assistant_turns = [t for t in turns if t.role == "assistant" and t.cwd]
        assert any(t.cwd == "/home/user/project-alpha" for t in assistant_turns)
        assert any(t.git_branch == "fix/auth-bug" for t in assistant_turns)
        assert any(t.claude_version == "2.1.75" for t in assistant_turns)
        assert any(t.stop_reason == "tool_use" for t in assistant_turns)

    def test_token_usage(self, mock_claude_dir):
        turns = extract_conversations(mock_claude_dir)
        read_turn = next(t for t in turns if t.tool_name == "Read")
        assert read_turn.usage.input_tokens == 500
        assert read_turn.usage.output_tokens == 200
        assert read_turn.usage.cache_creation_tokens == 1000
        assert read_turn.usage.cache_read_tokens == 400

    def test_model_extraction(self, mock_claude_dir):
        turns = extract_conversations(mock_claude_dir)
        models = {t.model for t in turns if t.model}
        assert "claude-sonnet-4-6" in models
        assert "claude-haiku-4-5-20251001" in models
        assert "claude-opus-4-6" in models

    def test_changed_files_filter(self, mock_claude_dir):
        # Only parse one specific file
        projects_dir = mock_claude_dir / "projects"
        target = str(next((projects_dir / "-home-user-project-alpha").glob("*.jsonl")))
        turns = extract_conversations(mock_claude_dir, changed_files={target})
        assert all(t.project == "alpha" for t in turns)


class TestBuildSessions:
    def test_aggregates_correctly(self, sample_prompts, sample_turns):
        sessions = build_sessions(sample_prompts, sample_turns)
        assert len(sessions) == 1
        s = sessions[0]
        assert s.session_id == "session-001"
        assert s.prompt_count == 3
        assert s.turn_count == 3
        assert s.total_input_tokens == 1600
        assert s.total_output_tokens == 450
        assert "claude-sonnet-4-6" in s.models_used
        assert s.tools_used["Read"] == 1
        assert s.tools_used["Edit"] == 1

    def test_multiple_sessions(self, sample_prompts, sample_turns):
        from datetime import datetime, timezone

        from clue.models import ConversationTurn, Prompt, TokenUsage

        extra_prompt = Prompt(
            timestamp=datetime(2025, 3, 22, 10, 0, tzinfo=timezone.utc),
            project="project-beta",
            session_id="session-002",
            text="deploy",
            char_length=6,
        )
        extra_turn = ConversationTurn(
            session_id="session-002",
            project="project-beta",
            role="assistant",
            model="claude-opus-4-6",
            usage=TokenUsage(input_tokens=1000, output_tokens=500),
        )
        sessions = build_sessions(
            sample_prompts + [extra_prompt],
            sample_turns + [extra_turn],
        )
        assert len(sessions) == 2
