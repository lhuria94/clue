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

# --- Security patterns ---

# Secrets/credentials in text (API keys, tokens, passwords)
SECRET_RE = re.compile(
    r"(?:"
    r"(?:api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|bearer|secret[_-]?key"
    r"|private[_-]?key|password|passwd|client[_-]?secret)"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/+=_-]{8,}"
    r"|['\"](?:sk|pk|rk|ak|AKIA|ghp|gho|ghs|ghr|github_pat|xox[bpsar]|glpat)"
    r"[-_A-Za-z0-9]{10,}['\"]"
    r")",
    re.I,
)

# Sensitive file paths — files that should not be read into AI context
SENSITIVE_FILE_RE = re.compile(
    r"(?:^|/|\s)(?:"
    r"\.env(?:\.\w+)?|\.env\.local|\.env\.production"
    r"|credentials\.(?:json|yaml|yml|xml|toml)"
    r"|\S*\.(?:pem|key|p12|pfx|jks|keystore)"
    r"|id_rsa|id_ed25519|id_ecdsa"
    r"|\.ssh/config|\.netrc|\.pgpass"
    r"|secrets\.(?:json|yaml|yml|toml)"
    r"|\.aws/credentials|\.boto"
    r"|kubeconfig|kube/config"
    r"|token\.json|service[_-]?account\S*\.json"
    r")(?:\s|$|['\"])",
    re.I,
)

# Dangerous shell commands
DANGEROUS_CMD_RE = re.compile(
    r"(?:"
    r"rm\s+-rf\s+/"  # rm -rf /
    r"|chmod\s+777"  # world-writable
    r"|curl\s+.*\|\s*(?:ba)?sh"  # curl pipe to shell
    r"|wget\s+.*\|\s*(?:ba)?sh"
    r"|--force\s+push|push\s+--force|push\s+-f"  # force push
    r"|dangerouslyDisableSandbox"  # sandbox bypass
    r"|eval\s*\("  # eval injection
    r"|> /dev/sd|dd\s+if=.*of=/dev/"  # disk overwrite
    r")",
    re.I,
)

# Prompt injection patterns — attempts to manipulate AI behaviour
PROMPT_INJECTION_RE = re.compile(
    r"(?:"
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"
    r"|disregard\s+(?:all\s+)?(?:previous|prior)\s+"
    r"|you\s+are\s+now\s+(?:a|an)\s+"  # role hijacking
    r"|new\s+system\s+prompt"
    r"|override\s+(?:your|the)\s+(?:instructions|rules|guidelines)"
    r"|forget\s+(?:all\s+)?(?:previous|prior|your)\s+(?:instructions|rules)"
    r"|act\s+as\s+(?:if\s+)?(?:you\s+(?:have|had)\s+)?no\s+(?:restrictions|limits)"
    r"|jailbreak"
    r"|DAN\s+mode"
    r"|bypass\s+(?:safety|content|ethical)\s+(?:filters?|guidelines?|restrictions?)"
    r")",
    re.I,
)

# Data exfiltration patterns — attempts to send data to external services
EXFILTRATION_RE = re.compile(
    r"(?:"
    r"curl\s+.*?-d\s+.*?(?:env|secret|key|token|password|credential)"
    r"|curl\s+.*?--data.*?(?:env|secret|key|token|password|credential)"
    r"|(?:wget|curl)\s+.*?(?:webhook|ngrok|requestbin|pipedream|hookbin)"
    r"|base64\s+.*?(?:\.env|credentials|\.key|\.pem)"
    r"|cat\s+.*?(?:\.env|credentials|\.key|\.pem).*?\|\s*(?:curl|nc|ncat)"
    r"|nc\s+-\w+\s+\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"  # netcat to IP
    r")",
    re.I,
)

# --- CLAUDE.md risk patterns ---

# Risky instructions in CLAUDE.md files: (compiled_re, category, description)
CLAUDE_MD_RISKS: list[tuple["re.Pattern[str]", str, str]] = [
    (re.compile(r"--no-verify", re.I),
     "hook_bypass", "CLAUDE.md instructs to use --no-verify"),
    (re.compile(r"dangerouslyDisableSandbox", re.I),
     "sandbox_bypass", "CLAUDE.md instructs to disable sandbox"),
    (re.compile(r"bypassPermissions|--dangerouslySkipPermissions", re.I),
     "wildcard_permissions", "CLAUDE.md instructs to bypass permissions"),
    (re.compile(r"(?:rm\s+-rf\s+/|chmod\s+0?777)", re.I),
     "dangerous_commands", "CLAUDE.md contains dangerous command patterns"),
    (re.compile(
        r"(?:api[_-]?key|secret[_-]?key|password)\s*[:=]\s*['\"]?\S{8,}", re.I),
     "secrets_in_prompts", "CLAUDE.md may contain hardcoded secrets"),
]

# Placeholder values to exclude from secret detection — common in AI code examples
PLACEHOLDER_SECRET_RE = re.compile(
    r"(?:your[_-]?(?:api[_-]?)?(?:key|token|secret|password)|"
    r"changeme|replace[_-]?me|example|placeholder|xxx+|test[_-]?key|"
    r"fake[_-]?(?:key|token)|dummy|sample|TODO|insert[_-]?here|"
    r"sk-(?:your|xxx|test|fake|dummy|example|placeholder))",
    re.I,
)
