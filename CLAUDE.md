# Energy Context Engine

Automated pipeline: monitors energy/climate news → selects stories that match available data → fetches full articles → enriches with data from multiple APIs → AI drafts data-grounded briefs → AI editor fact-checks and fixes → human approves in Notion → publishes to teodorotopa.com.

## Architecture

```
RSS feeds → Monitor (keyword filter, Notion-based dedup)
         → Article Selector (AI picks stories best served by available data)
         → Article Fetcher (trafilatura extracts full text from article URL)
         → Data Strategist (AI picks sources/entities/data_types to fetch)
         → Enricher (parallel fetch from Ember, EIA, GFW, NOAA, NLR, Open-Meteo, UK Carbon Intensity)
         → Drafter (200-250 word brief with bold lead-in structure)
         → Editor (pass / fix / fail — fixes issues directly when possible)
         → Verification (read-only check after editor fixes)
         → Notion "Review" → human approval → GitHub API → Vercel → live
```

## Key Directories

- `pipeline/monitors/` — RSS monitor (keyword filter, Notion-based dedup)
- `pipeline/sources/` — data connectors (BaseSource interface, `**kwargs` for selective `data_types`)
- `pipeline/analysis/` — article selector, data strategist, enricher, catalog loader
- `pipeline/content/` — article text fetcher (trafilatura)
- `pipeline/generation/` — drafter, editor (pass/fix/fail + verification), voice checker, prompts
- `pipeline/publishing/` — Notion API (with feedback reader), GitHub publishing
- `config/data_catalog/` — YAML catalogs (strategist reads these to decide what to fetch)
- `config/feedback_rules.yaml` — learned writing rules from rejected drafts (loaded into drafter prompt)

## Data Sources

| Source | What it provides | Scope |
|--------|-----------------|-------|
| **Ember** | Electricity generation by fuel type, carbon intensity | ~200 countries + EU/OECD/ASEAN |
| **EIA** | US electricity generation by fuel type with % breakdown | US national + 50 states |
| **GFW** | Tree cover loss, deforestation drivers, forest carbon emissions | Global, country-level |
| **NOAA** | Yearly/monthly temp, precip, heating/cooling degree days | 180+ countries, US states |
| **IUCN** | Threatened species counts by threat category | Global — not yet active (API key not configured) |
| **NLR** | Solar resource (GHI/DNI) and PVWatts production estimates | US national + 50 states |
| **Open-Meteo** | Historical solar radiation, wind speed, temperature, precipitation (no key required) | Global, capital-city proxy |
| **UK Carbon Intensity** | Real-time carbon intensity and generation mix at 30-min resolution (no key required) | Great Britain only |

### Adding a New Source

1. YAML in `config/data_catalog/` — entities + data_types (strategist auto-discovers)
2. Connector in `pipeline/sources/` extending `BaseSource` (must accept `**kwargs`)
3. Register in `pipeline/orchestrator.py`

## News Sources

Mongabay (3 feeds), Carbon Brief, PV Magazine, CleanTechnica, Electrek. Full article text fetched via trafilatura for all except Carbon Brief (RSS already has full text).

## Agent Pipeline

All agents go through the `claude` CLI proxy (`pipeline/claude_code_client.py`), which invokes `claude -p --model <model> --effort <level>`. Set via env vars (required, no defaults — `ClaudeCodeClient.__init__` raises if any are missing or invalid): `PIPELINE_CLAUDE_MODEL`, `PIPELINE_CLAUDE_EFFORT` (`low|medium|high|xhigh|max`), `PIPELINE_CLAUDE_TIMEOUT` (positive integer seconds). The `model=` kwarg passed by call sites is ignored — the CLI flag is authoritative. The proxy also passes `--strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources user` to skip MCP server initialization and project hooks (notably the pytest Stop hook in `.claude/settings.local.json`); subscription auth still works because keychain reads are not disabled. Per story:

| Agent | Role | Calls |
|-------|------|-------|
| **Article Selector** | Picks best story from RSS candidates based on data fit | 1 (per source batch) |
| **Data Strategist** | Picks which APIs/entities/data_types to fetch | 1 |
| **Drafter** | Writes 200-250 word brief with bold lead-ins | 1-2 |
| **Editor** | Fact-checks, returns pass/fix/fail. Fixes issues directly. | 1-2 |
| **Verification** | Read-only check after editor fixes (pass/fail only) | 0-1 |

Editor allows editorial characterizations (e.g., "nearly double" for 1.83x) but catches fabricated data. Total: 3-5 calls per story.

## Scheduled Workflow — autonomous (GitHub Actions, API mode)

Runs unattended in the cloud; no PC required. Two independent scheduled
workflows, each a single fixed UTC cron (no gating job, no TZ conversion),
firing only on a **selected day — currently Monday** (owner-configurable;
not a daily job):

- `.github/workflows/generate.yml` — cron `"0 11 * * 1"` (11:00 UTC, Mon).
- `.github/workflows/publish-learn.yml` — cron `"0 23 * * 1"` (23:00 UTC, Mon).

These land at **7am/7pm during Eastern Daylight Time** (Mar–Nov) and
**6am/6pm during Eastern Standard Time** (Nov–Mar) — always on the hour ET,
just an hour earlier in winter (GitHub Actions cron has no DST awareness;
this drift is an accepted trade-off for a simple, gate-free schedule). To
change which day(s) it runs or reschedule the time, edit the single cron
line in the relevant file (day-of-week field: 0=Sun ... 6=Sat). Manual runs:
Actions tab → pick the workflow → "Run workflow".

