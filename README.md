# Energy Context Engine

An automated AI pipeline that monitors renewable energy and climate news, enriches stories with public data, drafts data-grounded "energy intelligence briefs," and publishes the ones a human approves.

## See it live

Published briefs are live at **[www.teodorotopa.com/energy](https://www.teodorotopa.com/energy)**.

## What it does

On selected days each week, the pipeline scans a curated set of energy/climate news feeds, picks the stories best supported by available public data, pulls in relevant numbers from sources like Ember, EIA, GFW, NOAA, and Open-Meteo, and has Claude draft and fact-check a short brief grounded in that data — for less than $0.25 a run. Nothing publishes automatically — every brief sits in a Notion queue until a human reviews it. Only after that manual approval does it get pushed to the live site.

## How it works

```
RSS feeds → Monitor (keyword filter, dedup)
         → Article Selector (AI picks stories best served by available data)
         → Article Fetcher (full article text)
         → Data Strategist (AI picks which data sources/entities to fetch)
         → Enricher (parallel fetch from Ember, EIA, GFW, NOAA, NLR, Open-Meteo, UK Carbon Intensity)
         → Drafter (writes the brief)
         → Editor (fact-checks, fixes issues directly)
         → Verification (final read-only check)
         → Notion "Review" → human approval → GitHub → Vercel → live
```

Each story goes through a small pipeline of specialized AI agents (selector, strategist, drafter, editor, verifier) rather than one big prompt — each step has a narrow job and only the context it needs.

## Fully automated via GitHub Actions

The entire operation runs unattended in the cloud — no local machine required. Two scheduled workflows drive everything, firing only on selected days that the owner picks — **currently Monday and Thursday**:

- **[`generate.yml`](.github/workflows/generate.yml)** runs at 11:00 UTC on scheduled days. It discovers new stories, enriches them with data, and drafts + edits briefs via Claude (using the Message Batches API for cost savings). Finished drafts land in Notion with status `Review`. A per-run budget guard (default $0.50) would abort the run before any over-cap spend, though a typical run costs well under $0.25.
- **[`publish-learn.yml`](.github/workflows/publish-learn.yml)** runs at 23:00 UTC on scheduled days. It publishes anything a human has approved in Notion out to the live website (via the GitHub API, which triggers a Vercel rebuild), and separately reads feedback left on any rejected drafts to learn writing rules for next time — committing those learned rules back into the repo so the next scheduled run's drafts improve.

Together the two workflows form a closed loop: generate → wait for human review → publish approved work → learn from rejected work → generate again, better, next time. The schedule is just two cron lines in the workflow files, so which days it runs is easy to change.

## Human review in Notion

Every draft is a page in a Notion database — the editorial queue — with a `Status` field that tracks it through `Review → Approved` / `Rejected → Published`. A person reads each brief and either approves it (it publishes on the next run) or rejects it with feedback explaining why. Nothing reaches the website without that manual approval step. Rejection notes aren't just discarded — they're fed back into the drafting prompts so the pipeline's writing improves over time.

## Data sources

| Source | What it provides | Scope |
|--------|-------------------|-------|
| **Ember** | Electricity generation by fuel type, carbon intensity | ~200 countries + EU/OECD/ASEAN |
| **EIA** | US electricity generation by fuel type, % breakdown | US national + 50 states |
| **GFW** | Tree cover loss, deforestation drivers, forest carbon emissions | Global, country-level |
| **NOAA** | Yearly/monthly temperature, precipitation, heating/cooling degree days | 180+ countries, US states |
| **IUCN** | Threatened species counts by threat category | Global — not yet active (API key not configured) |
| **NLR** | Solar resource (GHI/DNI) and PVWatts production estimates | US national + 50 states |
| **Open-Meteo** | Historical solar radiation, wind speed, temperature, precipitation | Global |
| **UK Carbon Intensity** | Real-time carbon intensity and generation mix, 30-min resolution | Great Britain |

## Tech stack

Python, the Anthropic SDK (Claude, via the Message Batches API for cost-efficient drafting/editing), `feedparser` for RSS, and `trafilatura` for full-article text extraction.

## Local development

For setup, CLI commands, environment variables, and the full architecture reference, see [`CLAUDE.md`](CLAUDE.md).
