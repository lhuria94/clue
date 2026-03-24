#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# CLUEI bootstrap for macOS / Linux
#
# What this does:
#   1. Finds Python 3.10+ (or tells you how to install it)
#   2. Creates a virtual environment
#   3. Installs CLUEI + test deps (zero external deps)
#   4. Optionally installs Taskfile (go-task)
#   5. Runs full test suite
#   6. Runs doctor (validates all prerequisites)
#   7. Runs setup (extract data + install hook + print score)
#
# Usage:
#   git clone <repo-url> && cd cluei && ./setup.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
RESET='\033[0m'

ok()   { printf "  ${GREEN}[OK]${RESET}   %s\n" "$*"; }
warn() { printf "  ${YELLOW}[WARN]${RESET} %s\n" "$*"; }
fail() { printf "  ${RED}[FAIL]${RESET} %s\n" "$*"; }
info() { printf "  ${CYAN}[..]${RESET}   %s\n" "$*"; }
step() { printf "\n${BOLD}── %s${RESET}\n" "$*"; }

printf "\n${BOLD}CLUEI${RESET} — Code Leverage, Usage & Efficiency Index\n"
echo "═══════════════════════════════════════════════════════"

# ── Locate project root ───────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "src/clue/__main__.py" ]; then
    fail "Cannot find CLUEI source. Run from the project root."
    exit 1
fi

# ── Step 1: Find Python 3.10+ ─────────────────────────────────
step "Python"

PYTHON=""
for cmd in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || echo "0.0")
        major="${ver%%.*}"
        minor="${ver#*.}"
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.10+ not found"
    echo ""
    echo "  Install Python:"
    echo "    macOS:          brew install python@3.12"
    echo "    Ubuntu/Debian:  sudo apt install python3.12 python3.12-venv"
    echo "    Fedora:         sudo dnf install python3.12"
    echo "    Arch:           sudo pacman -S python"
    echo ""
    exit 1
fi

PYTHON_VER=$("$PYTHON" --version)
ok "Found ${PYTHON_VER} at $(command -v $PYTHON)"

# Verify venv module
if ! "$PYTHON" -c "import venv" &>/dev/null; then
    fail "Python venv module missing"
    echo "    Ubuntu/Debian: sudo apt install python3-venv"
    echo "    Fedora:        sudo dnf install python3-venv"
    exit 1
fi
ok "venv module available"

# Verify sqlite3 module
if ! "$PYTHON" -c "import sqlite3" &>/dev/null; then
    fail "Python sqlite3 module missing (should be stdlib)"
    exit 1
fi
ok "sqlite3 module available"

# ── Step 2: Virtual environment ────────────────────────────────
step "Virtual Environment"

VENV=".venv"
if [ -d "$VENV" ]; then
    ok "Already exists at ${VENV}/"
else
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV"
    ok "Created ${VENV}/"
fi

VENV_PYTHON="${VENV}/bin/python"
VENV_PIP="${VENV}/bin/pip"

# ── Step 3: Install package ───────────────────────────────────
step "Install"

info "Installing CLUEI + dev tools..."
if "$VENV_PIP" install --quiet -e ".[test,dev]" 2>&1; then
    ok "Installed CLUEI $(${VENV_PYTHON} -c 'from clue import __version__; print(__version__)')"
else
    fail "pip install failed — check your network connection and try again"
    exit 1
fi

# ── Step 4: Claude Code data ──────────────────────────────────
step "Claude Code Data"

CLAUDE_DIR="${HOME}/.claude"
if [ -d "$CLAUDE_DIR" ]; then
    ok "Found ~/.claude/"
    if [ -f "${CLAUDE_DIR}/history.jsonl" ]; then
        PROMPT_COUNT=$(wc -l < "${CLAUDE_DIR}/history.jsonl" | tr -d ' ')
        ok "history.jsonl: ${PROMPT_COUNT} prompts"
    else
        warn "No history.jsonl — use Claude Code at least once"
    fi
    CONV_COUNT=$(find "${CLAUDE_DIR}/projects" -name "*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
    ok "Conversation files: ${CONV_COUNT}"
else
    warn "~/.claude/ not found — install Claude Code:"
    echo "    npm install -g @anthropic-ai/claude-code"
fi

# ── Step 5: Taskfile (optional) ───────────────────────────────
step "Taskfile (optional)"

if command -v task &>/dev/null; then
    TASK_VER=$(task --version 2>/dev/null || echo "unknown")
    ok "Taskfile installed: ${TASK_VER}"
else
    warn "Taskfile not installed — installing is optional"
    echo ""
    echo "    Taskfile provides shortcuts (task dashboard, task score, etc.)"
    echo "    Without it, use: ${VENV_PYTHON} -m clue <command>"
    echo ""
    echo "    Install Taskfile:"
    echo "      macOS:   brew install go-task"
    echo "      Linux:   sh -c \"\$(curl --location https://taskfile.dev/install.sh)\" -- -d -b /usr/local/bin"
    echo "      Windows: winget install Task.Task"
    echo "      Or:      https://taskfile.dev/installation/"
    echo ""
    read -rp "    Install Taskfile now? [y/N] " INSTALL_TASK
    if [[ "$INSTALL_TASK" =~ ^[Yy] ]]; then
        if command -v brew &>/dev/null; then
            brew install go-task
            ok "Installed via Homebrew"
        else
            sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin 2>/dev/null
            ok "Installed to /usr/local/bin/task"
        fi
    fi
fi

# ── Step 6: Tests ─────────────────────────────────────────────
step "Tests"

info "Running test suite..."
TEST_OUTPUT=$("${VENV}/bin/pytest" tests/ -q --tb=line 2>&1) || true
PASS_LINE=$(echo "$TEST_OUTPUT" | tail -1)
if echo "$PASS_LINE" | grep -q "passed"; then
    ok "$PASS_LINE"
else
    warn "$PASS_LINE"
fi

# ── Step 7: Doctor ────────────────────────────────────────────
step "Doctor (prerequisite validation)"

"$VENV_PYTHON" -m clue doctor || true

# ── Step 8: Setup (extract + hook + score) ────────────────────
step "Setup"

if [ -d "$CLAUDE_DIR" ] && [ -f "${CLAUDE_DIR}/history.jsonl" ]; then
    "$VENV_PYTHON" -m clue setup
else
    warn "Skipping setup — no Claude Code data yet"
    echo "    After using Claude Code, run: ${VENV_PYTHON} -m clue setup"
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
printf "${BOLD}Ready!${RESET} Commands:\n"
echo ""
if command -v task &>/dev/null; then
    echo "  task dashboard          # Open interactive dashboard"
    echo "  task score              # Print efficiency score"
    echo "  task test               # Run test suite"
    echo "  task export             # Export for team sharing"
    echo "  task doctor             # Validate prerequisites"
    echo "  task                    # List all tasks"
else
    ABS_PYTHON="$(cd "$(dirname "$VENV_PYTHON")" && pwd)/$(basename "$VENV_PYTHON")"
    echo "  ${ABS_PYTHON} -m clue dashboard"
    echo "  ${ABS_PYTHON} -m clue score"
    echo "  ${ABS_PYTHON} -m clue doctor"
fi
echo ""
