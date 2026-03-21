"""Tests for CLI commands."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

from clue.cli import (
    cmd_digest,
    cmd_doctor,
    cmd_export,
    cmd_extract,
    cmd_merge,
    cmd_score,
    cmd_setup,
)


class _Args:
    """Minimal argparse.Namespace replacement for testing."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestCmdExtract:
    def test_full_extract(self, mock_claude_dir, tmp_path, capsys):
        args = _Args(
            claude_dir=str(mock_claude_dir),
            db=str(tmp_path / "test.db"),
            incremental=False,
        )
        cmd_extract(args)
        captured = capsys.readouterr()
        assert "Prompts:" in captured.out
        assert "Done." in captured.out

    def test_incremental_extract(self, mock_claude_dir, tmp_path, capsys):
        args = _Args(
            claude_dir=str(mock_claude_dir),
            db=str(tmp_path / "test.db"),
            incremental=False,
        )
        # First full extract
        cmd_extract(args)
        # Then incremental
        args.incremental = True
        cmd_extract(args)
        captured = capsys.readouterr()
        assert "incremental" in captured.out


class TestCmdExport:
    def test_export_json(self, mock_claude_dir, tmp_path, capsys):
        # First extract
        db_path = str(tmp_path / "test.db")
        cmd_extract(_Args(claude_dir=str(mock_claude_dir), db=db_path, incremental=False))

        # Then export
        output = str(tmp_path / "export.json")
        cmd_export(_Args(db=db_path, output=output, scrub=False, user_label=None))

        assert Path(output).exists()
        data = json.loads(Path(output).read_text())
        assert "overview" in data
        assert "efficiency_score" in data

    def test_export_with_scrub(self, mock_claude_dir, tmp_path, capsys):
        db_path = str(tmp_path / "test.db")
        cmd_extract(_Args(claude_dir=str(mock_claude_dir), db=db_path, incremental=False))

        output = str(tmp_path / "scrubbed.json")
        cmd_export(_Args(db=db_path, output=output, scrub=True, user_label="testuser"))

        data = json.loads(Path(output).read_text())
        assert data["user_label"] == "testuser"
        captured = capsys.readouterr()
        assert "scrubbed" in captured.out


class TestCmdMerge:
    def test_merge_two_files(self, mock_claude_dir, tmp_path, capsys):
        db_path = str(tmp_path / "test.db")
        cmd_extract(_Args(claude_dir=str(mock_claude_dir), db=db_path, incremental=False))

        # Export twice with different labels
        f1 = str(tmp_path / "alice.json")
        f2 = str(tmp_path / "bob.json")
        cmd_export(_Args(db=db_path, output=f1, scrub=False, user_label="alice"))
        cmd_export(_Args(db=db_path, output=f2, scrub=False, user_label="bob"))

        # Merge
        output = str(tmp_path / "team.json")
        cmd_merge(_Args(files=[f1, f2], output=output))

        merged = json.loads(Path(output).read_text())
        assert "alice" in merged["users"]
        assert "bob" in merged["users"]
        # Overview values should be doubled
        assert merged["overview"]["total_prompts"] == 10  # 5 * 2


class TestCmdDoctor:
    def test_doctor_with_data(self, mock_claude_dir, tmp_path, capsys):
        # Pre-populate database
        db_path = str(tmp_path / "test.db")
        cmd_extract(_Args(claude_dir=str(mock_claude_dir), db=db_path, incremental=False))

        # Create settings.json with a Stop hook
        settings_file = mock_claude_dir / "settings.json"
        settings_file.write_text(
            '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo ok"}]}]}}'
        )

        cmd_doctor(_Args(claude_dir=str(mock_claude_dir), db=db_path))
        captured = capsys.readouterr()
        assert "[OK]" in captured.out
        assert "Python >= 3.10" in captured.out
        assert "sqlite3 module" in captured.out

    def test_doctor_missing_data(self, tmp_path, capsys):
        with contextlib.suppress(SystemExit):
            cmd_doctor(_Args(claude_dir=str(tmp_path / "nonexistent"), db=str(tmp_path / "no.db")))
        captured = capsys.readouterr()
        assert "[FAIL]" in captured.out


class TestCmdScore:
    def test_prints_score(self, mock_claude_dir, tmp_path, capsys):
        db_path = str(tmp_path / "test.db")
        cmd_extract(_Args(claude_dir=str(mock_claude_dir), db=db_path, incremental=False))
        cmd_score(_Args(db=db_path))

        captured = capsys.readouterr()
        assert "AI Efficiency Score:" in captured.out
        assert "/100" in captured.out
        assert "Dimension Scores:" in captured.out


class TestCmdSetup:
    def test_setup_creates_hook(self, mock_claude_dir, tmp_path, capsys):
        # Create a settings.json
        settings_file = mock_claude_dir / "settings.json"
        settings_file.write_text("{}")

        db_path = str(tmp_path / "test.db")

        cmd_setup(
            _Args(
                claude_dir=str(mock_claude_dir),
                db=db_path,
            )
        )

        captured = capsys.readouterr()
        assert "Setup complete" in captured.out

        # Verify hook was written
        settings = json.loads(settings_file.read_text())
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]

    def test_setup_idempotent(self, mock_claude_dir, tmp_path, capsys):
        settings_file = mock_claude_dir / "settings.json"
        settings_file.write_text("{}")
        db_path = str(tmp_path / "test.db")

        cmd_setup(_Args(claude_dir=str(mock_claude_dir), db=db_path))
        cmd_setup(_Args(claude_dir=str(mock_claude_dir), db=db_path))

        settings = json.loads(settings_file.read_text())
        # Hook should only appear once
        stop_hooks = settings["hooks"]["Stop"]
        assert len(stop_hooks) == 1


class TestCmdDigest:
    def test_no_data(self, tmp_path, capsys):
        db_path = str(tmp_path / "no.db")
        with pytest.raises(SystemExit):
            cmd_digest(_Args(db=db_path))
        captured = capsys.readouterr()
        assert "No data" in captured.out

    def test_with_data(self, mock_claude_dir, tmp_path, capsys):
        db_path = str(tmp_path / "test.db")
        cmd_extract(_Args(claude_dir=str(mock_claude_dir), db=db_path, incremental=False))
        cmd_digest(_Args(db=db_path))
        captured = capsys.readouterr()
        # Should either print digest or "Not enough data"
        assert "Weekly Digest" in captured.out or "Not enough data" in captured.out
