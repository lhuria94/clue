"""AI usage efficiency scoring engine.

Scores across 7 dimensions to produce a composite 0-100 score:
1. Prompt Quality       (20%) — Are prompts specific, structured, and context-rich?
2. Token Efficiency     (15%) — Value per token, turns-to-completion ratio
3. Cache Utilisation    (10%) — Cache hit rate, session continuity
4. Tool Mastery         (15%) — Diversity, effectiveness patterns, antipattern detection
5. Session Discipline   (10%) — Focused sessions, tool workflow within sessions
6. Cost Awareness       (10%) — Model selection appropriate to task complexity
7. Iteration Efficiency (20%) — Correction rate, first-attempt success, workflow quality

This module is infrastructure-free: it accepts pre-queried ScoringData/TrendData
and returns pure domain objects. All SQL lives in db.py.
"""

from __future__ import annotations

import re

from .models import DimensionScore, EfficiencyScore, ProjectScore, ScoringData, TrendData

# --- Prompt semantic analysis helpers ---

# Patterns that indicate high-quality short prompts (slash commands, skills)
_SLASH_CMD_RE = re.compile(r"^/\w+")

# File/path references — indicates specificity
_FILE_REF_RE = re.compile(
    r"(?:"
    r"[\w./\\-]+\.(?:py|js|ts|tsx|jsx|java|kt|go|rs|rb|css|html|yml|yaml|toml|json|md|sh|sql)"
    r"|line\s+\d+"
    r"|:\d+(?::\d+)?"
    r")"
)

# Correction/rephrase patterns — indicates the previous prompt wasn't clear enough
_CORRECTION_PATTERNS = re.compile(
    r"(?i)^(?:no[,.\s]|not that|wrong|try again|undo|revert|actually[,\s]|I meant|"
    r"that's not|don'?t |stop |wait[,.\s]|instead[,.\s]|I said )",
)

# Confirmation patterns — low-effort responses (reduce quality score)
_CONFIRMATION_RE = re.compile(
    r"^(?:yes|ok|sure|y|yep|yeah|go|do it|proceed|continue|confirm)$", re.I
)


def _analyse_prompt_texts(texts: list[str]) -> dict:
    """Analyse prompt texts for semantic quality signals.

    Returns dict with counts and percentages for various signal types.
    """
    total = len(texts)
    if total == 0:
        return {
            "slash_cmds": 0, "slash_pct": 0.0,
            "file_refs": 0, "file_ref_pct": 0.0,
            "corrections": 0, "correction_pct": 0.0,
            "confirmations": 0, "confirmation_pct": 0.0,
            "contextual_short": 0,
        }

    slash_cmds = sum(1 for t in texts if _SLASH_CMD_RE.match(t.strip()))
    file_refs = sum(1 for t in texts if _FILE_REF_RE.search(t))
    corrections = sum(1 for t in texts if _CORRECTION_PATTERNS.match(t.strip()))
    confirmations = sum(1 for t in texts if _CONFIRMATION_RE.match(t.strip()))
    # Short prompts that contain file refs or slash commands are high-quality
    contextual_short = sum(
        1 for t in texts
        if len(t) < 50 and (_SLASH_CMD_RE.match(t.strip()) or _FILE_REF_RE.search(t))
    )

    return {
        "slash_cmds": slash_cmds,
        "slash_pct": slash_cmds / total * 100,
        "file_refs": file_refs,
        "file_ref_pct": file_refs / total * 100,
        "corrections": corrections,
        "correction_pct": corrections / total * 100,
        "confirmations": confirmations,
        "confirmation_pct": confirmations / total * 100,
        "contextual_short": contextual_short,
    }


