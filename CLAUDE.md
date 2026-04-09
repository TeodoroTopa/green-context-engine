# Energy Context Engine

Automated pipeline: monitors energy/climate news → selects stories that match available data → fetches full articles → enriches with data from multiple APIs → AI drafts data-grounded briefs → AI editor fact-checks and fixes → human approves in Notion → publishes to teodorotopa.com.

## Architecture

```
RSS feeds → Monitor (keyword filter, Notion-based dedup)
         → Article Selector (AI picks stories best served by available data)
         → Article Fetcher (trafilatura extracts full text from article URL)
         → Data Strategist (AI picks sources/entities/data_types to fetch)
         → Enricher (parallel fetch from Ember, EIA, GFW, NOAA)
         → Drafter (200-250 word brief with bold lead-in structure)
         → Editor (pass / fix / fail — fixes issues directly when possible)
         → Verification (read-only check after editor fixes)
         → Notion "Review" → human approval → GitHub API → Vercel → live
```

## Key Directories

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

### Adding a New Source

1. YAML in `config/data_catalog/` — entities + data_types (strategist auto-discovers)
2. Connector in `pipeline/sources/` extending `BaseSource` (must accept `**kwargs`)
3. Register in `pipeline/orchestrator.py`

## News Sources

Mongabay (3 feeds), Carbon Brief, PV Magazine, CleanTechnica, Electrek. Full article text fetched via trafilatura for all except Carbon Brief (RSS already has full text).

## Agent Pipeline

All agents use `claude-opus-4-6`. Per story:

| Agent | Role | Calls |
|-------|------|-------|
| **Article Selector** | Picks best story from RSS candidates based on data fit | 1 (per source batch) |
| **Data Strategist** | Picks which APIs/entities/data_types to fetch | 1 |
| **Drafter** | Writes 200-250 word brief with bold lead-ins | 1-2 |
| **Editor** | Fact-checks, returns pass/fix/fail. Fixes issues directly. | 1-2 |
| **Verification** | Read-only check after editor fixes (pass/fail only) | 0-1 |

Editor allows editorial characterizations (e.g., "nearly double" for 1.83x) but catches fabricated data. Total: 3-5 calls per story.

## Daily Workflow (Windows Task Scheduler)

**Morning** — `scripts/generate_drafts.bat`: runs pipeline once per source, generates one draft each. Drafts appear in Notion as "Review".

**Afternoon** — `scripts/publish_and_learn.bat`:
1. Publishes approved drafts to website via GitHub API → Vercel rebuild
2. Reads rejected drafts + feedback from Notion, extracts generalized writing rules via Claude, saves to `config/feedback_rules.yaml`, archives processed rejections

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
| `NOTION_TOKEN` | optional | Editorial queue (Notion Plus) |
| `WEBSITE_GITHUB_TOKEN` | optional | Publish to website repo |
| `PIPELINE_MODE` | optional | `dev`/`local` = claude CLI proxy (no API billing) |

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
