# Clue Team — How It Works

End-to-end flow from developer setup to leadership dashboard.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Developer CLI** | Python 3.10+ (existing Clue) | Already works. Zero new dependencies. Runs everywhere |
| **Provider extractors** | Python, one module per provider | Shares models/patterns with CLI. Easy to add new providers |
| **Local storage** | SQLite (existing) | Developer's personal dashboard. Never leaves their machine |
| **Push transport** | HTTPS POST with API key header | Simple, stateless, works through corporate proxies |
| **Team API** | FastAPI (Python) | Same language as CLI — shared scorer/models. Async, fast, OpenAPI docs for free |
| **Team database** | PostgreSQL 16 | The only state. Handles concurrent writes from 500 developers without breaking a sweat |
| **Team dashboard** | Streamlit initially → Next.js SPA later | Streamlit gets us to market fast. SPA when we need embedding, SSO, and polish |
| **Auth** | API keys (push), OAuth2/SSO (dashboard) | API keys are zero-friction for developers. SSO is table stakes for enterprise dashboard access |
| **Hosting** | Docker Compose (self-hosted) or Cloud Run (managed) | Self-hosted for enterprises who won't let data leave. Managed for everyone else |
| **Migrations** | Alembic (Postgres schema versioning) | Industry standard for Python + Postgres. Follows the pattern Clue already uses for SQLite migrations |

---

## The Data Accuracy Foundation

Everything depends on this. If the numbers are wrong, nothing else matters.

### How tokens are counted (proven, working today)

```
Claude Code writes JSONL → multiple entries per API call
                           same message.id + requestId
                           token usage is CUMULATIVE across entries

Entry 1: {id: "msg_1", requestId: "req_1", usage: {input: 500, output: 8}}     ← partial
Entry 2: {id: "msg_1", requestId: "req_1", usage: {input: 500, output: 8}}     ← still streaming
Entry 3: {id: "msg_1", requestId: "req_1", usage: {input: 500, output: 257}}   ← final total
```

**Clue groups by `message.id:requestId` and takes the LAST entry's usage.** This captures the complete token count. (ccusage takes the first entry — undercounts output tokens by ~64%.)

This dedup logic lives in `extractor.py` and runs on the developer's machine. The server never sees raw JSONL — it receives already-deduplicated, scored, scrubbed metrics.

### How cost is calculated

```
For each turn:
  1. Read model from the turn (e.g., "claude-sonnet-4-6")
  2. Look up per-model rates: input, output, cache_write, cache_read
  3. cost = (input_tokens × input_rate) + (output_tokens × output_rate)
         + (cache_creation_tokens × cache_write_rate)
         + (cache_read_tokens × cache_read_rate)
  4. Sum across all turns in a session → session cost
  5. Sum across all sessions in a day → daily cost
```

No averaging, no defaults, no rounding until display. Every token is attributed to its actual model.

### How scoring works

The scorer takes raw metrics and produces a 0-100 score across 7 dimensions. Each dimension has a clear rubric:

```
Input:  prompt_count, prompt_lengths, correction_count, tool_usage,
        model_mix, session_depths, cache_hit_rate, cost_per_session

Output: overall_score (0-100), grade (A-F), trend (% change),
        7 dimension scores, 3-5 actionable recommendations
```

The scorer is stateless — give it numbers, get back a score. It doesn't know which provider generated the data, which project it's from, or who the developer is. This is what makes it portable across providers.

---

## Flow 1: Developer Onboarding

### Step 1 — Install Clue locally (2 minutes)

```bash
git clone https://github.com/lhuria94/cluei.git && cd clue && ./setup.sh
```

Setup does:
1. Creates Python venv, installs Clue
2. Runs `clue extract` — parses all historical `~/.claude/` data into local SQLite
3. Installs PostStop hook — after every Claude Code session, `clue extract --incremental` runs automatically
4. Prints the developer's AI efficiency score with recommendations
5. Runs `clue doctor` to validate everything works

**At this point the developer has a fully working personal dashboard.** No server needed. No account needed. They can stop here if they want.

### Step 2 — Connect to team (1 minute)

The team admin gives the developer an API key and endpoint URL. The developer runs:

```bash
clue config --team-endpoint https://clue.yourcompany.com --api-key clue_sk_...
```

