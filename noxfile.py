"""Nox sessions for Clue — AI Efficiency Index for Engineering Teams."""

import nox

nox.options.default_venv_backend = "uv|virtualenv"
nox.options.sessions = ["lint", "test", "lint_imports"]


@nox.session(python=["3.14", "3.13", "3.12", "3.11", "3.10"])
def test(session: nox.Session) -> None:
    """Run test suite with coverage ratchet."""
    session.install("-e", ".[test]")
    session.run("pytest", *session.posargs)


@nox.session
def lint(session: nox.Session) -> None:
    """Lint with ruff."""
    session.install("ruff>=0.11")
    session.run("ruff", "check", "src", "tests", *session.posargs)


@nox.session
def format(session: nox.Session) -> None:
    """Format with ruff."""
    session.install("ruff>=0.11")
    session.run("ruff", "format", "src", "tests", *session.posargs)


@nox.session
def format_check(session: nox.Session) -> None:
    """Check formatting without modifying files."""
    session.install("ruff>=0.11")
    session.run("ruff", "format", "--check", "src", "tests")


@nox.session
def lint_imports(session: nox.Session) -> None:
    """Check architecture boundaries with import-linter."""
    session.install("-e", ".[dev]")
    session.run("lint-imports")
