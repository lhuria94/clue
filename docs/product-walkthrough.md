# CLUEI — Product Walkthrough

What every user sees, screen by screen.

---

## 1. Developer Experience

### 1.1 First Time Setup

Developer runs setup on their machine:

```
$ ./setup.sh

  ✓ Python 3.12 detected
  ✓ Virtual environment created
  ✓ Clue installed
  ✓ Extracted 3,847 prompts from ~/.claude/
  ✓ PostStop hook installed — auto-capture after every session
  ✓ All 187 tests passing

  ┌──────────────────────────────────────────────────────┐
  │  AI Efficiency Score: 74/100  [B]  ↑ +4.2%          │
  │                                                      │
  │  Prompt Quality         62  C   ████████░░           │
  │  Cost Efficiency        81  B+  ██████████░          │
  │  Wasted Spend           78  B   █████████░░          │
  │  Tool Mastery           85  A   ██████████░          │
  │  Session Discipline     58  D+  ███████░░░           │
  │  Cost Awareness         79  B   █████████░░          │
  │  Iteration Efficiency   70  B-  ████████░░░          │
  │                                                      │
  │  Recommendations:                                    │
  │  1. Your most efficient sessions stay under 18 AI    │
  │     steps — keep tasks focused.                      │
  │  2. Include context in prompts: what file, what      │
  │     behaviour, what you expect.                      │
  │  3. Start fresh sessions for new tasks.              │
  └──────────────────────────────────────────────────────┘

  Run 'task start' to open your personal dashboard.
```

### 1.2 Connect to Team

Admin sends developer a Slack message:

> "Hey, we're rolling out AI effectiveness tracking. Run this:"
> `clue team join https://clue.company.com --key clue_sk_a1b2c3`

```
$ clue team join https://clue.company.com --key clue_sk_a1b2c3

  ✓ Connected to Clue Team at clue.company.com
  ✓ Identified as: dev@company.com
  ✓ Team: Backend Squad
  ✓ Auto-push enabled (scrubbed — no prompt text or file paths leave your machine)

  What gets sent:
    ✓ Efficiency scores (0-100)
    ✓ Token counts and estimated cost
    ✓ Tool usage counts (Read: 34, Edit: 21, etc.)
    ✓ Session count, prompt count, correction rate
    ✓ Project identifier (git remote URL only)

  What NEVER gets sent:
    ✗ Your prompt text
    ✗ AI responses
    ✗ File paths or code
    ✗ Branch names

  Run 'clue push --dry-run' to see exactly what will be sent.

  Pushing historical data... ✓ 127 days uploaded
```

### 1.3 Dry Run (Trust Builder)

The developer can see exactly what leaves their machine:

```
$ clue push --dry-run

  Would send to: https://clue.company.com/v1/push
  Payload size: 4.2 KB
  Date range: 2026-03-24

  Preview:
  ┌─────────────────────────────────────────────────┐
  │ date:           2026-03-24                      │
  │ project:        github.com/org/web-app          │
  │ provider:       claude-code                     │
  │ prompts:        47                              │
  │ sessions:       8                               │
  │ cost:           $4.82                           │
  │ score:          74/100                          │
  │ correction_rate: 6%                             │
  │ top tools:      Read(34) Edit(21) Bash(15)      │
  │ model mix:      Sonnet 85%, Opus 10%, Haiku 5%  │
  └─────────────────────────────────────────────────┘

  No prompt text. No file paths. No code. No branch names.
  Run 'clue push' to send for real.
```

### 1.4 Personal Dashboard (Already Exists)

The developer runs `task start` and sees their personal Clue dashboard at `localhost:8484`. This is unchanged from today — 7 tabs of personal analytics. The team connection is additive, not a replacement.

### 1.5 Self-View on Team Dashboard

When the developer logs into the team dashboard, they see a "My Performance" tab:

