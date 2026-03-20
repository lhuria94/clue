"""Unit tests for the git_utils module."""

from __future__ import annotations

import subprocess

import pytest

from clue.git_utils import (
    classify_session,
    get_available_repos,
    get_commits_in_range,
    get_session_commits,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo with known commits."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )

    # Create a commit with a known date
    test_file = repo / "test.py"
    test_file.write_text("# initial")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial commit"],
        capture_output=True,
        check=True,
        env={
            **subprocess.os.environ,
            "GIT_AUTHOR_DATE": "2025-03-21T10:30:00+00:00",
            "GIT_COMMITTER_DATE": "2025-03-21T10:30:00+00:00",
        },
    )

    # Second commit
    test_file.write_text("# updated")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "fix login bug"],
        capture_output=True,
        check=True,
        env={
            **subprocess.os.environ,
            "GIT_AUTHOR_DATE": "2025-03-21T11:00:00+00:00",
            "GIT_COMMITTER_DATE": "2025-03-21T11:00:00+00:00",
        },
    )

    return repo


class TestGetAvailableRepos:
    def test_finds_repo(self, git_repo):
        repos = get_available_repos([str(git_repo)])
        assert str(git_repo) in repos

    def test_finds_repo_from_subdir(self, git_repo):
        subdir = git_repo / "src"
        subdir.mkdir()
        repos = get_available_repos([str(subdir)])
        assert str(git_repo) in repos

    def test_deduplicates(self, git_repo):
        subdir = git_repo / "src"
        subdir.mkdir()
        repos = get_available_repos([str(git_repo), str(subdir)])
        assert len(repos) == 1

    def test_empty_cwd(self):
        repos = get_available_repos(["", None])
        assert repos == []

    def test_nonexistent_path(self):
        repos = get_available_repos(["/nonexistent/path/xyz"])
        assert repos == []


class TestGetCommitsInRange:
    def test_finds_commits_in_range(self, git_repo):
        commits = get_commits_in_range(
            str(git_repo),
            after="2025-03-21T10:00:00+00:00",
            before="2025-03-21T12:00:00+00:00",
        )
        assert len(commits) == 2
        assert commits[0]["message"] == "fix login bug"  # Most recent first
        assert commits[1]["message"] == "initial commit"

    def test_narrow_range(self, git_repo):
        commits = get_commits_in_range(
            str(git_repo),
            after="2025-03-21T10:45:00+00:00",
            before="2025-03-21T11:30:00+00:00",
        )
        assert len(commits) == 1
        assert commits[0]["message"] == "fix login bug"

    def test_empty_range(self, git_repo):
        commits = get_commits_in_range(
            str(git_repo),
            after="2025-03-22T00:00:00+00:00",
            before="2025-03-23T00:00:00+00:00",
        )
        assert commits == []

    def test_nonexistent_repo(self):
        commits = get_commits_in_range(
            "/nonexistent/repo",
            after="2025-01-01",
            before="2025-12-31",
        )
        assert commits == []

    def test_commit_has_required_fields(self, git_repo):
        commits = get_commits_in_range(
            str(git_repo),
            after="2025-03-21T10:00:00+00:00",
            before="2025-03-21T12:00:00+00:00",
        )
        for c in commits:
            assert "sha" in c
            assert "timestamp" in c
            assert "message" in c
            assert len(c["sha"]) == 40  # Full SHA


class TestGetSessionCommits:
    def test_finds_session_commits(self, git_repo):
        commits = get_session_commits(
            str(git_repo),
            session_start="2025-03-21T10:00:00Z",
            session_end="2025-03-21T11:30:00Z",
        )
        assert len(commits) == 2

    def test_with_buffer(self, git_repo):
        # Session ends at 10:56, buffer of 5 min should catch 11:00 commit
        commits = get_session_commits(
            str(git_repo),
            session_start="2025-03-21T10:00:00Z",
            session_end="2025-03-21T10:56:00Z",
            buffer_minutes=5,
        )
        assert len(commits) == 2

    def test_no_end_time_uses_2h_window(self, git_repo):
        commits = get_session_commits(
            str(git_repo),
            session_start="2025-03-21T10:00:00Z",
        )
        assert len(commits) == 2

    def test_invalid_timestamp(self):
        commits = get_session_commits("/tmp", session_start="not-a-date")
        assert commits == []


class TestClassifySession:
    def test_productive(self):
        assert classify_session(commit_count=2, turn_count=10) == "productive"

    def test_exploratory(self):
        assert classify_session(commit_count=0, turn_count=15) == "exploratory"

    def test_abandoned(self):
        assert classify_session(commit_count=0, turn_count=3) == "abandoned"

    def test_single_commit_productive(self):
        assert classify_session(commit_count=1, turn_count=1) == "productive"

    def test_boundary_exploratory(self):
        assert classify_session(commit_count=0, turn_count=6) == "exploratory"

    def test_boundary_abandoned(self):
        assert classify_session(commit_count=0, turn_count=5) == "abandoned"
