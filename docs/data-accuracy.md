# Data Accuracy

How Clue counts tokens, estimates cost, and derives metrics — and the known limitations.

## Token Counting

### Streaming Chunk Deduplication

Claude Code logs each content block (thinking, text, tool_use) from an API response as a separate JSONL entry. All entries from the same API call share `message.id` and `requestId`. Token usage is **cumulative** — the last entry contains the complete totals for that API call.

Clue groups entries by `message.id:requestId` and takes the **last** entry's usage (correct cumulative totals). This avoids double-counting streaming chunks.

Entries missing both `message.id` and `requestId` (e.g. very old JSONL files) cannot be deduplicated and are counted individually.

### Multi-Tool Token Attribution

When a single API response contains multiple tool_use blocks (e.g. Read + Edit + Bash in one response), Clue emits one turn per tool but attributes the full token usage only to the **first** tool turn. Remaining tool turns receive zero usage. This prevents multiplying the token count by the number of tools.

### User Turns

User turns (`role: "user"`) have no model and zero token usage. They are stored for prompt counting and correction detection but do not contribute to token or cost totals.

## Cost Estimation

### Per-Model Pricing

Every cost calculation groups by model and applies the model-specific rate. No path uses a hardcoded default model. The `COALESCE(model, '_default')` pattern routes NULL-model turns to Sonnet pricing (the most common model).

Pricing table (`src/clue/models.py`):

| Model | Input/M | Output/M | Cache Write/M | Cache Read/M |
|---|---|---|---|---|
| `claude-opus-4-6` | $5.00 | $25.00 | $6.25 | $0.50 |
| `claude-sonnet-4-6` | $3.00 | $15.00 | $3.75 | $0.30 |
| `claude-haiku-4-5-20251001` | $1.00 | $5.00 | $1.25 | $0.10 |
| `_default` | $3.00 | $15.00 | $3.75 | $0.30 |

### Cost Consistency

Three independent paths produce the same total:

1. `total_estimated_cost` — `SUM` by model across all turns
2. `sum(daily_cost)` — `SUM` by (date, model), then summed across days
3. `sum(project_cost_efficiency)` — `SUM` by (date, project, model), then summed

All three must match. If they diverge, there is a bug in a GROUP BY or WHERE clause.

## Session Counting

### Source: `sessions` Table

Session counts come from the `sessions` table (built from both prompt history and conversation JSONL files), not from `COUNT(DISTINCT session_id)` on the `prompts` table.

**Why this matters**: `history.jsonl` only captures a subset of sessions. In practice, the prompts table may have ~12% of the sessions that the turns/sessions tables have. Using the prompts table for session counts would severely undercount.

### Daily Session Counts

Daily session counts in `daily_usage` come from the `turns` table (`COUNT(DISTINCT session_id)` grouped by date). A session active across multiple days is counted in each day. This means `sum(daily_usage.sessions)` > `total_sessions`. This is expected and correct for daily granularity — it answers "how many sessions were active on this day" not "how many unique sessions exist".

The hero cost/session uses `overview.total_sessions` (unique count from sessions table) to avoid this inflation.

### Per-Project Sessions

`project_cost_efficiency` and `branch_coaching` use separate session count queries (ungrouped by model) to avoid undercounting when sessions use multiple models. The cost queries group by model for accurate pricing, but session counting is independent.

## Scoring Engine

### Dimensions and Weights

| Dimension | Weight | Source |
|---|---|---|
| Prompt Quality | 20% | `prompts` table: lengths, file refs, corrections |
| Cost Efficiency | 15% | `session_metrics`: per-session cost distribution |
| Wasted Spend | 10% | Correction rate x follow-up turn cost |
| Tool Mastery | 15% | `turns` table: tool diversity, Read→Edit flow |
| Session Discipline | 10% | `session_metrics`: prompts per session distribution |
| Cost Awareness | 10% | `turns` table: model mix |
| Iteration Efficiency | 20% | `session_metrics`: correction rate, AI leverage |

Weights sum to exactly 1.0. All dimension scores are clamped to [0, 100]. When a dimension returns N/A, the remaining dimensions are re-normalised.

### Cost Efficiency Filtering

The "across N sessions" count in Cost Efficiency excludes zero-cost sessions (`cost == 0`), since they would skew the distribution. This is why the count may be lower than `total_sessions`.

## Usage Streak

Counts consecutive calendar days of activity ending at the most recent active day. The streak is only reported if the last active day is today or yesterday — otherwise it's 0 (the streak has broken).

## Merge Command

When merging multiple user exports:

- **Counts** (prompts, sessions, tokens, turns) are summed
- **Rates** (`avg_prompt_length_chars`, `cache_hit_rate_pct`) are recalculated from raw data, not summed
- `cache_hit_rate_pct` is recomputed from `daily_tokens` entries (`cr` and `cw` fields)
- `avg_prompt_length_chars` is recomputed from `prompt_lengths` entries

## Known Limitations

### Prompt Coverage

`history.jsonl` does not capture all user prompts. Many sessions have turns (from conversation JSONL files) but no corresponding prompt text. The Activity tab's daily prompt count reflects only what `history.jsonl` contains. This is a data source limitation, not a calculation error.

### Multi-Day Session Inflation

A session active across 3 calendar days appears 3 times in daily-granularity data. When the dashboard sums daily session counts for a filtered period (7/30/90 days), the total is inflated. The all-time hero and overview use the sessions table (unique count) and are not affected.

### `<synthetic>` Model

Claude Code occasionally logs turns with model `<synthetic>`. These have 0 tokens and $0 cost. They receive `_default` pricing but produce no cost impact.
