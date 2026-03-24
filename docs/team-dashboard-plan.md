# CLUEI — AI Efficiency Intelligence for Engineering Orgs

## The Problem

Engineering leaders have no visibility into whether AI tools are actually improving delivery. Developers use Claude Code, Gemini, Copilot, and Cursor daily — often multiple tools across the same org — but leadership can't answer:

- Is AI making us faster or just more expensive?
- Who's effective with AI and who needs coaching?
- Which projects benefit most from AI assistance?
- Are we getting better over time or plateauing?
- What does good AI-assisted development look like at our org?

Individual developers can't answer these either — they have gut feel, not data.

And it gets worse: most orgs are multi-tool. One team uses Claude Code, another uses Copilot, a third uses Cursor. There's no unified view of AI effectiveness across the org. Each tool has its own billing dashboard showing token counts — none of them measure whether the tokens translated into delivered software.

## The Bet

Organisations that measure and coach AI usage will outperform those that don't. The gap between a developer who scores 40/100 and one who scores 85/100 on AI efficiency is not talent — it's technique. Technique is coachable. But you can't coach what you can't see.

This is tool-agnostic. A developer who writes vague prompts in Cursor is making the same mistake as one who writes vague prompts in Claude Code. The scoring dimensions — prompt quality, cost efficiency, session discipline, iteration efficiency — apply to every AI coding tool. The data sources differ; the coaching is universal.

## What Exists Today

CLUEI is a Python CLI tool that:
- Extracts all Claude Code usage data from `~/.claude/`
- Scores developers 0-100 across 7 dimensions (prompt quality, cost efficiency, tool mastery, session discipline, etc.)
- Generates actionable coaching recommendations
- Provides `cluei score` for terminal-based scoring and recommendations
- Exports scrubbed (privacy-safe) JSON for sharing
- Merges multiple exports for basic team comparison

Claude Code is the first provider. The architecture is designed to be provider-agnostic — the scoring engine evaluates behaviours (prompt length, correction rate, tool workflow, session depth), not Claude-specific features.

The CLI and local Streamlit dashboard serve as the prototyping ground. The production dashboard is a single Next.js application with role-based views (see Architecture Decisions below).

## Vision: The AI Effectiveness Layer

Clue becomes the measurement and coaching layer that sits above all AI coding tools. Not a replacement for any tool's own analytics — a unified view that answers "how effectively is my org using AI?" regardless of which tools they use.

```
┌─────────────────────────────────────────────────────────┐
│                    Clue Team Dashboard                   │
│   Unified AI effectiveness scoring across all tools      │
│   Coaching · Benchmarks · Cost · Delivery correlation    │
└──────────┬──────────┬──────────┬──────────┬─────────────┘
           │          │          │          │
     ┌─────▼───┐ ┌───▼────┐ ┌──▼───┐ ┌───▼────┐
     │ Claude  │ │ Gemini │ │Cursor│ │Copilot │
     │  Code   │ │  CLI   │ │      │ │        │
     └─────────┘ └────────┘ └──────┘ └────────┘
```

Each provider has a different local data format. Clue normalises them into a common metrics schema — the same 7-dimension score regardless of which tool generated the session.

## What We're Building

A self-hosted or managed server (like SonarQube) that collects scrubbed metrics from every developer's machine — across all AI coding tools — and presents AI effectiveness analytics through a single Next.js dashboard. One dashboard serves all roles: developers see their own data, project leads see their project, VPs see the org. The server only receives aggregated, scrubbed data — never prompt text, never project names (unless the org opts in), never file paths.

## Org Model: Service Company Reality

This is built for service-based orgs where:
- **People rotate across projects.** A developer works on Project A this sprint, Project B next sprint, both simultaneously next month.
- **Projects have fluid teams.** Project X starts with 3 developers, scales to 8, then winds down to 2.
- **Sub-teams exist within projects.** A project might have a backend squad, a mobile squad, and an infra squad — each with different AI effectiveness patterns.
- **Leadership slices both ways.** "How is Developer Y performing across all their projects?" AND "How is Project X performing across all its developers?"
- **Billing matters per project.** Clients may be charged for AI tool costs. The org needs per-project cost attribution.