def _grade(score: float) -> str:
    if score >= 95:
        return "A+"
    if score >= 85:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _score_prompt_quality(data: ScoringData) -> DimensionScore:
    """Score prompt quality based on length distribution AND semantic signals.

    Semantic signals (new):
    - Slash commands: short but precise, should not be penalised
    - File/path references: indicates specificity regardless of length
    - Confirmation prompts: low-effort "yes"/"ok" responses
    """
    lengths = data.prompt_lengths
    weight = 0.20

    if not lengths:
        return DimensionScore(
            name="Prompt Quality",
            score=0,
            weight=weight,
            grade="N/A",
            explanation="No prompts found.",
            recommendations=["Start using Claude Code to generate data."],
        )

    total = len(lengths)
    avg_len = sum(lengths) / total
    signals = _analyse_prompt_texts(data.prompt_texts)

    # Penalise very short prompts, but EXCLUDE slash commands and file-ref short prompts
    very_short = sum(1 for length in lengths if length < 15)
    effective_short = max(0, very_short - signals["contextual_short"])
    effective_short_pct = effective_short / total * 100

    # Reward medium-length prompts (50-500 chars)
    good_range = sum(1 for length in lengths if 50 <= length <= 500)
    good_range_pct = good_range / total * 100

    # Reward long, detailed prompts (300+ chars)
    detailed = sum(1 for length in lengths if length > 300)
    detailed_pct = detailed / total * 100

    # Score components
    short_penalty = max(0, effective_short_pct - 20) * 1.0
    good_bonus = min(good_range_pct * 0.7, 40)
    detail_bonus = min(detailed_pct * 0.4, 15)
    avg_len_score = min(avg_len / 4, 25)

    # Semantic bonuses
    file_ref_bonus = min(signals["file_ref_pct"] * 0.3, 10)
    slash_bonus = min(signals["slash_pct"] * 0.2, 5)
    confirmation_penalty = min(signals["confirmation_pct"] * 0.3, 10)

    score = _clamp(
        50
        - short_penalty
        + good_bonus
        + detail_bonus
        + avg_len_score
        + file_ref_bonus
        + slash_bonus
        - confirmation_penalty
        - 50
    )

    recs = []
    if effective_short_pct > 30:
        recs.append(
            f"{effective_short_pct:.0f}% of prompts are under 15 chars (excluding commands). "
            "Be more specific — 'fix the auth bug in login.py line 42' beats 'fix it'."
        )
    if signals["confirmation_pct"] > 20:
        recs.append(
            f"{signals['confirmation_pct']:.0f}% of prompts are simple confirmations "
            "(yes/ok/sure). Give Claude clear instructions upfront to reduce back-and-forth."
        )
    if good_range_pct < 40:
        recs.append(
            f"Only {good_range_pct:.0f}% of prompts are in the 50-500 char sweet spot. "
            "Include context: what file, what behaviour, what you expect."
        )
    if signals["file_ref_pct"] < 15 and total > 20:
        recs.append(
            f"Only {signals['file_ref_pct']:.0f}% of prompts reference specific files. "
            "Including file paths and line numbers helps Claude find the right code faster."
        )
    if detailed_pct > 50:
        recs.append(
            "Over half your prompts are 300+ chars. Consider if some could be split into "
            "smaller, focused requests — Claude works best with clear, bounded tasks."
        )

    explanation_parts = [f"Avg {avg_len:.0f} chars, {good_range_pct:.0f}% in ideal range"]
    if signals["file_refs"] > 0:
        explanation_parts.append(f"{signals['file_ref_pct']:.0f}% with file refs")
    if signals["slash_cmds"] > 0:
        explanation_parts.append(f"{signals['slash_cmds']} slash commands")

    return DimensionScore(
        name="Prompt Quality",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=", ".join(explanation_parts) + ".",
        recommendations=recs,
    )


def _score_token_efficiency(data: ScoringData) -> DimensionScore:
    """Score token efficiency — value per token AND turns-to-completion.

    New signal: prompts-to-turns ratio measures how many human prompts are needed
    per AI turn. Lower ratio = Claude understood and delivered on fewer attempts.
    """
    total_input = data.total_input_tokens
    total_output = data.total_output_tokens
    sessions = data.session_count or 1
    weight = 0.15

    if total_input == 0:
        return DimensionScore(
            name="Token Efficiency",
            score=0,
            weight=weight,
            grade="N/A",
            explanation="No token data.",
            recommendations=[],
        )

    # Output/input ratio — higher means more value extracted
    oi_ratio = total_output / max(total_input, 1)

    # Tokens per session — lower is more focused
    tokens_per_session = (total_input + total_output) / sessions

    # NEW: Prompts-to-turns ratio (human efficiency signal)
    total_prompts = sum(data.prompts_per_session) if data.prompts_per_session else 0
    total_turns = sum(data.turns_per_session) if data.turns_per_session else 0
    prompt_turn_ratio = total_prompts / total_turns if total_turns > 0 else 1.0

    # Score: ideal ratio is 0.5-3.0 (Claude generates meaningful output)
    ratio_score = _clamp(oi_ratio * 25, 0, 30)

    # Score: penalise excessive tokens per session (>500K suggests thrashing)
    session_score = _clamp(40 - max(0, (tokens_per_session - 100_000) / 10_000), 0, 40)

    # NEW: Efficiency bonus — fewer human prompts per AI turn is better
    # Ideal prompt_turn_ratio is 0.2-0.5 (Claude does multiple tool calls per prompt)
    efficiency_bonus = _clamp(30 - prompt_turn_ratio * 30, 0, 30)

    score = _clamp(ratio_score + session_score + efficiency_bonus)

    recs = []
    if oi_ratio < 0.3:
        recs.append(
            f"Output/input ratio is {oi_ratio:.2f} — Claude is reading a lot but generating "
            "little. Consider pre-reading files yourself and providing focused context."
        )
    if tokens_per_session > 300_000:
        recs.append(
            f"Averaging {tokens_per_session / 1000:.0f}K tokens per session. "
            "Break complex tasks into smaller sessions to reduce context bloat."
        )
    if prompt_turn_ratio > 0.7 and total_turns > 10:
        recs.append(
            f"Prompt-to-turn ratio is {prompt_turn_ratio:.2f} — you're prompting frequently "
            "relative to Claude's actions. Give more complete instructions upfront so Claude "
            "can chain multiple tool calls per prompt."
        )

    return DimensionScore(
        name="Token Efficiency",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"Output/input ratio: {oi_ratio:.2f}, "
            f"{tokens_per_session / 1000:.0f}K tokens/session, "
            f"prompt/turn ratio: {prompt_turn_ratio:.2f}."
        ),
        recommendations=recs,
    )


