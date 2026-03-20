"""Data models for Claude Code telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Prompt:
    """A single user prompt from history.jsonl."""

    timestamp: datetime
    project: str
    session_id: str
    text: str
    char_length: int


@dataclass
class TokenUsage:
    """Token counts from a single API response."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class ConversationTurn:
    """A single turn (user or assistant) in a conversation."""

    session_id: str
    project: str
    role: str  # "user" | "assistant"
    timestamp: str | None = None
    model: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    tool_name: str | None = None
    text_length: int = 0
    is_subagent: bool = False
    cwd: str | None = None
    git_branch: str | None = None
    claude_version: str | None = None
    stop_reason: str | None = None


@dataclass
class Session:
    """A Claude Code session."""

    session_id: str
    project: str
    started_at: datetime | None = None
    prompt_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    models_used: set[str] = field(default_factory=set)
    tools_used: dict[str, int] = field(default_factory=dict)
    turn_count: int = 0


# --- Scoring models ---


@dataclass
class DimensionScore:
    """A single dimension of the efficiency score."""

    name: str
    score: float  # 0-100
    weight: float
    grade: str  # A/B/C/D/F
    explanation: str
    recommendations: list[str] = field(default_factory=list)


@dataclass
class EfficiencyScore:
    """Composite AI usage efficiency score."""

    overall: float  # 0-100
    grade: str  # A+/A/B/C/D/F
    dimensions: list[DimensionScore] = field(default_factory=list)
    top_recommendations: list[str] = field(default_factory=list)
    trend: str = "stable"  # "improving" | "declining" | "stable"
    trend_delta: float = 0.0  # change from previous period


@dataclass
class ProjectScore:
    """Efficiency score scoped to a single project."""

    project: str
    score: EfficiencyScore = field(default_factory=lambda: EfficiencyScore(overall=0, grade="N/A"))
    prompt_count: int = 0
    token_count: int = 0
    session_count: int = 0


# --- Scorer input models ---


@dataclass
class ScoringData:
    """Pre-queried data for the scoring engine. No database dependency."""

    prompt_lengths: list[int] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    session_count: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    prompts_per_session: list[int] = field(default_factory=list)
    model_calls: dict[str, int] = field(default_factory=dict)
    model_output_tokens: dict[str, int] = field(default_factory=dict)
    # Enhanced scoring signals
    prompt_texts: list[str] = field(default_factory=list)
    turns_per_session: list[int] = field(default_factory=list)
    unique_tools_per_session: list[int] = field(default_factory=list)


@dataclass
class TrendData:
    """Pre-queried data for trend computation."""

    recent_avg_length: float = 0.0
    prior_avg_length: float = 0.0
    has_data: bool = False


# --- Pricing ---

MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.0,
        "cache_write": 1.0,
        "cache_read": 0.08,
    },
    "_default": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
}