The data model must support a **many-to-many relationship** between developers and projects, with time as the third axis. A developer's efficiency score on Project A may be very different from their score on Project B (different codebase, different complexity, different tools).

### The two axes

```
                    Project A    Project B    Project C
Developer 1         [score]      [score]         —
Developer 2         [score]         —          [score]
Developer 3         [score]      [score]       [score]

Slice by row:  "How is Developer 3 doing across all projects?"
Slice by col:  "How is Project B doing across all developers?"
Slice by cell: "How is Developer 3 doing specifically on Project B?"
Slice by time: "How did Project A's team perform this quarter vs last?"
```

## Users and What They Need

### Project Lead / Delivery Manager
- "How effectively is my project team using AI? Are we getting value for cost?"
- "Which developers on my project have the highest correction rate? They need coaching."
- "This project's AI cost is 3x higher than a similar project — why?"
- "New developer joined the project last week — how quickly are they ramping up with AI tools?"

### Engineering Manager (people manager)
- "How are my reports performing across their different project assignments?"
- "Developer Y's score dropped this month — is it the new project or a pattern?"
- "Which of my reports should I nominate for the AI best-practices guild?"

### VP/Head of Engineering / Practice Lead
- "Give me one number: is AI working for us?"
- "Compare Project A vs Project B AI effectiveness — same team size, different outcomes. Why?"
- "What's our org-wide cost per developer per month? Per project per month?"
- "Which practice area (backend, mobile, data) gets the most value from AI?"

### Developer (opt-in self-view)
- "How do I compare to others on this project?"
- "My score on Project A is 80 but on Project B it's 55 — what's different?"
- "What's my trend over the last 3 months across all projects?"

### CTO/Founder
- "ROI per client project. Are we faster with AI? Can we demonstrate it?"
- "Should we invest in AI coaching or just buy more seats?"
- "Which AI tool (Claude/Cursor/Copilot) is most effective for which type of work?"

## Privacy Model — Non-Negotiable

This is the single most important architectural decision. Get it wrong and no developer will opt in.

**What the team dashboard NEVER sees:**
- Prompt text (what the developer typed)
- Conversation content (what Claude responded)
- File paths or file contents
- Absolute project paths
- Git diffs or code

**What the team dashboard sees (scrubbed):**
- Efficiency score (0-100) and 7 dimension breakdown
- Token counts and estimated cost (aggregated by day)
- Session count, prompt count, average prompt length (chars, not content)
- Tool usage distribution (Read, Edit, Bash — counts only)
- Model mix (% Opus vs Sonnet vs Haiku)
- Correction rate (% of prompts that were corrections)
- Cache hit rate
- Stop reason distribution
- Working hour patterns (hour-of-day, day-of-week)