def _score_cache_utilisation(data: ScoringData) -> DimensionScore:
    """Score cache utilisation — sustained sessions hit cache more.

    Enhanced with actionable recommendations for improving cache performance.
    """
    cache_create = data.cache_creation_tokens
    cache_read = data.cache_read_tokens
    cache_total = cache_create + cache_read
    weight = 0.10

    if cache_total == 0:
        return DimensionScore(
            name="Cache Utilisation",
            score=50,
            weight=weight,
            grade="C",
            explanation="No cache data available.",
            recommendations=[
                "Cache data improves with sustained, focused sessions. "
                "Use CLAUDE.md files to front-load project context so Claude reads less per turn."
            ],
        )

    hit_rate = cache_read / cache_total * 100

    # Higher hit rate = better. 90%+ is excellent, <50% is poor.
    score = _clamp(hit_rate * 1.05)  # Slight bonus to make 95% = ~100

    recs = []
    if hit_rate < 70:
        recs.append(
            f"Cache hit rate is {hit_rate:.0f}%. You may be context-switching too often. "
            "Stay in one project/session longer to benefit from prompt caching."
        )
    if hit_rate < 50:
        recs.append(
            "Very low cache hit rate suggests many short, disconnected sessions. "
            "Batch related questions into single sessions."
        )
    if hit_rate >= 70 and cache_create > cache_read:
        recs.append(
            "More cache tokens are being created than read. Add a CLAUDE.md to your project "
            "root — it front-loads context and boosts cache reuse across turns."
        )

    return DimensionScore(
        name="Cache Utilisation",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"Cache hit rate: {hit_rate:.1f}% ({cache_read:,} read / {cache_total:,} total)."
        ),
        recommendations=recs,
    )


