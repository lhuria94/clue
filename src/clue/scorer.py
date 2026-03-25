"""AI usage efficiency scoring engine.

Scores across 7 weighted dimensions + 1 informational dimension:
1. Prompt Quality       (20%) — Are prompts specific, structured, and context-rich?
2. Cost Efficiency      (15%) — Actual spend per session, cost distribution consistency
3. Wasted Spend         (10%) — What fraction of cost goes to corrections/rework
4. Tool Mastery         (15%) — Diversity, effectiveness patterns, antipattern detection
5. Session Discipline   (10%) — Focused sessions, tool workflow within sessions
6. Cost Awareness       (10%) — Model selection appropriate to task complexity
7. Iteration Efficiency (20%) — Correction rate, first-attempt success, workflow quality
8. Advanced Usage        (0%) — Agentic maturity, skills, parallel execution (informational)

This module is infrastructure-free: it accepts pre-queried ScoringData/TrendData
and returns pure domain objects. All SQL lives in db.py.
"""

from __future__ import annotations

from .models import DimensionScore, EfficiencyScore, ProjectScore, ScoringData, TrendData
from .patterns import CONFIRMATION_RE, CORRECTION_RE, FILE_REF_RE, SLASH_CMD_RE

# Backward-compatible aliases for consumers that import private names
_SLASH_CMD_RE = SLASH_CMD_RE
_FILE_REF_RE = FILE_REF_RE
_CORRECTION_PATTERNS = CORRECTION_RE
_CONFIRMATION_RE = CONFIRMATION_RE


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
            "file_ref_correction_rate": 0, "non_file_ref_correction_rate": 0,
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

    # Compute correction rate after file-ref vs non-file-ref prompts
    # A correction is when the NEXT prompt is a correction pattern
    file_ref_followed_by_correction = 0
    non_file_ref_followed_by_correction = 0
    file_ref_count_for_rate = 0
    non_file_ref_count_for_rate = 0
    for i in range(len(texts) - 1):
        is_file_ref = bool(_FILE_REF_RE.search(texts[i]))
        next_is_correction = bool(_CORRECTION_PATTERNS.match(texts[i + 1].strip()))
        if is_file_ref:
            file_ref_count_for_rate += 1
            if next_is_correction:
                file_ref_followed_by_correction += 1
        else:
            non_file_ref_count_for_rate += 1
            if next_is_correction:
                non_file_ref_followed_by_correction += 1

    file_ref_cr = (
        file_ref_followed_by_correction / file_ref_count_for_rate * 100
        if file_ref_count_for_rate > 0 else 0
    )
    non_file_ref_cr = (
        non_file_ref_followed_by_correction / non_file_ref_count_for_rate * 100
        if non_file_ref_count_for_rate > 0 else 0
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
        "file_ref_correction_rate": file_ref_cr,
        "non_file_ref_correction_rate": non_file_ref_cr,
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
    # Only recommend file refs if user's own data doesn't contradict it
    # (prompt_learning in export.py may show file-ref prompts have *higher* correction rates)
    if signals["file_ref_pct"] < 15 and total > 20:
        # Check if file-ref prompts actually have lower correction rate
        file_ref_correction = signals.get("file_ref_correction_rate", 0)
        non_file_ref_correction = signals.get("non_file_ref_correction_rate", 0)
        if file_ref_correction <= non_file_ref_correction or file_ref_correction == 0:
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


def _score_cost_efficiency(data: ScoringData) -> DimensionScore:
    """Score cost efficiency — actual spend per session.

    Uses real cost data from SessionMetrics. A session is a unit of work
    (one task, one bug, one feature). Cost-per-session is the actionable metric.
    """
    metrics = data.session_metrics
    weight = 0.15

    costed = [m for m in metrics if m.cost > 0]
    if not costed:
        return DimensionScore(
            name="Cost Efficiency",
            score=50,
            weight=weight,
            grade="C",
            explanation="Not enough session data to assess cost efficiency.",
            recommendations=[],
        )

    total_cost = sum(m.cost for m in costed)
    avg_cps = total_cost / len(costed)
    session_costs = sorted(m.cost for m in costed)

    # Median cost-per-session as baseline
    median_cps = session_costs[len(session_costs) // 2]

    # Score based on cost distribution — compare your sessions to each other
    # Use the ratio of median to p90 as a spread indicator
    p10 = session_costs[max(len(session_costs) // 10, 0)]
    p90 = session_costs[min(len(session_costs) * 9 // 10, len(session_costs) - 1)]

    # Tight distribution (p90/median < 3x) = consistent = good
    spread = p90 / max(median_cps, 0.01)
    if spread < 2:
        base = 85  # Very consistent spend
    elif spread < 4:
        base = 70
    elif spread < 8:
        base = 55
    else:
        base = 35  # Huge variance — some sessions wildly more expensive

    # Bonus: what fraction of total cost is in the top 10% of sessions?
    top10_cost = sum(session_costs[-(max(len(session_costs) // 10, 1)):])
    top10_pct = top10_cost / max(total_cost, 0.01) * 100
    # If top 10% consumes <30% of budget, that's healthy
    concentration_bonus = _clamp(15 - (top10_pct - 30) * 0.5, 0, 15)

    score = _clamp(base + concentration_bonus)

    recs = []
    # Find expensive outlier sessions
    if len(costed) >= 5:
        expensive = sorted(costed, key=lambda m: m.cost, reverse=True)[:3]
        top_cost = expensive[0].cost
        if top_cost > total_cost * 0.2:
            recs.append(
                f"Your most expensive session cost ${top_cost:.2f} "
                f"({top_cost / total_cost * 100:.0f}% of total spend). "
                "Long sessions with many back-and-forths drive up cost — "
                "start fresh for new tasks."
            )
    if spread >= 4:
        recs.append(
            f"Session costs range from ${p10:.2f} to ${p90:.2f} "
            f"(typical ${median_cps:.2f}). "
            "Expensive sessions often mean long conversations — "
            "start fresh for new tasks instead of continuing."
        )

    return DimensionScore(
        name="Cost Efficiency",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"${avg_cps:.2f}/session average, "
            f"${median_cps:.2f} typical, "
            f"${total_cost:.2f} total across {len(costed)} sessions."
        ),
        recommendations=recs,
    )


def _score_wasted_spend(data: ScoringData) -> DimensionScore:
    """Score wasted spend — what fraction of cost goes to corrections/rework.

    Uses actual session data: correction prompts × session cost fraction.
    Lower waste = higher score.
    """
    metrics = data.session_metrics
    weight = 0.10

    if not metrics:
        return DimensionScore(
            name="Wasted Spend",
            score=50,
            weight=weight,
            grade="C",
            explanation="Not enough data to assess wasted spend.",
            recommendations=[],
        )

    total_cost = sum(m.cost for m in metrics)
    total_prompts = sum(m.prompt_count for m in metrics)
    total_corrections = sum(m.correction_count for m in metrics)

    if total_cost == 0 or total_prompts == 0:
        return DimensionScore(
            name="Wasted Spend",
            score=75,
            weight=weight,
            grade="B",
            explanation="No cost data — unable to estimate waste.",
            recommendations=[],
        )

    correction_pct = total_corrections / total_prompts * 100

    # Estimate wasted cost: for sessions with corrections,
    # waste ≈ correction_fraction × session_cost
    wasted = 0.0
    for m in metrics:
        if m.correction_count > 0 and m.prompt_count > 0:
            wasted += m.cost * (m.correction_count / m.prompt_count)
    waste_pct = wasted / total_cost * 100 if total_cost > 0 else 0

    # Score: 0% waste = 100, 5% = ~80, 15% = ~50, 30%+ = ~20
    score = _clamp(100 - waste_pct * 3)

    recs = []
    if waste_pct > 5:
        recs.append(
            f"~${wasted:.2f} ({waste_pct:.1f}% of spend) goes to "
            f"correction-heavy sessions. "
            f"{total_corrections} correction prompts across "
            f"{sum(1 for m in metrics if m.correction_count > 0)} sessions."
        )
    if waste_pct > 15:
        recs.append(
            "High rework cost. Write prompts with specific file paths and "
            "expected outcomes to reduce 'no, not that' corrections."
        )

    return DimensionScore(
        name="Wasted Spend",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"~${wasted:.2f} wasted ({waste_pct:.1f}% of ${total_cost:.2f} total), "
            f"{correction_pct:.1f}% correction rate."
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
            f"Only using {unique_tools} distinct tools. Try Agent for parallel research, "
            "Grep for searching code, and Edit for precise file changes."
        )
    if tools.get("Bash", 0) / max(total_uses, 1) > 0.5:
        recs.append(
            "Heavy terminal usage. Prefer Read over cat, Grep over grep, "
            "Edit over sed — dedicated tools are safer and easier to review."
        )
    if "Agent" not in tools:
        recs.append(
            "Not using parallel agents. The Agent tool can run multiple "
            "research tasks at the same time."
        )
    if edit_count > 0 and read_count < edit_count:
        recs.append(
            "Editing more files than reading. Read files before modifying them — "
            "this helps Claude understand existing code and avoid regressions."
        )
    if session_tools and avg_session_diversity < 2:
        recs.append(
            f"Average {avg_session_diversity:.1f} tools per session. Effective sessions use "
            "a mix of Read, Edit, Grep, and Bash for a complete research-implement-test workflow."
        )

    return DimensionScore(
        name="Tool Mastery",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=(
            f"{unique_tools} tools used, most used is "
            f"{max(tools, key=lambda k: tools[k])} ({top_tool_pct:.0f}%), "
            f"average {avg_session_diversity:.1f} per session."
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
            "Group related questions into one session so Claude has full context."
        )
    if deep_pct > 10:
        recs.append(
            f"{deep_pct:.0f}% of sessions exceed 60 prompts. "
            "Start fresh sessions for new tasks — long sessions degrade quality."
        )
    if avg_depth < 5:
        recs.append(
            f"Average session depth is {avg_depth:.1f} prompts. "
            "Claude works best with sustained, multi-step interactions."
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
            f"Average {avg_depth:.1f} prompts/session, {ideal_pct:.0f}% in ideal range (5-40)"
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
            f"Opus is {opus_pct:.0f}% of usage. Reserve Opus for complex reasoning — "
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
            "so Claude can chain multiple steps (read → edit → test) per prompt."
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
            f"{leverage:.1f} actions per prompt, "
            f"{workflow_pct:.0f}% multi-step sessions."
        ),
        recommendations=recs,
    )


def _score_advanced_usage(data: ScoringData) -> DimensionScore:
    """Score advanced usage maturity — agentic patterns, skills, task discipline.

    Informational dimension (weight=0) — does not affect composite score.
    Measures how effectively the user leverages advanced Claude Code features:
    - Agentic maturity: % of sessions using the Agent tool
    - Parallel execution: % of Agent calls with run_in_background
    - Skill adoption: distinct skills used
    - Task discipline: TaskCreate/TaskUpdate usage patterns
    """
    weight = 0.0  # Informational only

    agent_types = data.agent_type_counts
    parallel = data.parallel_invocations
    skills = data.skills_used
    task_tools = data.task_tool_counts
    tools = data.tool_counts

    total_agent_calls = sum(agent_types.values()) if agent_types else 0
    total_tool_calls = sum(tools.values()) if tools else 0
    total_skill_calls = sum(skills.values()) if skills else 0
    total_task_calls = sum(task_tools.values()) if task_tools else 0

    if total_tool_calls == 0:
        return DimensionScore(
            name="Advanced Usage",
            score=0,
            weight=weight,
            grade="N/A",
            explanation="No tool usage data.",
            recommendations=["Use Claude Code to generate advanced usage data."],
        )

    # --- Agentic maturity (0-30) ---
    agent_pct = total_agent_calls / total_tool_calls * 100 if total_tool_calls else 0
    # Using agents at all is good; 5-20% of calls being Agent is ideal
    if agent_pct == 0:
        agentic_score = 0.0
    elif agent_pct < 5:
        agentic_score = 15.0
    elif agent_pct <= 20:
        agentic_score = 30.0
    else:
        agentic_score = 25.0  # Over-reliance on agents

    # Bonus for using typed subagents (not just generic)
    typed_agents = sum(v for k, v in agent_types.items() if k is not None)
    if total_agent_calls > 0 and typed_agents / total_agent_calls > 0.5:
        agentic_score = min(agentic_score + 5, 30)

    # --- Parallel execution (0-25) ---
    if total_agent_calls == 0:
        parallel_score = 0.0
    else:
        parallel_pct = parallel / total_agent_calls * 100
        if parallel_pct == 0:
            parallel_score = 5.0  # Using agents but not parallelising
        elif parallel_pct < 20:
            parallel_score = 15.0
        else:
            parallel_score = 25.0

    # --- Skill adoption (0-25) ---
    unique_skills = len(skills)
    if unique_skills == 0:
        skill_score = 0.0
    elif unique_skills <= 2:
        skill_score = 10.0
    elif unique_skills <= 5:
        skill_score = 20.0
    else:
        skill_score = 25.0

    # --- Task discipline (0-20) ---
    creates = task_tools.get("TaskCreate", 0)
    updates = task_tools.get("TaskUpdate", 0)
    if creates == 0 and updates == 0:
        task_score = 0.0
    elif creates > 0 and updates > 0:
        # Using both create and update shows discipline
        task_score = 20.0
    elif creates > 0:
        task_score = 10.0  # Creating but not tracking
    else:
        task_score = 5.0

    score = _clamp(agentic_score + parallel_score + skill_score + task_score)

    # Build explanation
    parts = []
    if total_agent_calls > 0:
        parts.append(f"{total_agent_calls} agent calls ({agent_pct:.0f}% of tools)")
    if parallel > 0:
        parts.append(f"{parallel} parallel")
    if total_skill_calls > 0:
        parts.append(f"{unique_skills} skills ({total_skill_calls} uses)")
    if total_task_calls > 0:
        parts.append(f"{total_task_calls} task ops")
    explanation = ", ".join(parts) if parts else "No advanced feature usage detected."

    recs = []
    if total_agent_calls == 0:
        recs.append(
            "Not using Agent tool. Spawn subagents for parallel research, "
            "code review, and independent explorations."
        )
    elif parallel == 0:
        recs.append(
            "No background agents. Use run_in_background=true for independent "
            "research tasks to parallelise your workflow."
        )
    if unique_skills == 0:
        recs.append(
            "No skills used. Skills like /commit, /review, /test automate "
            "common workflows with best-practice patterns."
        )
    if creates == 0 and updates == 0:
        recs.append(
            "Not using task tools. TaskCreate/TaskUpdate help track multi-step "
            "work and maintain progress across long sessions."
        )

    return DimensionScore(
        name="Advanced Usage",
        score=round(score, 1),
        weight=weight,
        grade=_grade(score),
        explanation=explanation,
        recommendations=recs,
    )


def _data_driven_recommendations(data: ScoringData) -> list[str]:
    """Generate recommendations by comparing YOUR sessions against each other.

    Every recommendation is backed by actual per-session data — no generic
    thresholds, no imagined metrics.  Each compares two groups of your own
    sessions and cites the measured difference.
    """
    metrics = data.session_metrics
    if len(metrics) < 5:
        return []

    recs: list[str] = []

    # --- 1. Read-before-Edit vs not: correction rate comparison ---
    rbe_sessions = [m for m in metrics if m.has_read_before_edit and m.edit_count > 0]
    no_rbe = [m for m in metrics if not m.has_read_before_edit and m.edit_count > 0]
    if len(rbe_sessions) >= 3 and len(no_rbe) >= 3:
        rbe_corr = sum(m.correction_count for m in rbe_sessions) / max(
            sum(m.prompt_count for m in rbe_sessions), 1
        )
        no_rbe_corr = sum(m.correction_count for m in no_rbe) / max(
            sum(m.prompt_count for m in no_rbe), 1
        )
        if no_rbe_corr > rbe_corr and no_rbe_corr > 0.02:
            rbe_pct = rbe_corr * 100
            no_rbe_pct = no_rbe_corr * 100
            recs.append(
                f"Sessions where you Read before Edit have a {rbe_pct:.0f}% correction rate "
                f"vs {no_rbe_pct:.0f}% without. Reading first across {len(rbe_sessions)} sessions "
                f"saved rework."
            )

    # --- 2. File-ref prompts vs no file-ref: correction rate ---
    with_refs = [m for m in metrics if m.file_ref_count > 0 and m.prompt_count > 0]
    no_refs = [m for m in metrics if m.file_ref_count == 0 and m.prompt_count > 0]
    if len(with_refs) >= 3 and len(no_refs) >= 3:
        ref_corr = sum(m.correction_count for m in with_refs) / max(
            sum(m.prompt_count for m in with_refs), 1
        )
        no_ref_corr = sum(m.correction_count for m in no_refs) / max(
            sum(m.prompt_count for m in no_refs), 1
        )
        if no_ref_corr > ref_corr and no_ref_corr > 0.02:
            recs.append(
                f"Prompts with file references have a {ref_corr * 100:.0f}% correction rate. "
                f"Without file refs: {no_ref_corr * 100:.0f}%. "
                f"Naming the file upfront reduces back-and-forth."
            )

    # --- 3. Top 10% vs bottom 10% sessions by cost ---
    costed = [m for m in metrics if m.cost > 0]
    if len(costed) >= 10:
        by_cost = sorted(costed, key=lambda m: m.cost)
        n10 = max(len(by_cost) // 10, 1)
        top10 = by_cost[:n10]       # cheapest sessions
        bottom10 = by_cost[-n10:]   # most expensive sessions

        top_avg_len = sum(m.avg_prompt_length for m in top10) / len(top10)
        bot_avg_len = sum(m.avg_prompt_length for m in bottom10) / len(bottom10)
        top_avg_turns = sum(m.turn_count for m in top10) / len(top10)
        bot_avg_turns = sum(m.turn_count for m in bottom10) / len(bottom10)
        top_avg_div = sum(m.tool_diversity for m in top10) / len(top10)
        bot_avg_div = sum(m.tool_diversity for m in bottom10) / len(bottom10)

        parts = []
        actions = []
        if top_avg_len > bot_avg_len * 1.3:
            parts.append(f"prompts avg {top_avg_len:.0f} chars (vs {bot_avg_len:.0f})")
            actions.append("write longer, more specific prompts with context")
        if bot_avg_turns > top_avg_turns * 1.5:
            parts.append(f"stay under {top_avg_turns:.0f} back-and-forths (vs {bot_avg_turns:.0f})")
            actions.append("break large tasks into separate sessions")
        if top_avg_div > bot_avg_div * 1.2:
            parts.append(f"use {top_avg_div:.0f} tools (vs {bot_avg_div:.0f})")

        if parts:
            msg = f"Your most efficient sessions {', '.join(parts)}."
            if actions:
                msg += f" Try: {actions[0]}."
            recs.append(msg)

    # --- 4. Per-project comparison (cost per session) ---
    projects: dict[str, list] = {}
    for m in metrics:
        if m.cost > 0:
            projects.setdefault(m.project, []).append(m)

    if len(projects) >= 2:
        proj_efficiency = {}
        for proj, sessions in projects.items():
            if len(sessions) >= 3:
                total_cost = sum(m.cost for m in sessions)
                proj_efficiency[proj] = total_cost / len(sessions)
        if len(proj_efficiency) >= 2:
            ranked = sorted(proj_efficiency.items(), key=lambda x: x[1])
            best_proj, best_cps = ranked[0]
            worst_proj, worst_cps = ranked[-1]
            if worst_cps > best_cps * 1.5:
                ratio = worst_cps / best_cps if best_cps > 0 else 0
                recs.append(
                    f"In {best_proj} you spend ${best_cps:.2f}/session. "
                    f"In {worst_proj} it's ${worst_cps:.2f}/session "
                    f"({ratio:.1f}x more). "
                    f"Compare prompt style and session length between the two."
                )

    # --- 5. max_tokens hits correlate with session cost ---
    max_tok_sessions = [m for m in metrics if m.max_tokens_hits > 0]
    no_max_tok = [m for m in metrics if m.max_tokens_hits == 0 and m.cost > 0]
    if len(max_tok_sessions) >= 2 and len(no_max_tok) >= 3:
        avg_cost_max = sum(m.cost for m in max_tok_sessions) / len(max_tok_sessions)
        avg_cost_no = sum(m.cost for m in no_max_tok) / len(no_max_tok)
        if avg_cost_max > avg_cost_no * 1.5:
            recs.append(
                f"Sessions hitting context limits cost ${avg_cost_max:.2f} average "
                f"vs ${avg_cost_no:.2f} for others. "
                f"{len(max_tok_sessions)} sessions ran out of context — "
                f"start fresh sessions for new tasks to keep costs down."
            )

    return recs


def compute_score(data: ScoringData) -> EfficiencyScore:
    """Compute the composite efficiency score from pre-queried data."""
    dimensions = [
        _score_prompt_quality(data),
        _score_cost_efficiency(data),
        _score_wasted_spend(data),
        _score_tool_mastery(data),
        _score_session_discipline(data),
        _score_cost_awareness(data),
        _score_iteration_efficiency(data),
        _score_advanced_usage(data),
    ]

    # Weighted composite
    total_weight = sum(d.weight for d in dimensions if d.grade != "N/A")
    if total_weight > 0:
        overall = sum(d.score * d.weight for d in dimensions if d.grade != "N/A") / total_weight
    else:
        overall = 0

    # Data-driven comparative recommendations first (most valuable)
    data_recs = _data_driven_recommendations(data)

    # Then threshold-based recommendations from lowest-scoring dimensions
    sorted_dims = sorted(dimensions, key=lambda d: d.score)
    dim_recs = []
    for d in sorted_dims:
        for r in d.recommendations:
            if len(dim_recs) < 3:
                dim_recs.append(r)

    # Combine: data-driven first, then threshold-based, max 5 total
    top_recs = data_recs[:3] + dim_recs[:2]
    top_recs = top_recs[:5]

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
