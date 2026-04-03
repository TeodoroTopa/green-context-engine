"""Tests for the drafter and voice validation."""

from unittest.mock import MagicMock

from pipeline.analysis.enricher import EnrichedStory
from pipeline.generation.drafter import Drafter
from pipeline.generation.voice import check_voice
from pipeline.monitors.rss_monitor import Story

SAMPLE_ENRICHED = EnrichedStory(
    story=Story(
        title="Solar surge in Germany",
        url="https://example.com/solar",
        summary="Germany added record solar capacity.",
        published="2026-03-30",
        source="mongabay",
        feed_name="mongabay_energy",
    ),
    entities=["Germany"],
    ember_data={"Germany": {"generation": [], "carbon_intensity": []}},
    data_summary="Germany's solar grew 20% year over year.",
    suggested_angles=["Record capacity additions"],
)

CLEAN_DRAFT = """\
---
title: "Germany's Solar Surge"
date: 2026-03-30
sources:
  - name: Mongabay
    url: https://example.com/solar
  - name: Ember
    url: https://ember-energy.org
status: draft
---

## The Hook

Germany added 10 GW of solar capacity in 2025.

## The Data Context

Solar now accounts for 15% of Germany's generation mix.
"""


def test_voice_check_catches_violations():
    bad = "This unprecedented shift is truly transformative. In an era of change, it is worth noting."
    violations = check_voice(bad)
    assert any("unprecedented" in v for v in violations)
    assert any("transformative" in v for v in violations)
    assert any("in an era of" in v for v in violations)
    assert any("it is worth noting" in v for v in violations)


def test_voice_check_passes_clean_text():
    assert check_voice(CLEAN_DRAFT) == []


def test_draft_saves_file(tmp_path):
    """draft() calls Claude, saves markdown to content/drafts/."""
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=CLEAN_DRAFT)]
    client.messages.create.return_value = msg

    drafter = Drafter(client)
    # Override DRAFTS_DIR to tmp
    import pipeline.generation.drafter as drafter_mod
    original_dir = drafter_mod.DRAFTS_DIR
    drafter_mod.DRAFTS_DIR = tmp_path

    try:
        path = drafter.draft(SAMPLE_ENRICHED)
        assert path.exists()
        assert path.suffix == ".md"
        assert "solar" in path.stem
        content = path.read_text()
        assert "Germany" in content
    finally:
        drafter_mod.DRAFTS_DIR = original_dir


def test_extract_draft_strips_preamble():
    """_extract_draft removes LLM commentary before the frontmatter."""
    client = MagicMock()
    drafter = Drafter(client)

    raw = (
        'The file has been fixed. Here is the corrected version:\n\n'
        '```markdown\n'
        '---\ntitle: "Test"\nstatus: draft\n---\n\n## The Hook\n\nContent.\n'
        '```'
    )
    result = drafter._extract_draft(raw)
    assert result.startswith("---")
    assert "The file has been fixed" not in result
    assert "```" not in result


def test_extract_draft_passes_clean_text():
    """_extract_draft returns clean drafts unchanged."""
    client = MagicMock()
    drafter = Drafter(client)

    clean = '---\ntitle: "Test"\n---\n\n## The Hook\n\nContent.'
    result = drafter._extract_draft(clean)
    assert result == clean


def test_revise_overwrites_draft(tmp_path):
    """revise() updates the draft file with the corrected version."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nCoal was 63% of generation.')

    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text='---\ntitle: "Test"\n---\n\nCoal was 61% of generation.')]
    client.messages.create.return_value = msg

    drafter = Drafter(client)
    result_path = drafter.revise(
        draft,
        errors=[{"severity": "high", "claim": "63%", "issue": "Should be 61%", "fix": "Change to 61%"}],
        data_text="Coal: 228 TWh out of 372 TWh total",
    )

    assert result_path == draft
    revised = draft.read_text(encoding="utf-8")
    assert "61%" in revised
    assert "63%" not in revised