**`generate.yml`** → `scripts/run_pipeline_batched.py`:
`Pipeline.run_batched()` discovers/enriches stories, then drafts and edits via
the **Message Batches API** (50% off) for the two Sonnet stages. Drafts land in
Notion as "Review". A `BudgetGuard` (env `PIPELINE_DAILY_BUDGET_USD`, default
`$0.50`) aborts before any over-cap batch — this is a per-run safety ceiling,
not the typical cost (see below).

**`publish-learn.yml`**:
1. `publish_approved.py` — publishes approved drafts to the website via GitHub API → Vercel.
2. `process_feedback.py` — learns writing rules from rejections into `config/feedback_rules.yaml`.
3. Commits the updated `feedback_rules.yaml` back to this repo so the next scheduled `generate.yml` run uses it (ephemeral runners don't persist local state; Notion is the source of truth for everything else).

**Cost control:** per-stage model tiering in `config/models.yaml` (Haiku for
selector/strategist/verifier, Sonnet for drafter/editor) + Batch (50%) keeps
typical runs **under $0.25** — well below the $0.50 abort ceiling.
`pipeline/usage.py` prices per model; the Sonnet stages go through Batch, the
Haiku stages run synchronously. Running only weekly instead of daily further
cuts total spend; note `--max-stories 5` per run means more than 5 relevant
stories accumulating over the week will roll over rather than all being
processed in one run.

**Local / legacy:** the Windows `.bat` files + `PIPELINE_MODE=local` CLI proxy
still work for free local dev (subscription auth, no API billing, no Batch).
`scripts/run_pipeline.py` is the synchronous (non-batched) runner.

The drafter loads `feedback_rules.yaml` at runtime, so the pipeline learns from rejections over time.

## Notion Editorial Queue

Database: Notion Plus account. Statuses: Review → Approved/Rejected → Published.

| Property | Type | Purpose |
|----------|------|---------|
| Story Title | title | Article headline |
| Status | select | Review, Approved, Rejected, Published |
| Source | select | News source (Mongabay, etc.) |
| Date Found | date | Article publication date |
| Topics | multi_select | Matched keywords (solar, wind, coal, etc.) |
| URL | url | Original article link |
| Feedback | rich text | Rejection notes (drives prompt improvement) |

## Commands

```bash
# Generate drafts (one per source)
PIPELINE_MODE=local python scripts/run_pipeline.py --source mongabay --max-stories 1

# Standalone research (no Notion/publishing)
python scripts/research_story.py --url "..." --title "..." --summary "..."

# Publish approved drafts
python scripts/publish_approved.py

# Process rejection feedback into writing rules
python scripts/process_feedback.py

# Tests
pytest tests/
```

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `EMBER_API_KEY` | yes | Ember electricity data |
| `EIA_API_KEY` | yes | EIA US electricity data |
| `GFW_API_KEY` | optional | Global Forest Watch |
| `NOAA_API_KEY` | optional | NOAA climate data |
| `IUCN_API_KEY` | optional | IUCN Red List threatened species data (not yet configured) |
| `NLR_API_KEY` | optional | NLR solar resource / PVWatts data |
| `NOTION_TOKEN` | optional | Editorial queue (Notion Plus) |
| `WEBSITE_GITHUB_TOKEN` | optional | Publish to website repo |
| `ANTHROPIC_API_KEY` | yes (prod/API mode) | Paid API auth for scheduled cloud runs (`PIPELINE_MODE` unset/`prod`) |
| `PIPELINE_DAILY_BUDGET_USD` | optional | Per-run spend cap for the batched run (default `0.50`; typical run costs under $0.25) |
| `PIPELINE_MODE` | optional | `dev`/`local` = claude CLI proxy (free, no API billing); unset/`prod` = paid API |
| `PIPELINE_CLAUDE_MODEL` | yes (when proxy used) | Model for the CLI proxy (alias like `opus`/`sonnet` or full ID like `claude-opus-4-7`) |
| `PIPELINE_CLAUDE_EFFORT` | yes (when proxy used) | Effort level for the CLI proxy (`low`/`medium`/`high`/`xhigh`/`max`) |
| `PIPELINE_CLAUDE_TIMEOUT` | yes (when proxy used) | Subprocess timeout in seconds for each CLI call (positive integer) |

Per-stage models live in `config/models.yaml` (used in API mode; ignored by the CLI proxy).

## Notes for Claude Code

- Teo is a senior data scientist — skip basic explanations
- Simple, readable code > clever abstractions
- Every new module comes with tests
- Commit at every working checkpoint
- Prompts use XML tags and examples-first structure (per Anthropic context engineering guide)
- CLI proxy passes prompts via stdin, strips ANTHROPIC_API_KEY from subprocess env

## Autonomous Work

When working autonomously (scheduled tasks, CodeMachine workflows, unattended sessions), follow the rules in `.claude/rules/autonomous-work.md`. Key points:

- **Never push to main.** Always use dev branches and open PRs.
- **Self-contained only.** Don't start work requiring API keys you don't have.
- **Document research** in `docs/research/` as markdown files.
- **Run tests** after every change — all must pass before committing.
