"""Shared regex patterns for prompt analysis.

Used by scorer, export, and db modules. Single source of truth
to avoid drift between duplicate definitions.
"""

from __future__ import annotations

import re

# Correction/rephrase patterns — indicates the previous prompt wasn't clear enough
CORRECTION_RE = re.compile(
    r"(?i)^(?:no[,.\s]|not that|wrong|try again|undo|revert|actually[,\s]|I meant|"
    r"that's not|don'?t |stop |wait[,.\s]|instead[,.\s]|I said )",
)

# File/path references — indicates specificity
FILE_REF_RE = re.compile(
    r"(?:"
    r"[\w./\\-]+\.(?:py|js|ts|tsx|jsx|java|kt|go|rs|rb|php|c|cpp|h|cs|swift|"
    r"r|scala|lua|pl|ex|exs|hs|elm|vue|svelte|css|scss|less|html|xml|yml|yaml|"
    r"toml|json|md|sh|bash|zsh|sql|tf|hcl|proto|graphql|dockerfile)"
    r"|line\s+\d+"
    r"|:\d+(?::\d+)?"
    r")"
)

# Slash commands / skills
SLASH_CMD_RE = re.compile(r"^/\w+")

# Confirmation patterns — low-effort responses
CONFIRMATION_RE = re.compile(
    r"^(?:yes|ok|sure|y|yep|yeah|go|do it|proceed|continue|confirm)$", re.I
)