def _score_tool_mastery(data: ScoringData) -> DimensionScore:
    """Score tool usage diversity, effectiveness, and antipatterns.

    Enhanced signals:
    - Per-session tool diversity (not just global)
    - Read-before-Edit workflow detection
    - Bash-for-read antipattern
    """
    tools = data.tool_counts
    weight = 0.15

    if not tools:
        return DimensionScore(
            name="Tool Mastery",
            score=0,
            weight=weight,
            grade="N/A",
            explanation="No tool usage data.",
            recommendations=["Tools enable Claude to read, edit, and test code autonomously."],
        )

    total_uses = sum(tools.values())
    unique_tools = len(tools)

    # Diversity score — using more tools = more sophisticated usage
    diversity_score = min(unique_tools * 5, 35)

    # Balanced usage — penalise if one tool dominates >70%
    top_tool_pct = max(tools.values()) / total_uses * 100
    balance_score = _clamp(30 - max(0, top_tool_pct - 40) * 0.7, 0, 30)

    # Sophistication — reward Agent, Edit, Write usage (not just Read/Bash)
    sophisticated_tools = {"Agent", "Edit", "Write", "Grep", "NotebookEdit"}
    sophisticated_uses = sum(tools.get(t, 0) for t in sophisticated_tools)
    sophistication_score = min(sophisticated_uses / max(total_uses, 1) * 30, 15)

    # NEW: Per-session tool diversity — are sessions using varied tools?
    session_tools = data.unique_tools_per_session
    if session_tools:
        avg_session_diversity = sum(session_tools) / len(session_tools)
        session_diversity_bonus = min(avg_session_diversity * 3, 10)
    else:
        avg_session_diversity = 0
        session_diversity_bonus = 0

    # NEW: Read→Edit workflow — reward sessions that read before editing
    read_count = tools.get("Read", 0)
    edit_count = tools.get("Edit", 0) + tools.get("Write", 0)
    if edit_count > 0 and read_count >= edit_count:
        workflow_bonus = 10  # Good practice: reading before editing
    elif edit_count > 0 and read_count > 0:
        workflow_bonus = 5
    else:
        workflow_bonus = 0

    score = _clamp(
        diversity_score + balance_score + sophistication_score
        + session_diversity_bonus + workflow_bonus
    )

    recs = []
    if unique_tools < 5:
        recs.append(
            f"Only using {unique_tools} distinct tools. Explore Agent (for parallel research), "
            "Grep (for codebase search), and Edit (for precise changes)."
        )
    if tools.get("Bash", 0) / max(total_uses, 1) > 0.5:
        recs.append(
            "Heavy Bash usage. Use Read instead of cat, Grep instead of grep, "
            "Edit instead of sed — dedicated tools are safer and more reviewable."
        )
    if "Agent" not in tools:
        recs.append(
            "Not using subagents. The Agent tool can parallelise research and complex tasks."
        )
    if edit_count > 0 and read_count < edit_count:
        recs.append(
            "Editing more files than reading. Read files before modifying them — "
            "this helps Claude understand existing code and avoid regressions."
        )
    if session_tools and avg_session_diversity < 2:
        recs.append(
            f"Avg {avg_session_diversity:.1f} tools per session. Effective sessions use "
            "a mix of Read, Edit, Grep, and Bash for a complete research-implement-test workflow."
        )

    return DimensionScore(
        name="Tool Mastery",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"{unique_tools} tools used, top tool is "
            f"{max(tools, key=lambda k: tools[k])} ({top_tool_pct:.0f}%), "
            f"avg {avg_session_diversity:.1f} tools/session."
        ),
        recommendations=recs,
    )


def _score_session_discipline(data: ScoringData) -> DimensionScore:
    """Score session focus — depth, tool workflow, and structure.

    Enhanced with per-session tool diversity as a proxy for structured workflows
    (research -> implement -> test).
    """
    sessions = data.prompts_per_session
    weight = 0.10

    if not sessions:
        return DimensionScore(
            name="Session Discipline",
            score=0,
            weight=weight,
            grade="N/A",
            explanation="No session data.",
            recommendations=[],
        )

    avg_depth = sum(sessions) / len(sessions)
    total_sessions = len(sessions)

    # Too shallow (<3 prompts) = not enough context for Claude to be useful
    shallow = sum(1 for s in sessions if s < 3)
    shallow_pct = shallow / total_sessions * 100

    # Too deep (>60 prompts) = context window bloat, quality degrades
    deep = sum(1 for s in sessions if s > 60)
    deep_pct = deep / total_sessions * 100

    # Ideal range: 5-40 prompts per session
    ideal = sum(1 for s in sessions if 5 <= s <= 40)
    ideal_pct = ideal / total_sessions * 100

    depth_score = _clamp(ideal_pct * 0.6 + (25 - shallow_pct * 0.3) + (10 - deep_pct * 0.5))

    # NEW: Workflow structure — sessions with diverse tools show structured approach
    session_tools = data.unique_tools_per_session
    if session_tools:
        # Sessions using 3+ tools suggest research→implement→test flow
        structured = sum(1 for t in session_tools if t >= 3)
        structured_pct = structured / max(len(session_tools), 1) * 100
        workflow_bonus = min(structured_pct * 0.15, 15)
    else:
        structured_pct = 0
        workflow_bonus = 0

    score = _clamp(depth_score + workflow_bonus)

    recs = []
    if shallow_pct > 30:
        recs.append(
            f"{shallow_pct:.0f}% of sessions have <3 prompts. "
            "Batch related questions into single sessions for better context."
        )
    if deep_pct > 10:
        recs.append(
            f"{deep_pct:.0f}% of sessions exceed 60 prompts. "
            "Start fresh sessions for new tasks — long sessions degrade quality."
        )
    if avg_depth < 5:
        recs.append(
            f"Average session depth is {avg_depth:.1f} prompts. "
            "Claude works best with sustained, multi-turn interactions."
        )
    if session_tools and structured_pct < 30:
        recs.append(
            f"Only {structured_pct:.0f}% of sessions use 3+ tools. "
            "Structured sessions (Read → Edit → Bash for testing) produce better results."
        )

    return DimensionScore(
        name="Session Discipline",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"Avg {avg_depth:.1f} prompts/session, {ideal_pct:.0f}% in ideal range (5-40)"
            + (f", {structured_pct:.0f}% structured." if session_tools else ".")
        ),
        recommendations=recs,
    )