**Optional (org chooses):**
- Project names (some orgs want per-project cost tracking, others don't)
- Branch activity patterns (no branch names, just counts)
- Git correlation metrics (sessions-to-commits ratio, time-to-value)

The scrub boundary is enforced on the developer's machine before data leaves. The server cannot request unscrubbed data. This is a trust architecture, not a policy.

## Architecture

### Provider Abstraction

The key architectural decision: separate **extraction** (provider-specific) from **scoring** (universal).

```
Provider Extractors (one per tool, runs on developer machine):
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Claude Code  │ │ Gemini CLI   │ │ Cursor       │ │ Copilot      │
│ extractor    │ │ extractor    │ │ extractor    │ │ extractor    │
│              │ │              │ │              │ │              │
│ ~/.claude/   │ │ ~/.gemini/   │ │ ~/.cursor/   │ │ VS Code      │
│ JSONL files  │ │ log files    │ │ state DB     │ │ telemetry    │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │                │
       └────────────────┴────────────────┴────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Common Metrics Schema │
                    │                       │
                    │  provider: string      │
                    │  session_count: int    │
                    │  prompt_count: int     │
                    │  token_usage: {}       │
                    │  cost_usd: float       │
                    │  tool_actions: {}      │
                    │  correction_rate: float│
                    │  avg_prompt_chars: int │
                    │  model_mix: {}         │
                    │  cache_hit_rate: float │
                    │  session_depths: []    │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Scoring Engine        │
                    │  (provider-agnostic)   │
                    │                       │
                    │  7 dimensions, 0-100   │
                    │  Same rubric for all   │
                    └───────────────────────┘
```

Each extractor normalises its tool's raw data into the common schema. The scorer doesn't know or care which tool generated the data. A session is a session, a prompt is a prompt, a correction is a correction — the scoring rubric is about developer behaviour, not tool features.

### What differs per provider

| Dimension | Claude Code | Copilot | Cursor | Gemini CLI |
|---|---|---|---|---|
| **Data location** | `~/.claude/projects/**/*.jsonl` | VS Code telemetry / extension logs | `~/.cursor/` SQLite | `~/.gemini/` (TBC) |
| **Token visibility** | Full (input, output, cache) | Limited (completions only) | Full (API passthrough) | Full |
| **Tool usage** | Explicit (Read, Edit, Bash, etc.) | Implicit (accept/reject/edit) | Explicit (similar to Claude) | Explicit |
| **Session boundary** | Clear (sessionId in JSONL) | Ambiguous (continuous inline) | Clear (composer sessions) | Clear |
| **Cost data** | Derivable from tokens + model | Bundled in subscription | Derivable from tokens | Derivable |
| **Correction signal** | User sends follow-up correction | User edits/rejects suggestion | User sends correction | Similar to Claude |

Some dimensions score differently per provider out of necessity:
- **Tool Mastery** for Copilot measures accept/reject/edit ratio instead of Read→Edit workflow
- **Cost Awareness** for subscription tools (Copilot) becomes "usage efficiency per seat" rather than per-token cost
- **Cache Hit Rate** only applies to tools that expose cache metrics

The scoring engine handles this via **provider profiles** — each provider declares which dimensions it can fully score, partially score, or skip. The overall score normalises across available dimensions.

### System Architecture

```
┌─────────────────────────────────────────────────┐
│  Developer Machine                              │
│                                                 │
│  cluei extract --provider claude  (PostStop hook)│
│  cluei extract --provider cursor  (on-demand)   │
│  cluei extract --provider copilot (on-demand)   │
│              ──→ local SQLite (scoring + CLI)    │
│                                                 │
│  cluei push ──→ scrubs locally ──→ HTTPS POST ─┼──┐
└─────────────────────────────────────────────────┘  │
                                                     │
┌────────────────────────────────────────────────────▼──┐
│  Clue Team Service                                    │
│                                                       │
│  POST /v1/push      — ingest scrubbed daily metrics   │
│  GET  /v1/project   — project dashboard data          │
│  GET  /v1/team      — team (people group) dashboard   │
│  GET  /v1/user      — individual trend (self-view)    │
│  GET  /v1/org       — org-wide rollup                 │
│                                                       │
│  All endpoints accept: ?project_id= &team_id=         │
│    &user_id= &provider= &from= &to=                  │
│                                                       │
│  Auth: API key per developer (push)                   │
│        SSO/OAuth for dashboard (read)                 │
│        Role-based: dev sees self, lead sees project,  │
│          manager sees team, VP sees org                │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │  PostgreSQL                                     │  │
│  │                                                 │  │
│  │  ── Identity ──                                 │  │
│  │  orgs            — id, name                     │  │
│  │  teams           — id, org_id, name             │  │
│  │  projects        — id, org_id, name, client,    │  │
│  │                    status (active/completed)     │  │
│  │  users           — id, org_id, name, role,      │  │
│  │                    api_key_hash                  │  │
│  │  team_members    — user_id, team_id,            │  │
│  │                    from_date, to_date            │  │
│  │  project_members — user_id, project_id,         │  │
│  │                    from_date, to_date, role      │  │
│  │                                                 │  │
│  │  ── Metrics (the core — atomic unit) ──         │  │
│  │  daily_metrics   — user_id, project_id, date,   │  │
│  │                    provider, scores_json,        │  │
│  │                    tokens, costs, tool_counts,   │  │
│  │                    model_mix, correction_rate,   │  │
│  │                    session_count, prompt_count,  │  │
│  │                    cache_hit_rate,               │  │
│  │                    avg_prompt_chars              │  │
│  │                                                 │  │
│  │  PK: (user_id, project_id, date, provider)      │  │
│  │  One row per dev × project × day × provider.    │  │
│  │  This is the atomic grain. All views are         │  │
│  │  rollups of this table.                         │  │
│  │                                                 │  │
│  │  ── Reference ──                                │  │
│  │  providers       — id, name, version,           │  │
│  │                    supported_dimensions          │  │
│  │                                                 │  │
│  │  ── Materialized views (all derive from         │  │
│  │     daily_metrics + membership tables) ──       │  │
│  │                                                 │  │
│  │  Slice by developer (across projects):          │  │
│  │    user_weekly_rollup                           │  │
│  │    user_project_comparison                      │  │
│  │                                                 │  │
│  │  Slice by project (across developers):          │  │
│  │    project_weekly_rollup                        │  │
│  │    project_member_comparison                    │  │
│  │    project_cost_attribution                     │  │
│  │                                                 │  │
│  │  Slice by team (people group):                  │  │
│  │    team_weekly_rollup                           │  │
│  │                                                 │  │
│  │  Slice by org:                                  │  │
│  │    org_monthly_rollup                           │  │
│  │    provider_comparison                          │  │
│  │    project_comparison                           │  │
│  └─────────────────────────────────────────────────┘  │
│                                                       │
│  Next.js Dashboard: role-based views                   │
│  (dev self-view, project, team, org)                   │
└───────────────────────────────────────────────────────┘
```

## What We Reuse From Clue

| Component | Reuse | How |
|---|---|---|
| `scorer.py` | 90% | Import as library. Add provider profiles for dimension availability. Scoring rubric is provider-agnostic |
| `models.py` | 80% | Add `provider` field to core dataclasses. Extend with common metrics schema |
| `patterns.py` | 100% | Regex patterns for prompt analysis (correction detection, file references, etc.) apply to all providers |
| `extractor.py` | 100% | Becomes the Claude Code provider extractor. Stays on developer machines unchanged |
| `export.py` scrub logic | 90% | Scrub runs client-side before push. Provider-agnostic — operates on common schema |
| `export.py` query patterns | 70% | SQL patterns translate to Postgres with added user_id/team_id/provider filters |
| Dashboard UX patterns | 40% | Tab structure, KPI layouts, chart types translate to Next.js. Streamlit dashboard served as prototype — production dashboard is Next.js from day one |

## What's New

| Component | Description | Size |
|---|---|---|
| Provider abstraction | Common metrics schema + provider profile interface | Small |
| Cursor extractor | Reads `~/.cursor/` state, normalises to common schema | Medium |
| Copilot extractor | Reads VS Code extension telemetry, normalises to common schema | Medium |
| Gemini extractor | Reads `~/.gemini/` logs, normalises to common schema | Medium (when Gemini CLI matures) |
| `clue push` CLI command | POST scrubbed metrics to team service. Runs after each session or on-demand | Small |
| API service | FastAPI with 3-4 endpoints. Auth middleware. Postgres connection | Medium |
| Postgres schema | 5-6 tables + materialized views. provider column on all metric tables | Small |
| Team scoring | Re-score with team-relative percentiles across providers | Small (extends scorer.py) |
| Dashboard | Next.js with role-based views, team/user/date/provider filters, SSO | Medium-Large |
| Provider comparison view | "Claude Code vs Cursor: cost efficiency, session outcomes" per org | Small |
| Admin panel | Manage teams, API keys, provider opt-in settings | Small |

## Competitive Landscape

### What exists today

| Tool | What it does | What it doesn't do |
|---|---|---|
| **ccusage** | CLI token/cost reports for Claude Code | No scoring, no coaching, no team view, no multi-provider. Has a token counting bug (64% output undercount due to first-wins dedup on cumulative entries) |
| **Copilot Metrics API** | GitHub-provided acceptance rates and active users | Locked to Copilot. No prompt quality, no session analysis, no cross-tool view |
| **Cursor Analytics** | Basic token/cost in the Cursor dashboard | Per-user only, no team aggregation, no scoring |
| **DORA / Sleuth / LinearB** | Engineering delivery metrics | Measures delivery, not AI effectiveness. No connection between AI usage and output |
| **Pluralsight Flow** | Developer productivity analytics | Code-centric (commits, PRs). Doesn't understand AI-assisted sessions |

### The gap

Nobody measures **AI effectiveness** — how well developers use AI, not just how much. The industry tracks tokens spent (input metric) or PRs merged (output metric) but not the quality of the interaction that connects them. That's the Clue position: the coaching and measurement layer between AI tool and delivery outcome.

### Design principles (learned from best-in-class)

From **DORA**: Use metrics for improvement, never punishment. Teams that weaponise metrics against developers see gaming and attrition. Clue's team view defaults to anonymised and shows team aggregates before individual breakdown.

From **SonarQube**: Quality gates that ratchet. Once a team reaches 70/100 efficiency, they shouldn't drop below it. Alert on regression, celebrate improvement.

From **Datadog/Grafana**: Dashboards are only useful if they answer a question in under 10 seconds. Every view must have a clear "so what" — not just charts, but recommendations and next actions.

From **GitHub Copilot Metrics**: Acceptance rate alone is misleading. A developer who accepts 90% of suggestions but constantly edits them afterward is less effective than one who accepts 60% but ships them as-is. Measure the full cycle.

## Phases

### Phase 1 — Push + Collect for Claude Code (2 weeks)

**Goal:** Scrubbed data flows automatically from developer machines to a central Postgres.

- `clue push` command that runs `export --scrub` and POSTs the JSON to a configured endpoint
- Minimal FastAPI service with `POST /v1/push` (API key auth)
- Postgres schema: `users`, `teams`, `daily_metrics`, `providers`
- `provider` column on all metric tables from day one (even though only Claude Code exists)
- Common metrics schema defined as the contract between extractors and the server
- Update PostStop hook to include push after extract
- No dashboard yet — just validate data is flowing

**Done when:** 5 developers pushing daily, data visible in Postgres.

### Phase 2 — Dashboard (3 weeks)

**Goal:** One Next.js dashboard that serves all roles — developer self-view through to org overview.

- Next.js app with role-based views:
  - **Developer**: own scores, trends, per-project breakdown, recommendations
  - **Project Lead**: all developers on project, project cost, coaching recommendations
  - **Manager**: reports across all projects, team aggregates
  - **VP/Org**: all teams, all projects, provider comparison, cost rollup
- `GET /v1/team?team_id=X&range=90d&provider=all` returns aggregated team data
- SSO/OAuth login (NextAuth.js)
- Quality gate: alert when team score drops below threshold
- Deployment: same Docker Compose as Phase 1 — adds Next.js container

**Done when:** Engineering managers are checking the dashboard weekly.

### Phase 3 — Multi-Provider + Org Intelligence (3 weeks)

**Goal:** Support Cursor as second provider. Give leadership cross-tool visibility.

- Cursor extractor: reads `~/.cursor/` state, normalises to common schema
- Provider profiles: declare which scoring dimensions each provider supports
- Scorer updates: handle partial dimension availability gracefully
- Provider comparison view: "Claude Code users score 72 avg, Cursor users score 65 avg — here's where they differ"
- Org-wide rollup: total AI spend across all tools, average efficiency, trend
- Cross-team comparison
- Delivery correlation: efficiency score vs commit frequency
- Weekly email digest to managers

**Done when:** At least 2 providers reporting data, leadership using cross-tool view.

### Phase 4 — Copilot + Gemini + Scale (3 weeks)

**Goal:** Full multi-provider coverage. Production-grade hosting.

- Copilot extractor: VS Code extension telemetry → common schema
- Gemini CLI extractor (when Gemini CLI reaches sufficient adoption)
- Provider-specific scoring adjustments (Copilot accept/reject/edit vs Claude tool workflow)
- Self-serve team creation and API key management
- Historical trend analysis and anomaly detection

**Done when:** Org can answer "how effective are we with AI?" across all tools.

### Phase 5 — Platform (ongoing)

- Webhook integrations (Slack digest, Jira/Linear correlation)
- API for custom reporting and BI integration
- Exportable reports for leadership reviews
- Benchmarking across orgs (anonymised, opt-in): "Your org's AI efficiency is in the 75th percentile"
- AI coaching assistant: personalised improvement plans based on score breakdown

## Deployment Model (SonarQube pattern)

Same product, two deployment options. Like SonarQube: one codebase, choose where it runs.

### Self-hosted
- `docker compose up` → FastAPI + Postgres + Next.js
- Runs on any cloud VM, ECS, or Kubernetes
- Data never leaves the org's infrastructure
- Fits security-sensitive orgs and enterprises
- Org owns upgrades and ops

### Managed (CLUEI Cloud)
- We run the service, orgs push to our endpoint
- Scrub mode enforced client-side — trust architecture, not policy
- Zero ops for customers
- Revenue model: per-seat SaaS
- Same Docker images, managed by us

### Distribution
- No PyPI — CLUEI CLI distributed via own installer: `curl -sSL https://cluei.dev/install.sh | bash`
- Installer detects environment, installs CLI agent, connects to team server
- Server distributed as Docker images (self-hosted) or hosted by us (managed)

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Developers don't opt in (privacy concern) | High | Fatal | Scrub mode is default and enforced client-side. Open source the push logic. Developers can audit exactly what leaves their machine |
| Scores feel like surveillance | High | High | Frame as coaching, not monitoring. DORA principle: metrics for improvement, never punishment. Show individual trend before team comparison. Anonymised by default |
| Gaming the metrics | Medium | Medium | Scores are composite across 7 dimensions — hard to game without genuinely improving. Flag anomalies (sudden score jumps) |
| Scale bottleneck at Postgres | Low | Medium | Daily metrics per user = ~1 row/day. 100 devs × 365 days = 36,500 rows/year. Postgres handles this trivially |
| Claude Code changes JSONL format | Medium | High | Extractor already handles format variations. Pin to known schema versions. Monitor for new fields |
| Org wants metrics Clue doesn't compute | High | Medium | The raw daily_metrics table stores enough granularity to derive new aggregations without re-collection |
| Provider data access changes | High | High | Copilot and Cursor could restrict local data access at any time. Mitigate: support official APIs where available, maintain local extraction as fallback, design graceful degradation (score with available dimensions) |
| Comparing scores across providers is misleading | Medium | High | Not all dimensions are available for all providers. Never show raw cross-provider score comparison without normalisation. Show "scored on 5/7 dimensions" alongside the number |
| Provider moat — competitors copy the scoring | Medium | Low | The scoring engine is open source and that's fine. The moat is the team layer, cross-provider normalisation, and coaching recommendations — network effects, not algorithms |
| Building extractors for moving targets | High | Medium | Each provider's local data format is undocumented and changes without notice. Community-maintained extractors with version pinning. Accept that some providers will break periodically |

## Success Metrics

| Metric | Target | Timeframe |
|---|---|---|
| Developer opt-in rate | >80% of org | Phase 1 + 30 days |
| Org-wide efficiency score improvement | +10 points average | 6 months |
| Project lead dashboard usage | Weekly active | Phase 2 + 30 days |
| Cost-per-developer trend | Flat or declining while output increases | 6 months |
| Per-project AI cost visibility | 100% of active projects tracked | Phase 2 + 60 days |
| Developer satisfaction with AI coaching | NPS > 30 | Phase 3 + 30 days |
| Cross-project coaching impact | Developers who rotate carry improved scores to new projects | 6 months |

## Open Questions

1. **Opt-in vs opt-out?** Should push be automatic after setup, or require explicit developer consent each time?
2. **Anonymised by default?** Should the project view show developer names or anonymous IDs? Threshold rule: teams <5 are always anonymised to prevent identification.
3. **Project mapping** — how does a developer's local project path map to the org's project? Options: (a) developer sets `clue config --project "Project X"` per repo, (b) infer from git remote URL, (c) admin maps git remotes to projects in the team service. Option (b) is the least friction.
4. **Project cost attribution** — can the org bill AI costs per project to clients? This requires unanonymised project names in the team view, which conflicts with scrub mode. Solution: separate "project label" (set by admin, not derived from filesystem) from "project path" (always scrubbed).
5. **Rotation handling** — when a developer moves from Project A to Project B, how is the transition detected? Options: (a) `project_members` table managed manually by admin, (b) auto-detect from which project the developer is pushing data for, (c) both — auto-detect with admin override.
6. **Cross-project scoring** — should a developer's overall score average across all their projects, or is it always per-project? Recommendation: always show per-project, with a weighted average as the "overall" (weighted by session count on each project).
7. **Integration with existing tools?** Jira/Linear for delivery correlation, Slack for digests, SSO provider for auth. Which are Phase 2 vs Phase 4?
8. **Pricing model?** Free for self-hosted, per-seat for managed? Free tier up to N developers?

## Naming — Resolved

**CLUEI** — **C**ode **L**everage, **U**tilization & **E**fficiency **I**ndex

One name for everything:
- CLI: `cluei` (extract, score, push)
- Server: `cluei-server` (Docker image)
- Dashboard: part of the server, accessed via browser
- Provider-neutral: no AI tool name in the brand

## Decision: Build or Wait?

**Build if:**
- You have >10 developers using AI coding tools (any combination)
- Leadership is asking "what are we getting for our AI spend?"
- You believe AI effectiveness is coachable (it is)
- You want to understand which AI tools work best for which teams
- You want a competitive advantage in engineering productivity

**Wait if:**
- <5 developers (manual merge works fine)
- Single tool, single team (personal Clue dashboard is sufficient)
- No org interest in AI metrics yet

## Architecture Decisions

### One dashboard, not two

The personal Streamlit dashboard and team dashboard are not separate products. One Next.js dashboard serves all roles via role-based views:
- Developer opens it → sees only their own data (same information as `cluei score`, but visual)
- Project lead → sees their project's developers
- VP → sees org rollup

**Why:** Maintaining two dashboard stacks (Streamlit + Next.js) is a long-term cost with no benefit. The "personal" view is just the team dashboard filtered to `user_id = me`. SonarQube doesn't have a "personal SonarQube" and a "team SonarQube" — it's one product with scoped views.

The existing Streamlit dashboard served its purpose: prototyping, screenshots, validating the UX. It stays in the CLI for local/offline use but is not the production dashboard.

### CLI stays Python, dashboard is Next.js

The CLI (extract, score, push) stays Python because the extraction logic, scoring engine, and 187 tests already exist. Rewriting in Go for single-binary distribution is a future optimisation, not a current need.

The dashboard is Next.js because it needs auth (NextAuth.js), role-based views, SSO, multi-tenancy, and embedding — none of which Streamlit handles well.

### No PyPI

The product is a self-hosted/managed server, not a Python library. Distribution is via:
- Own installer (`curl -sSL https://cluei.dev/install.sh | bash`) for the CLI agent
- Docker images for the server
- PyPI doesn't serve the product vision — it's a distribution channel for individual Python packages, not team products

### SonarQube deployment model

Same codebase, two deployment options. Self-hosted (`docker compose up`) or managed (we host it). The CLI agent doesn't care which — it pushes to an endpoint URL.

## Bottom Line

Every engineering org is spending on AI coding tools. None of them can answer whether it's working — and in a service company, they can't even attribute the cost to the right project.

CLUEI already solves the hard problem: defining and measuring what "good AI-assisted development" looks like, across 7 dimensions, with actionable coaching. This works today for individual developers with Claude Code.

The stack:
- **`cluei` CLI** — Python (extract, score, push)
- **CLUEI Server** — FastAPI + Postgres + Next.js dashboard

The path to a multi-provider, multi-project team product:

1. **`cluei push`** — scrubbed data flows from developer machines to central Postgres
2. **Next.js dashboard** — one dashboard, role-based views, developer through to VP
3. **Provider extractors** — Claude Code first, Cursor next, Copilot and Gemini to follow
4. **Data model: developer × project × day × provider** — the atomic grain that supports every slice

The scoring engine is the IP. The extractors are plumbing. The server is a standard API + Postgres. The real moat is being first to define AI effectiveness measurement that works across every tool, every project, and every team — and coaching orgs to get better at it.
