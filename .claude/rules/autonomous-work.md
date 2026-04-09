# Autonomous Work Rules

These rules apply whenever Claude is working autonomously — scheduled tasks,
CodeMachine workflows, or any unattended session. Edit this file to adjust
the boundaries.

## Branch Discipline

- NEVER commit to or push to main. Always work on a dev or feature branch.
- Branch naming: `dev/{feature-area}` for local work, `claude/{task-name}`
  for scheduled cloud tasks.
- Open a PR when work is complete. Do not merge PRs without human review.
- Never force push or rebase shared branches.

## Self-Contained Work Only

- Do NOT start work that requires a human to provide an API key, password,
  or any credential before it can be completed.
- Only integrate data sources that are free and require NO API key (like
  Open-Meteo, UK Carbon Intensity) or that already have a key configured
  in the environment.
- If a promising source requires an API key you don't have, document it
  in docs/research/ and move on. Do not build a half-finished connector.
- Do not modify .env, .env.example, or any secrets/credentials files.

## Quality Gates

- Run `pytest tests/` after every code change. All tests must pass before
  committing.
- New code must include tests.
- Commit at every working checkpoint with descriptive commit messages.
- Run the catalog loader after any YAML changes:
  `python -c "from pipeline.analysis.catalog import load_catalog; load_catalog()"`

## Research Reports

- Document all research findings in `docs/research/` as markdown files.
- Include source URLs, API documentation links, and your assessment.
- Name files descriptively: `data-sources-YYYY-MM-DD.md`,
  `news-feeds-YYYY-MM-DD.md`, etc.

## What NOT to Do Autonomously

- Do not modify production prompts (drafter, editor, strategist prompts)
  without human review.
- Do not delete existing data sources, feeds, or configuration.
- Do not change config/publishing.yaml or Notion database settings.
- Do not publish drafts or approve content.
- Do not modify this rules file.

## Data Source Integration Checklist

When adding a new data source, complete ALL of these steps:

1. Connector in `pipeline/sources/` extending `BaseSource`
2. YAML catalog in `config/data_catalog/`
3. Tests in `tests/`
4. Register in `pipeline/orchestrator.py`
5. Add to `DATA_SOURCE_URLS` and `DATA_SOURCE_NAMES` in
   `pipeline/generation/prompts/energy_brief.py`
6. Add to `DATA_SOURCES` in `pipeline/publishing/notion.py`
7. Add formatting to `pipeline/analysis/enricher.py`
8. Update `config/sources.yaml`
9. Run full test suite to verify