```
┌─────────────────────────────────────────────────────────────────┐
│  My AI Effectiveness                                            │
│                                                                 │
│  Overall: 74/100 B  ↑ +4 from last month                       │
│  Team average: 71    Org average: 69                            │
│  You're in the 68th percentile                                  │
│                                                                 │
│  By Project:                                                    │
│  ┌─────────────────────┬───────┬───────┬────────┬─────────────┐ │
│  │ Project             │ Score │ Trend │ Cost   │ Sessions/wk │ │
│  ├─────────────────────┼───────┼───────┼────────┼─────────────┤ │
│  │ Web App Redesign    │ 78    │ ↑ +3  │ $42/wk │ 12          │ │
│  │ API Gateway         │ 68    │ → 0   │ $28/wk │ 8           │ │
│  │ Data Pipeline       │ 72    │ ↑ +6  │ $15/wk │ 5           │ │
│  └─────────────────────┴───────┴───────┴────────┴─────────────┘ │
│                                                                 │
│  Your Strengths:                                                │
│  • Tool Mastery: 85 (top 15% of org)                            │
│  • Cost Efficiency: 81 (your sessions are lean)                 │
│                                                                 │
│  Where to Improve:                                              │
│  • Session Discipline: 58 — you have 3-4 sessions/week over    │
│    30 prompts. Try breaking these into smaller tasks.           │
│  • Prompt Quality: 62 — 38% of prompts are under 20 chars.     │
│    Adding file names and expected behaviour saves rework.       │
│                                                                 │
│  90-Day Trend:            Score                                 │
│  100 ┤                                                          │
│   80 ┤          ╭──╮  ╭───────╮ ╭──                             │
│   60 ┤─────╮╭──╯  ╰──╯       ╰─╯                               │
│   40 ┤     ╰╯                                                   │
│   20 ┤                                                          │
│      └────────────────────────────────────────                  │
│       Jan        Feb        Mar                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Project Lead Experience

### 2.1 Project Dashboard

The project lead for "Web App Redesign" logs in via SSO. They land on their project view:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Clue Team    Projects ▾   Teams ▾   Org ▾              Sarah Chen ▾       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Web App Redesign                              7d  30d  90d  All Time      │
│  Client: Acme Corp  |  Status: Active  |  6 developers                     │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Project Score │  │ AI Cost      │  │ Sessions     │  │ Correction   │   │
│  │    72/100     │  │  $342/mo     │  │  89/mo       │  │  Rate        │   │
│  │   B  ↑ +4    │  │  $57/dev     │  │  15/dev      │  │  8%          │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
│                                                                             │
│  vs Org:  Score +3 above avg  |  Cost -12% below avg  |  Correction -3%    │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Team Breakdown                                                 Sort: Score │
│  ┌──────────┬───────┬───────┬────────┬──────────┬──────────┬──────────────┐ │
│  │ Developer│ Score │ Trend │ Cost/wk│ Sessions │ Correct% │ Provider     │ │
│  ├──────────┼───────┼───────┼────────┼──────────┼──────────┼──────────────┤ │
│  │ Dev A    │  85   │ ↑ +3  │ $45    │   18     │  4%      │ Claude Code  │ │
│  │ Dev B    │  78   │ ↑ +1  │ $62    │   22     │  6%      │ Claude Code  │ │
│  │ Dev C    │  71   │ →     │ $38    │   12     │  8%      │ Cursor       │ │
│  │ Dev D    │  65   │ ↓ -5  │ $52    │   15     │  14%  ⚠ │ Claude Code  │ │
│  │ Dev E    │  61   │ ↑ +8  │ $78    │   14     │  12%     │ Claude+Cursor│ │
│  │ Dev F    │  58   │ →     │ $67    │    8     │  18%  ⚠ │ Claude Code  │ │
│  └──────────┴───────┴───────┴────────┴──────────┴──────────┴──────────────┘ │
│                                                                             │
│  ⚠ 2 developers with correction rate > 12%                                 │
│    Recommendation: share the prompt patterns guide. Developers with high    │
│    correction rates typically send prompts without specifying the file,     │
│    expected behaviour, or constraints.                                      │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Project Score Trend                                                        │
│                                                                             │
│  100 ┤                                                                      │
│   80 ┤                    ╭─────────────╮  ╭───── 72                        │
│   60 ┤───────╮╭──────────╯             ╰──╯                                │
│   40 ┤       ╰╯                                                             │
│   20 ┤                                                                      │
│      └──────────────────────────────────────────                            │
│       Oct    Nov    Dec    Jan    Feb    Mar                                │
│                                                                             │
│  ── Project ── Org Average                                                  │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Cost Breakdown                                                             │
│                                                                             │
│  By Model:          By Developer:        Weekly Trend:                      │
│  ┌─────────────┐    ┌─────────────┐     $100 ┤     ╭──╮                    │
│  │ ████ Son 72%│    │ ██ Dev E $78│      $75 ┤─╮ ╭╯  ╰╮╭─                 │
│  │ ██   Opu 18%│    │ ██ Dev F $67│      $50 ┤ ╰─╯    ╰╯                  │
│  │ █    Hai 10%│    │ █  Dev B $62│      $25 ┤                             │
│  └─────────────┘    │ █  Dev D $52│         └──────────────                 │
│                     │ █  Dev A $45│                                         │
│                     │ █  Dev C $38│                                         │
│                     └─────────────┘                                         │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Coaching Insights                                                          │
│                                                                             │
│  • Dev D's score dropped 5 points this month. Session depth increased       │
│    from avg 12 to avg 28 prompts. They may be staying in long sessions     │
│    instead of starting fresh. Suggest: "Start a new session for each        │
│    distinct task."                                                          │
│                                                                             │
│  • Dev E improved 8 points — fastest improvement on the project.            │
│    Their prompt length increased from avg 35 chars to avg 120 chars.       │
│    What changed? Worth sharing with the team.                              │
│                                                                             │
│  • Project cache hit rate is 45% vs org average 62%. Context may be        │
│    getting lost between sessions. Suggest: use CLAUDE.md files to          │
│    persist project context.                                                │
│                                                                             │
│  • Dev C uses Cursor exclusively. Their tool mastery scores differently    │
│    (scored on 6/7 dimensions). Consider this when comparing to Claude      │
│    Code users.                                                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Drill Into a Developer

Project lead clicks on "Dev D" to understand the score drop:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Dev D on Web App Redesign                             7d  30d  90d        │
│                                                                             │
│  Score: 65/100 C+  ↓ -5                                                    │
│                                                                             │
│  Dimension Breakdown:                                                       │
│  ┌──────────────────────┬────┬───────┬──────────────────────────────┐       │
│  │ Dimension            │ Sc │ Trend │ Detail                      │       │
│  ├──────────────────────┼────┼───────┼──────────────────────────────┤       │
│  │ Prompt Quality       │ 55 │ → 0   │ 42% under 20 chars          │       │
│  │ Cost Efficiency      │ 72 │ ↓ -8  │ p90/median spread: 4.2x     │       │
│  │ Wasted Spend         │ 60 │ ↓ -6  │ 14% correction rate         │       │
│  │ Tool Mastery         │ 78 │ → 0   │ Good Read→Edit workflow     │       │
│  │ Session Discipline   │ 42 │ ↓-12  │ 4 sessions over 30 prompts  │  ← ⚠ │
│  │ Cost Awareness       │ 75 │ → 0   │ 90% Sonnet, 10% Opus        │       │
│  │ Iteration Efficiency │ 62 │ ↓ -3  │ 14% corrections             │       │
│  └──────────────────────┴────┴───────┴──────────────────────────────┘       │
│                                                                             │
│  Root cause: Session Discipline dropped 12 points.                          │
│                                                                             │
│  Session Depth Distribution:                                                │
│  Last month:   ▃ ▅ ▃ ▂ ▇ ▃ ▅ ▂ ▃ ▅  (avg: 12, max: 22)                   │
│  This month:   ▂ ▃ ▂ █ ▃ ▂ █ ▂ █ ▃  (avg: 21, max: 45)  ← long sessions │
│                                                                             │
│  What to tell Dev D:                                                        │
│  "Your last 4 sessions averaged 35+ prompts each — that's a sign the      │
│   session lost context and you were fighting the AI instead of directing    │
│   it. Try starting fresh when you switch tasks or when the AI starts       │
│   making mistakes. Your tool mastery is strong (78) — the issue isn't      │
│   how you use tools, it's session length."                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Engineering Manager Experience

### 3.1 Team View (People Manager)

The engineering manager sees their reports across all project assignments:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Clue Team    Projects ▾   Teams ▾   Org ▾              James Park ▾       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Backend Squad                                          30d  90d  All      │
│  8 members  |  4 active projects  |  Manager: James Park                   │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Team Score   │  │ AI Cost      │  │ Improving    │  │ Need Help    │   │
│  │    76/100    │  │  $680/mo     │  │   5 of 8     │  │   2 of 8     │   │
│  │   B  ↑ +2   │  │  $85/dev     │  │   members    │  │   members    │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  My Reports — Cross-Project View                                            │
│                                                                             │
│  ┌──────────┬────────┬──────────────┬─────────────┬──────────────────────┐  │
│  │ Person   │Overall │ Projects     │ Cost/mo     │ Note                 │  │
│  ├──────────┼────────┼──────────────┼─────────────┼──────────────────────┤  │
│  │ Sarah    │  82    │ WebApp: 85   │ $95         │ Top performer        │  │
│  │          │  ↑ +3  │ API GW: 78   │             │                      │  │
│  ├──────────┼────────┼──────────────┼─────────────┼──────────────────────┤  │
│  │ Amir     │  79    │ WebApp: 79   │ $72         │ Consistent           │  │
│  │          │  ↑ +1  │              │             │                      │  │
│  ├──────────┼────────┼──────────────┼─────────────┼──────────────────────┤  │
│  │ Priya    │  70    │ DataPipe: 76 │ $88         │ Ramping on new proj  │  │
│  │          │  → 0   │ Mobile: 64   │             │ Mobile started 2 wks │  │
│  ├──────────┼────────┼──────────────┼─────────────┼──────────────────────┤  │
│  │ Dev D    │  65    │ WebApp: 65   │ $52         │ ⚠ Score dropped      │  │
│  │          │  ↓ -5  │              │             │ Session discipline    │  │
│  ├──────────┼────────┼──────────────┼─────────────┼──────────────────────┤  │
│  │ Kai      │  62    │ API GW: 62   │ $110        │ ⚠ High cost, low    │  │
│  │          │  → 0   │              │             │ score. Coaching rec.  │  │
│  ├──────────┼────────┼──────────────┼─────────────┼──────────────────────┤  │
│  │ ...      │        │              │             │                      │  │
│  └──────────┴────────┴──────────────┴─────────────┴──────────────────────┘  │
│                                                                             │
│  Coaching Actions:                                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Kai: $110/mo cost with 62 score. Their Opus usage is 35%         │  │
│  │    (team avg: 10%). Most of their Opus sessions could run on Sonnet.│  │
│  │    Action: 1:1 conversation about model selection.                   │  │
│  │                                                                      │  │
│  │ 2. Dev D: Session discipline dropped 12 points. Running long        │  │
│  │    sessions (avg 28 prompts vs team avg 14).                        │  │
│  │    Action: suggest session hygiene practices.                       │  │
│  │                                                                      │  │
│  │ 3. Priya: 64 on Mobile project (started 2 weeks ago). Normal ramp  │  │
│  │    pattern — her DataPipe score is 76. Flag if no improvement by    │  │
│  │    April 15.                                                         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Team Trend                                                                 │
│                                                                             │
│  100 ┤                                                                      │
│   80 ┤            ╭──────── Sarah (82)                                      │
│      ┤       ╭───╯╭─────── Amir (79)                                       │
│   70 ┤──╮╭──╯────╯  ╭──── Priya (70)                                      │
│      ┤  ╰╯     ╭───╯                                                       │
│   60 ┤────────╯─────────── Dev D (65)                                       │
│      ┤                                                                      │
│      └──────────────────────────────────                                    │
│       Oct    Nov    Dec    Jan    Feb    Mar                                │
│                                                                             │
│  ── Team Average                                                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. VP / Head of Engineering Experience

### 4.1 Org Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Clue Team    Projects ▾   Teams ▾   Org ▾              VP Eng ▾           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Organisation AI Effectiveness                 Q4 2025   Q1 2026           │
│                                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌────────────┐  │
│  │ Org Score     │  │ Total AI Cost │  │ Active Devs   │  │ Cost/Dev   │  │
│  │    71/100     │  │  $4,230/mo    │  │    42         │  │  $101/mo   │  │
│  │   B  ↑ +6    │  │  ↑ +12%       │  │  ↑ +8 new     │  │  ↓ -$14    │  │
│  │  from Q3     │  │  from Q4      │  │  this quarter │  │  from Q4   │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  └────────────┘  │
│                                                                             │
│  Reading: Cost up 12% but cost-per-developer DOWN $14. We added 8 devs    │
│  and total efficiency improved. AI investment is scaling well.             │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  By Project                                                    Sort: Score │
│  ┌────────────────────┬───────┬──────┬──────────┬──────────┬─────────────┐ │
│  │ Project            │ Score │Trend │ Cost/mo  │ Devs     │ Client      │ │
│  ├────────────────────┼───────┼──────┼──────────┼──────────┼─────────────┤ │
│  │ Infra Automation   │  81   │ ↑ +3 │ $420     │ 4        │ Internal    │ │
│  │ Data Pipeline      │  79   │ ↑ +5 │ $580     │ 6        │ BigCo       │ │
│  │ Web App Redesign   │  72   │ ↑ +4 │ $342     │ 6        │ Acme Corp   │ │
│  │ Mobile Client      │  68   │ → 0  │ $890     │ 10       │ Acme Corp   │ │
│  │ API Gateway        │  64   │ ↓ -2 │ $310     │ 5        │ StartupX    │ │
│  └────────────────────┴───────┴──────┴──────────┴──────────┴─────────────┘ │
│                                                                             │
│  ⚠ Mobile Client: highest cost ($890), below-avg score (68).               │
│    10 developers × $89/dev/mo — but Infra Automation gets 81 with          │
│    4 devs × $105/dev/mo. Mobile team may need prompt coaching.             │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  By Team (People Groups)                                                    │
│  ┌────────────────┬───────┬──────┬──────────┬──────────┬──────────────────┐ │
│  │ Team           │ Score │Trend │ Cost/mo  │ Members  │ Top Dimension    │ │
│  ├────────────────┼───────┼──────┼──────────┼──────────┼──────────────────┤ │
│  │ Platform       │  81   │ ↑ +4 │ $520     │ 5        │ Tool Mastery 90 │ │
│  │ Backend        │  76   │ ↑ +2 │ $680     │ 8        │ Cost Effic.  84 │ │
│  │ Data           │  75   │ ↑ +5 │ $410     │ 5        │ Iteration    82 │ │
│  │ Frontend       │  69   │ ↑ +1 │ $820     │ 9        │ Tool Mastery 76 │ │
│  │ Mobile         │  68   │ → 0  │ $630     │ 8        │ Cost Aware   72 │ │
│  │ QA/Automation  │  66   │ ↑ +8 │ $170     │ 3        │ Prompt Qlty  71 │ │
│  └────────────────┴───────┴──────┴──────────┴──────────┴──────────────────┘ │
│                                                                             │
│  Highlight: QA/Automation improved 8 points — fastest improving team.       │
│  They started using structured prompts with test specifications.            │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  By AI Tool                                                                 │
│  ┌──────────────┬──────────┬──────┬──────────┬──────────┬────────────────┐ │
│  │ Provider     │ Avg Score│ Devs │ Cost/mo  │ Cost/Dev │ Best Dimension │ │
│  ├──────────────┼──────────┼──────┼──────────┼──────────┼────────────────┤ │
│  │ Claude Code  │  73      │ 32   │ $3,200   │ $100     │ Tool Mastery   │ │
│  │ Cursor       │  68      │ 8    │ $720     │ $90      │ Cost Effic.    │ │
│  │ Copilot      │  65      │ 6    │ $310     │ $52      │ Session Disc.  │ │
│  └──────────────┴──────────┴──────┴──────────┴──────────┴────────────────┘ │
│                                                                             │
│  Note: Scores are not directly comparable across providers.                │
│  Claude Code scored on 7/7 dimensions, Cursor 6/7, Copilot 5/7.           │
│  Cost/dev for Copilot is lower because it's subscription-based.            │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Org Trend (Quarterly)                                                      │
│                                                                             │
│  Score                         Cost/Dev                                     │
│  80 ┤            ╭── 71        $150 ┤                                       │
│  70 ┤      ╭────╯              $125 ┤╲                                      │
│  60 ┤─────╯                    $100 ┤ ╲───────── $101                       │
│  50 ┤ 55                       $75  ┤                                       │
│     └──────────────             $50  └──────────────                         │
│      Q3    Q4    Q1              Q3    Q4    Q1                             │
│                                                                             │
│  Reading: Score up 16 points over 2 quarters while cost/dev dropped.       │
│  AI effectiveness is improving. The investment is working.                  │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Org-Level Recommendations                                                  │
│                                                                             │
│  1. SCALE WHAT WORKS: Platform team scores 81. Their practices:            │
│     structured CLAUDE.md files, session limits, Read→Edit workflow.         │
│     Roll this out as an org-wide guide.                                    │
│                                                                             │
│  2. COACHING TARGET: Mobile team (68) and Frontend team (69) are           │
│     15+ points below Platform. Both have low prompt quality scores.        │
│     A 2-hour prompt engineering workshop could close this gap.             │
│                                                                             │
│  3. COST OPTIMISATION: Org-wide Opus usage is 18%. Analysis shows          │
│     only 6% of Opus sessions used features that require Opus.              │
│     Switching the rest to Sonnet would save ~$380/month.                   │
│                                                                             │
│  4. TOOL EVALUATION: 6 developers use Copilot (avg score 65).             │
│     Consider whether the lower cost ($52/dev) justifies the lower          │
│     effectiveness vs Claude Code ($100/dev, score 73).                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Weekly Email Digest (to VP inbox)

```
Subject: Clue Weekly — AI Effectiveness Report (Mar 17-24)