This writes to `~/.claude/clue-team.json`:
```json
{
  "endpoint": "https://clue.yourcompany.com",
  "api_key": "clue_sk_...",
  "auto_push": true,
  "scrub": true
}
```

### Step 3 — First push

```bash
clue push
```

This does:
1. `clue export --scrub` — generates scrubbed metrics JSON from local SQLite
2. Attaches the developer's API key as auth header
3. POSTs to `POST /v1/push`
4. Server validates API key → resolves to user_id → inserts into `daily_metrics`

From now on, after every Claude Code session:
```
Claude Code stops
  → PostStop hook fires
  → clue extract --incremental (updates local SQLite)
  → clue push (sends scrubbed metrics to team server)
```

The developer never thinks about it again.

### What the push payload looks like

```json
{
  "version": "1.0",
  "provider": "claude-code",
  "generated_at": "2026-03-24T10:00:00Z",
  "date_range": {
    "from": "2026-03-24",
    "to": "2026-03-24"
  },
  "daily_metrics": [
    {
      "date": "2026-03-24",
      "project_hint": "github.com/org/web-app",
      "provider": "claude-code",
      "prompts": 47,
      "sessions": 8,
      "tokens": {
        "input": 125000,
        "output": 89000,
        "cache_write": 45000,
        "cache_read": 320000
      },
      "cost_usd": 4.82,
      "model_mix": {
        "claude-sonnet-4-6": 0.85,
        "claude-opus-4-6": 0.10,
        "claude-haiku-4-5": 0.05
      },
      "tool_counts": {
        "Read": 34, "Edit": 21, "Bash": 15,
        "Grep": 8, "Glob": 5, "Write": 3
      },
      "correction_rate": 0.06,
      "cache_hit_rate": 0.62,
      "avg_prompt_chars": 145,
      "stop_reasons": {
        "tool_use": 42, "end_turn": 18, "stop_sequence": 2
      },
      "session_depths": [5, 12, 3, 28, 7, 15, 2, 9],
      "hourly_distribution": {"9": 5, "10": 12, "11": 8, "14": 10, "15": 7, "16": 5},
      "scores": {
        "overall": 74,
        "dimensions": {
          "prompt_quality": 62,
          "cost_efficiency": 81,
          "wasted_spend": 78,
          "tool_mastery": 85,
          "session_discipline": 58,
          "cost_awareness": 79,
          "iteration_efficiency": 70
        }
      }
    }
  ]
}
```

**What's NOT in this payload:**
- No prompt text
- No conversation content
- No file paths
- No absolute project paths (only `project_hint` derived from git remote, configurable)
- No code, no diffs, no branch names

**What IS in this payload — and why each field matters:**

| Field | Why the team needs it |
|---|---|
| `prompts`, `sessions` | Volume: is the developer using AI regularly? |
| `tokens.*` | Cost attribution: how much is this project costing in AI? |
| `cost_usd` | Direct cost metric. Pre-calculated on device so server doesn't need pricing tables |
| `model_mix` | Cost awareness: are they using Opus when Sonnet would suffice? |
| `tool_counts` | Tool mastery: Read→Edit workflow indicates structured development |
| `correction_rate` | Prompt quality signal: high correction = vague prompts |
| `cache_hit_rate` | Efficiency: reusing context vs rebuilding it every turn |
| `avg_prompt_chars` | Prompt quality: too short = vague, too long = unfocused |
| `stop_reasons` | Session pattern: mostly tool_use = agentic, mostly end_turn = conversational |
| `session_depths` | Session discipline: [3, 2, 1, 45] suggests one runaway session |
| `hourly_distribution` | Work pattern: when does the developer use AI? (no surveillance — just aggregated counts) |
| `scores` | The headline number: 0-100 efficiency with dimension breakdown |

---

## Flow 2: Project Setup and Separation

### How projects are identified

The developer's machine knows which project they're working on from two sources:
1. **`~/.claude/` directory structure** — Claude Code stores conversations under project-specific paths
2. **Git remote URL** — the repo they're working in (e.g., `github.com/org/web-app`)

When `clue push` runs, the `project_hint` field is derived from the git remote URL of the working directory. This is the **only project identifier** that leaves the developer's machine.

### How the server maps projects

The team admin creates projects in the admin panel:

```
Project: "Web App Redesign"
  Git remotes: github.com/org/web-app, github.com/org/web-app-v2
  Client: Acme Corp
  Status: Active
  Members: auto-detect from push data
```