def _score_cost_awareness(data: ScoringData) -> DimensionScore:
    """Score model selection — using the right model for the task.

    Softened single-model penalty: many users are on fixed plans (Max, team)
    where model selection isn't always in their control.
    """
    models = data.model_calls
    weight = 0.10

    if not models:
        return DimensionScore(
            name="Cost Awareness",
            score=50,
            weight=weight,
            grade="C",
            explanation="No model data.",
            recommendations=[],
        )

    total_calls = sum(models.values())

    # Categorise by tier
    opus_pct = sum(v for k, v in models.items() if "opus" in k.lower()) / max(total_calls, 1) * 100
    haiku_pct = (
        sum(v for k, v in models.items() if "haiku" in k.lower()) / max(total_calls, 1) * 100
    )
    sonnet_pct = 100 - opus_pct - haiku_pct

    model_count = len(models)

    if model_count == 1:
        # Softened: single model is common (Max plan, team config). Not terrible.
        score = 60.0
    else:
        score = 65.0
        # Bonus for using multiple models (shows awareness)
        score += min(model_count * 8, 15)
        # Penalty for excessive Opus usage
        if opus_pct > 50:
            score -= (opus_pct - 50) * 0.4
        # Bonus for Haiku usage (cost-conscious for simple tasks)
        score += min(haiku_pct * 0.3, 10)

    score = _clamp(score)

    recs = []
    if model_count == 1:
        model_name = list(models.keys())[0]
        recs.append(
            f"Using only {model_name}. If your plan allows, try Sonnet for routine coding "
            "and Opus for complex architecture — matching model to task saves cost."
        )
    if opus_pct > 60:
        recs.append(
            f"Opus is {opus_pct:.0f}% of calls. Reserve Opus for complex reasoning — "
            "Sonnet handles most coding tasks at 1/5 the cost."
        )
    if haiku_pct == 0 and total_calls > 50 and model_count > 1:
        recs.append(
            "Not using Haiku at all. For quick questions and simple edits, "
            "Haiku is 4x cheaper than Sonnet with comparable results."
        )

    return DimensionScore(
        name="Cost Awareness",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"Model mix: Sonnet {sonnet_pct:.0f}%, Opus {opus_pct:.0f}%, Haiku {haiku_pct:.0f}%."
        ),
        recommendations=recs,
    )