Org Score: 71/100 B  ↑ +1 from last week

Key Changes:
  ↑ QA/Automation team +3 points (66 → 69) — structured prompts paying off
  ↓ API Gateway project -2 points (66 → 64) — 2 new developers ramping up
  → Mobile Client flat at 68 — no improvement for 3 weeks, coaching recommended

Cost: $1,058 this week ($42 avg/developer)
  Highest: Mobile Client $223 (10 devs)
  Lowest:  QA/Automation $42 (3 devs)
  Best efficiency: Infra Automation $105/dev, score 81

Action Items:
  • Mobile Client has been flat for 3 weeks — schedule team coaching session
  • 4 developers have never scored above 60 — consider 1:1 coaching
  • Org-wide Opus usage could be reduced by ~$380/month

View full dashboard: https://clue.company.com/org
```

---

## 5. Admin Experience

### 5.1 Setup Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Clue Team Admin                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Organisation: Your Company                                                 │
│  Plan: Self-Hosted  |  42 developers  |  5 teams  |  6 projects            │
│                                                                             │
│  ┌─ Quick Health ────────────────────────────────────────────────────────┐  │
│  │ Developers pushing data: 38 / 42  (4 inactive > 7 days)             │  │
│  │ Last push: 2 minutes ago                                             │  │
│  │ Data coverage: 127 days                                              │  │
│  │ Providers: Claude Code (32), Cursor (8), Copilot (6)                │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Tabs: [Users] [Teams] [Projects] [API Keys] [Settings]                    │
│                                                                             │
│  ── Users ──────────────────────────────────────────────────────────────   │
│  ┌───────────────────┬──────────┬───────────────┬──────────┬────────────┐  │
│  │ Email             │ Team     │ Projects      │ Last Push│ Status     │  │
│  ├───────────────────┼──────────┼───────────────┼──────────┼────────────┤  │
│  │ sarah@company.com │ Backend  │ WebApp, API GW│ 2m ago   │ Active     │  │
│  │ amir@company.com  │ Backend  │ WebApp        │ 1h ago   │ Active     │  │
│  │ kai@company.com   │ Backend  │ API GW        │ 3h ago   │ Active     │  │
│  │ new@company.com   │ —        │ —             │ Never    │ Invited    │  │
│  └───────────────────┴──────────┴───────────────┴──────────┴────────────┘  │
│                                                                             │
│  [+ Invite Developer]  [Bulk Import CSV]  [Regenerate API Key]             │
│                                                                             │
│  ── Projects ───────────────────────────────────────────────────────────   │
│  ┌──────────────────┬────────────┬─────────────────────────┬────────────┐  │
│  │ Project          │ Client     │ Git Remotes             │ Auto-Detect│  │
│  ├──────────────────┼────────────┼─────────────────────────┼────────────┤  │
│  │ Web App Redesign │ Acme Corp  │ github.com/org/web-app  │ 6 devs     │  │
│  │ API Gateway      │ StartupX   │ github.com/org/api-gw   │ 5 devs     │  │
│  │ (Unassigned)     │ —          │ github.com/org/scripts  │ 2 devs     │  │
│  └──────────────────┴────────────┴─────────────────────────┴────────────┘  │
│                                                                             │
│  ⚠ 1 unassigned git remote. Assign it to a project or ignore.             │
│                                                                             │
│  ── Settings ───────────────────────────────────────────────────────────   │
│  │ Anonymise developers in project view:  [On] / Off                    │  │
│  │ Show developer names to:  Project Leads / Managers / VPs / All       │  │
│  │ Auto-detect project membership:  [On] / Off                          │  │
│  │ Weekly digest email:  [On] / Off → Recipients: [VP list]             │  │
│  │ Score drop alert threshold:  [-5 points]                             │  │
│  │ Inactive developer alert:  [7 days]                                  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. What Happens Behind the Scenes

### Every Claude Code Session (automatic, invisible to developer)

```
10:00  Developer starts Claude Code session on web-app project
10:45  Developer ends session (45 minutes, 23 prompts, 8 tool calls)

10:45  Claude Code PostStop hook fires
10:45  → clue extract --incremental
         Reads new JSONL entries from ~/.claude/
         Deduplicates by message.id:requestId (last entry wins)
         Attributes tokens to correct model
         Stores in local SQLite
         Duration: ~200ms

10:45  → clue push
         Runs export --scrub on today's data
         Computes efficiency score locally
         Strips prompt text, file paths, branch names
         Derives project from git remote URL
         POSTs 4KB JSON to team server
         Duration: ~500ms

10:46  Server receives push
         Validates API key → resolves user_id
         Matches project_hint to project_id
         Upserts into daily_metrics (user, project, date, provider)
         Duration: ~50ms

10:46  Done. Developer didn't notice anything.
```

### Every 15 Minutes (server background job)

```
xx:00  Refresh materialised views
         project_weekly_rollup
         team_weekly_rollup
         org_monthly_rollup
         user_project_trend
       Duration: ~2 seconds for 50-developer org
```

### Every Monday 8am (scheduled)

```
08:00  Generate weekly digest email
         For each manager: their team's changes, coaching recommendations
         For VP: org overview, project comparisons, cost trends
         Send via configured email provider
```