When a push arrives with `project_hint: "github.com/org/web-app"`, the server:
1. Looks up the project by matching git remote
2. If no match → creates an "unassigned" entry for admin to map later
3. Associates the daily_metrics row with `(user_id, project_id, date, provider)`

### Project separation in the database

```sql
-- The atomic grain: one row per developer × project × day × provider
-- A developer working on 3 projects today produces 3 rows

daily_metrics:
  user_id=7, project_id=1, date=2026-03-24, provider=claude-code, cost=2.10, score=74
  user_id=7, project_id=3, date=2026-03-24, provider=claude-code, cost=1.50, score=68
  user_id=7, project_id=5, date=2026-03-24, provider=cursor,      cost=0.80, score=71
```

This means:
- **Project view**: `WHERE project_id = 1` → all developers, all days, all providers for that project
- **Developer view**: `WHERE user_id = 7` → all projects, all days, all providers for that person
- **Cell view**: `WHERE user_id = 7 AND project_id = 1` → one developer on one project over time
- **Org view**: no filters → everything, rolled up by week/month

### How Clue knows which project a session belongs to

On the developer's machine, `extractor.py` already parses project from two places:

1. **`history.jsonl`** — each prompt has a `project` field containing the working directory path
2. **Conversation files** — stored under `~/.claude/projects/<encoded-project-path>/`

The extractor maps these to the project. When `export --scrub` runs:
- The filesystem path `/Users/dev/work/acme/web-app` becomes the git remote `github.com/org/web-app`
- If no git remote, it becomes a hash (never the raw path)

**The server never sees filesystem paths. Only git remote URLs (or hashes).**

### Multi-project sessions

Sometimes a developer's Claude Code session touches multiple projects (e.g., working on a monorepo with multiple services). Clue handles this:

- Each prompt is tagged with its `cwd` (working directory) at the time it was sent
- If `cwd` changes mid-session, prompts are attributed to the correct project
- Token cost is split proportionally across projects based on prompt count per project within the session

---

## Flow 3: What the Team Dashboard Shows

### Project Lead View

The project lead for "Web App Redesign" opens the dashboard and sees:

**Project Health Card:**
```
Web App Redesign — Score: 72/100 B  ↑ +4 from last month
  Active developers: 6
  This month: $342 AI cost, 1,247 prompts, 89 sessions
  Correction rate: 8% (org avg: 11%)
```

**Developer Breakdown (anonymised by default, names opt-in):**
```
                Score   Trend   Cost    Sessions   Correction Rate
Developer A      85      ↑+3    $45      18         4%
Developer B      78      ↑+1    $62      22         6%
Developer C      71      →      $38      12         8%
Developer D      65      ↓-5    $52      15         14%    ← needs coaching
Developer E      61      ↑+8    $78      14         12%    ← improving fast
Developer F      58      →      $67      8          18%    ← needs coaching
```

**Coaching Recommendations:**
- "2 developers have correction rates above 15% — suggest prompt engineering practice"
- "Developer D's score dropped 5 points — their session depth increased from avg 12 to avg 28. They may be staying in sessions too long instead of starting fresh"
- "Project's cache hit rate is 45%, below org average of 62% — developers may not be providing enough context upfront"

**Project Cost Trend:** Line chart showing weekly AI cost with developer breakdown.

**Tool Usage:** "This project uses Read 40%, Edit 25%, Bash 20% — healthy Read→Edit workflow."

### Engineering Manager View (people manager)

The manager for "Backend Team" sees their reports across all project assignments:

```
                Overall   Project A   Project B   Project C
Sarah            82        85          78          —
James            71        —           71          —
Priya            68        72          —           64
                           ↑ her best             ↑ new project, ramping up
```

**Insight:** "Priya scores 72 on Project A but 64 on Project C — she started Project C 2 weeks ago. Normal ramp-up pattern. If score doesn't improve in 4 weeks, investigate."

### VP/Org View

```
Org AI Effectiveness: 71/100 B  ↑ +6 from Q3

By Project:                          By Team:
  Web App Redesign    72  B            Backend     76  B
  Mobile Client       68  C+           Frontend    69  C+
  Data Pipeline       79  B+           Mobile      68  C+
  API Gateway         64  C            Platform    81  B+
  Infra Automation    81  B+           Data        75  B

Total AI spend: $4,230/month across 42 developers ($101/dev/month)
Top provider: Claude Code (78%), Cursor (15%), Copilot (7%)
```