def _score_iteration_efficiency(data: ScoringData) -> DimensionScore:
    """Score iteration efficiency — the north-star metric.

    Measures how effectively the user-AI collaboration converges on results:
    - Correction rate: how often the user has to redirect Claude
    - First-attempt quality: ratio of confirmations to corrections
    - Session workflow: do sessions follow a research→implement→test arc?
    - Prompt-to-turn leverage: Claude doing more per human prompt
    """
    weight = 0.20

    signals = _analyse_prompt_texts(data.prompt_texts)
    total_prompts = len(data.prompt_texts)

    if total_prompts == 0:
        return DimensionScore(
            name="Iteration Efficiency",
            score=0,
            weight=weight,
            grade="N/A",
            explanation="No prompt data.",
            recommendations=["Use Claude Code to generate data for iteration analysis."],
        )

    correction_pct = signals["correction_pct"]
    confirmation_pct = signals["confirmation_pct"]

    # --- Correction rate (lower is better) ---
    # < 5% corrections is excellent, > 20% is poor
    correction_score = _clamp(100 - correction_pct * 4, 0, 35)

    # --- Prompt leverage (Claude actions per human prompt) ---
    total_turns = sum(data.turns_per_session) if data.turns_per_session else 0
    if total_turns > 0 and total_prompts > 0:
        leverage = total_turns / total_prompts  # Higher = Claude doing more per prompt
        leverage_score = _clamp(min(leverage, 5) * 6, 0, 30)
    else:
        leverage = 0
        leverage_score = 15  # Neutral when no data

    # --- Session workflow quality ---
    session_tools = data.unique_tools_per_session
    if session_tools:
        # Sessions with 3+ tools suggest a full workflow (read → edit → test)
        structured = sum(1 for t in session_tools if t >= 3)
        workflow_pct = structured / len(session_tools) * 100
        workflow_score = _clamp(workflow_pct * 0.2, 0, 20)
    else:
        workflow_pct = 0
        workflow_score = 10  # Neutral

    # --- First-attempt quality (low corrections + productive flow) ---
    # Penalise high correction AND high confirmation (both indicate inefficiency)
    noise_pct = correction_pct + confirmation_pct
    focus_score = _clamp(15 - noise_pct * 0.3, 0, 15)

    score = _clamp(correction_score + leverage_score + workflow_score + focus_score)

    recs = []
    if correction_pct > 15:
        recs.append(
            f"{correction_pct:.0f}% of prompts are corrections ('no', 'wrong', 'try again'). "
            "Write clearer initial prompts with specific acceptance criteria to reduce rework."
        )
    if correction_pct > 5 and correction_pct <= 15:
        recs.append(
            f"{correction_pct:.0f}% correction rate. Include expected outcomes in your prompts — "
            "'change X to Y in file Z' is clearer than 'fix this'."
        )
    if leverage < 1.5 and total_turns > 10:
        recs.append(
            f"Claude averages {leverage:.1f} actions per prompt. Give broader task descriptions "
            "so Claude can chain multiple tool calls (read → edit → test) per prompt."
        )
    if session_tools and workflow_pct < 30:
        recs.append(
            f"Only {workflow_pct:.0f}% of sessions follow a full workflow (3+ tools). "
            "Encourage complete cycles: research with Read/Grep, implement with Edit, "
            "verify with Bash."
        )
    if noise_pct > 40:
        recs.append(
            f"{noise_pct:.0f}% of prompts are confirmations or corrections. "
            "Front-load context and be specific — aim for prompts that produce the right "
            "result on the first try."
        )

    return DimensionScore(
        name="Iteration Efficiency",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"{correction_pct:.0f}% corrections, "
            f"{leverage:.1f}x AI leverage, "
            f"{workflow_pct:.0f}% structured sessions."
        ),
        recommendations=recs,
    )


def compute_score(data: ScoringData) -> EfficiencyScore:
    """Compute the composite efficiency score from pre-queried data."""
    dimensions = [
        _score_prompt_quality(data),
        _score_token_efficiency(data),
        _score_cache_utilisation(data),
        _score_tool_mastery(data),
        _score_session_discipline(data),
        _score_cost_awareness(data),
        _score_iteration_efficiency(data),
    ]

    # Weighted composite
    total_weight = sum(d.weight for d in dimensions if d.grade != "N/A")
    if total_weight > 0:
        overall = sum(d.score * d.weight for d in dimensions if d.grade != "N/A") / total_weight
    else:
        overall = 0

    # Collect top recommendations (max 5, ordered by lowest-scoring dimensions)
    sorted_dims = sorted(dimensions, key=lambda d: d.score)
    top_recs = []
    for d in sorted_dims:
        for r in d.recommendations:
            if len(top_recs) < 5:
                top_recs.append(r)

    return EfficiencyScore(
        overall=round(overall, 1),
        grade=_grade(overall),
        dimensions=dimensions,
        top_recommendations=top_recs,
    )


def compute_trend(data: TrendData) -> tuple[str, float]:
    """Determine trend from pre-queried data."""
    if not data.has_data or data.prior_avg_length == 0:
        return "stable", 0.0

    delta = ((data.recent_avg_length - data.prior_avg_length) / data.prior_avg_length) * 100
    if delta > 5:
        return "improving", round(delta, 1)
    if delta < -5:
        return "declining", round(delta, 1)
    return "stable", round(delta, 1)


def compute_project_scores(
    projects: list[str],
    scoring_data: dict[str, ScoringData],
    project_stats: dict[str, tuple[int, int, int]],
) -> list[ProjectScore]:
    """Compute per-project efficiency scores from pre-queried data."""
    results = []
    for project in projects:
        data = scoring_data.get(project, ScoringData())
        score = compute_score(data)

        prompt_count, token_count, session_count = project_stats.get(project, (0, 0, 0))

        results.append(
            ProjectScore(
                project=project,
                score=score,
                prompt_count=prompt_count,
                token_count=token_count,
                session_count=session_count,
            )
        )

    return sorted(results, key=lambda p: p.score.overall, reverse=True)