**Insight:** "Platform team scores 81 with $85/dev/month. Mobile team scores 68 with $120/dev/month. Investigate: mobile may benefit from the prompt coaching that worked for platform last quarter."

---

## Flow 4: Adding a Second Provider (Cursor)

### What changes for the developer

```bash
clue extract --provider cursor    # one-time: parse existing Cursor data
clue config --providers claude-code,cursor   # enable both
```

The PostStop hook continues to run for Claude Code automatically. For Cursor, the developer runs `clue extract --provider cursor` periodically (or we watch Cursor's data directory for changes).

### What the Cursor extractor does

```
~/.cursor/ (or Cursor's state directory)
  → Parse conversation/session data
  → Normalise to common metrics schema:
      - session_count, prompt_count (mapped from Cursor's concepts)
      - token_usage (input/output from API calls)
      - tool_actions (Cursor's tool equivalents: Apply, Terminal, Search, etc.)
      - correction_rate (follow-up edits to AI suggestions)
      - model_mix (which models Cursor uses)
  → Store in local SQLite alongside Claude Code data
  → Push scrubbed metrics with provider: "cursor"
```

### What changes on the server

Nothing. The `daily_metrics` table already has a `provider` column. A developer using both tools on the same project produces two rows per day:

```sql
user_id=7, project_id=1, date=2026-03-24, provider=claude-code, score=74, cost=3.20
user_id=7, project_id=1, date=2026-03-24, provider=cursor,      score=69, cost=1.50
```

The dashboard can show:
- Combined view (all providers aggregated)
- Per-provider comparison ("You score 74 on Claude Code but 69 on Cursor — your prompt quality is lower on Cursor")
- Cost comparison ("Claude Code: $3.20/day, Cursor: $1.50/day for similar work")

### Provider-specific scoring adjustments

Not all dimensions score identically across providers:

| Dimension | Claude Code | Cursor |
|---|---|---|
| Tool Mastery | Read→Edit workflow, tool diversity | Apply→Accept workflow, inline vs composer |
| Cost Awareness | Opus/Sonnet/Haiku model selection | Model selection (if exposed) |
| Cache Hit Rate | Explicit cache metrics | May not be available → dimension weight redistributed |

The scorer handles this via **provider profiles**:
```python
PROVIDER_PROFILES = {
    "claude-code": {
        "supported_dimensions": ["prompt_quality", "cost_efficiency", "wasted_spend",
                                  "tool_mastery", "session_discipline",
                                  "cost_awareness", "iteration_efficiency"],
        "weights": DEFAULT_WEIGHTS,
    },
    "cursor": {
        "supported_dimensions": ["prompt_quality", "cost_efficiency", "wasted_spend",
                                  "tool_mastery", "session_discipline",
                                  "iteration_efficiency"],
        # cache_hit_rate not available → cost_awareness scored differently
        "weights": CURSOR_WEIGHTS,  # redistributed to available dimensions
    },
}
```

Cross-provider scores are **not directly compared** unless both support the same dimensions. The dashboard shows "scored on 7/7 dimensions" vs "scored on 6/7 dimensions" alongside the number.

---

## Flow 5: Data Accuracy Guarantees

This is the section that matters most. If leadership makes decisions based on these numbers, the numbers must be right.

### What we verify at each stage

**Stage 1: Extraction (developer machine)**
- Token dedup: group by `message.id:requestId`, take last entry (cumulative total)
- Multi-tool attribution: one API response with 3 tool_use blocks → tokens counted once, not 3x
- Per-model cost: each turn priced at its actual model rate, not a default
- Session boundaries: derived from `sessionId` in JSONL, not heuristics
- Project attribution: derived from `cwd` field per prompt, not per session

Verified by: 187 tests including unit, integration, and security tests with 87% coverage ratchet.

**Stage 2: Export + Scrub (developer machine)**
- Three-path cost consistency: `total_cost == sum(daily_cost) == sum(per_project_cost)`
- Session count accuracy: counted from sessions table, not prompts table
- Scrub completeness: no project names, no paths, no prompt text in output
- JSON serialisation: every value is JSON-serialisable (tested)

Verified by: integration tests that round-trip through extract → store → export → JSON.

**Stage 3: Push (transport)**
- Idempotent: pushing the same day twice overwrites, doesn't duplicate
- Checksummed: payload includes hash of daily_metrics for integrity verification
- Versioned: schema version in payload so server can handle old/new clients

**Stage 4: Server ingestion**
- Upsert: `INSERT ON CONFLICT (user_id, project_id, date, provider) DO UPDATE`
- Validation: reject payloads with impossible values (negative tokens, score > 100, etc.)
- Audit trail: every push logged with timestamp, user, payload hash

**Stage 5: Materialised views (server)**
- Views are derived from `daily_metrics` only — no separate data path
- Views refresh on schedule (every 15 minutes) or on demand
- Any number shown in the dashboard can be traced back to the `daily_metrics` rows that produced it

### How we prevent drift

The server never computes tokens or cost. These are calculated on the developer's machine where the raw JSONL data lives. The server receives pre-computed metrics and stores them. This means:

- If the pricing table changes, we update the CLI and developers re-push. The server doesn't care.
- If a new Claude Code version changes JSONL format, we update the extractor. The server doesn't care.
- If a new provider is added, we write a new extractor. The server doesn't care.

The server's job is: receive, store, aggregate, serve. All intelligence is at the edges.

---

## Flow 6: Admin Setup (Team Service)

### Initial setup

```bash
# Self-hosted
docker compose up -d    # Postgres + API + Dashboard

# Or managed
# Sign up at clue.yourcompany.com → get org endpoint
```

### Create org structure

Admin UI or API:

```bash
# Create teams (people groups — org chart)
clue-admin team create "Backend Team" --manager sarah@company.com
clue-admin team create "Frontend Team" --manager james@company.com
clue-admin team create "Mobile Team" --manager priya@company.com

# Create projects (work units — may span multiple teams)
clue-admin project create "Web App Redesign" --client "Acme Corp" \
  --git-remotes github.com/org/web-app,github.com/org/web-app-v2

clue-admin project create "Mobile Client" --client "Acme Corp" \
  --git-remotes github.com/org/mobile-app

# Generate API keys for developers
clue-admin user create dev@company.com --team "Backend Team" \
  --output-key    # prints: clue_sk_a1b2c3...

# Or bulk import
clue-admin users import team-roster.csv
```

### Project membership

Two modes:
1. **Auto-detect** (default): when a developer pushes data with `project_hint: "github.com/org/web-app"`, the server matches it to the project and adds them to `project_members` with `from_date = today`. If they stop pushing for that project for 14 days, `to_date` is set.

2. **Manual override**: admin explicitly assigns developers to projects with date ranges. Useful for contractors, rotations, or when git remotes don't map cleanly.

### Access control

| Role | Sees |
|---|---|
| Developer | Own data across all projects. Team average (anonymised). |
| Project Lead | All developers on their project. Project metrics. |
| Team Manager | All reports across all their projects. Team-level aggregates. |
| VP / Practice Lead | All teams, all projects in their practice area. |
| Org Admin | Everything. User management. API key management. |

Roles derived from SSO groups or manually assigned.

---

## Summary: What Moves Where

```
Developer Machine                          Team Server
─────────────────                          ───────────

~/.claude/*.jsonl
     │
     ▼
clue extract
 (dedup, parse, attribute)
     │
     ▼
Local SQLite
 (full data, personal use)
     │
     ▼
clue export --scrub
 (strip prompt text, paths,
  project names → git remotes,
  compute scores locally)
     │
     ▼
clue push ─── HTTPS POST ──────────────▶  POST /v1/push
                                            │
  Payload:                                  ▼
  - daily metrics (counts, not content)   Validate + upsert
  - scores (pre-computed)                   │
  - cost (pre-computed)                     ▼
  - project_hint (git remote only)        PostgreSQL
  - provider name                          daily_metrics table
                                            │
  NOT in payload:                           ▼
  - prompt text                           Materialised views
  - conversation content                   (project, team, org rollups)
  - file paths                              │
  - code                                    ▼
  - branch names                          Dashboard
                                           (project view, team view,
                                            org view, dev self-view)
```

The boundary is clear: **raw data stays on the developer's machine. Only scrubbed, pre-scored, pre-costed metrics cross the wire.** The server is a dumb aggregation layer — all intelligence (extraction, dedup, scoring, cost calculation) happens at the edge where the data lives.
