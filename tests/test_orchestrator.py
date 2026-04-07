"""Tests for the pipeline orchestrator."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from pipeline.monitors.rss_monitor import Story


@patch("pipeline.orchestrator.Anthropic")
@patch("pipeline.orchestrator.EmberSource")
@patch("pipeline.orchestrator.EIASource")
@patch("pipeline.orchestrator.RSSMonitor")
@patch("pipeline.orchestrator.yaml.safe_load")
@patch("pipeline.orchestrator.load_dotenv")
@patch.dict("os.environ", {"EMBER_API_KEY": "fake", "EIA_API_KEY": "fake"})
def test_pipeline_runs_end_to_end(mock_dotenv, mock_yaml, mock_monitor_cls, mock_eia_cls, mock_ember_cls, mock_anthropic_cls, tmp_path):
    """Pipeline wires monitor → enricher → drafter and produces draft files."""
    story = Story(
        title="Test story",
        url="https://example.com/test",
        summary="A test story about energy.",
        published="2026-04-01",
        source="mongabay",
        feed_name="test",
    )
    mock_monitor = MagicMock()
    mock_monitor.check_feeds.return_value = [story]
    mock_monitor_cls.return_value = mock_monitor

    mock_yaml.return_value = {"feeds": [{"name": "test", "url": "http://fake", "source": "mongabay"}]}

    mock_ember = MagicMock()
    mock_ember.get_generation_context.return_value = {
        "entity": "World",
        "generation": [{"series": "Solar", "generation_twh": 100, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 400, "date": "2025"}],
    }
    mock_ember_cls.return_value = mock_ember

    mock_client = MagicMock()
    def make_response(text):
        msg = MagicMock()
        msg.content = [MagicMock(text=text)]
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 50
        return msg

    # Claude calls: strategist, draft, editor (pass verdict)
    mock_client.messages.create.side_effect = [
        make_response('{"fetches": [{"source": "ember", "entity": "World", "role": "primary"}], "reasoning": "test"}'),
        make_response("---\ntitle: Test\nstatus: draft\n---\n\nTest content."),
        make_response('{"verdict": "pass", "summary": "All claims verified."}'),
    ]
    mock_anthropic_cls.return_value = mock_client

    import pipeline.generation.drafter as drafter_mod
    original_dir = drafter_mod.DRAFTS_DIR
    drafter_mod.DRAFTS_DIR = tmp_path

    try:
        from pipeline.orchestrator import Pipeline
        pipeline = Pipeline()
        drafts = pipeline.run(source="mongabay")

        assert len(drafts) == 1
        assert drafts[0].exists()
        assert drafts[0].suffix == ".md"
    finally:
        drafter_mod.DRAFTS_DIR = original_dir


@patch("pipeline.orchestrator.Anthropic")
@patch("pipeline.orchestrator.EmberSource")
@patch("pipeline.orchestrator.EIASource")
@patch("pipeline.orchestrator.load_dotenv")
@patch.dict("os.environ", {"EMBER_API_KEY": "fake", "EIA_API_KEY": "fake"})
def test_research_and_draft_standalone(mock_dotenv, mock_eia_cls, mock_ember_cls, mock_anthropic_cls, tmp_path):
    """research_and_draft() works without Notion or RSS — just Story in, draft out."""
    story = Story(
        title="Manual test story",
        url="https://example.com/manual",
        summary="A manually provided story about coal.",
        published="2026-04-01",
        source="manual",
        feed_name="manual",
    )

    mock_ember = MagicMock()
    mock_ember.get_generation_context.return_value = {
        "entity": "World",
        "generation": [{"series": "Coal", "generation_twh": 9000, "date": "2024"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 471, "date": "2024"}],
    }
    mock_ember_cls.return_value = mock_ember

    mock_client = MagicMock()
    def make_response(text):
        msg = MagicMock()
        msg.content = [MagicMock(text=text)]
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 50
        return msg

    mock_client.messages.create.side_effect = [
        make_response('{"fetches": [{"source": "ember", "entity": "World", "role": "primary"}], "reasoning": "test"}'),
        make_response("---\ntitle: Coal Test\nstatus: draft\n---\n\nCoal content."),
        make_response('{"verdict": "pass", "summary": "OK."}'),
    ]
    mock_anthropic_cls.return_value = mock_client

    import pipeline.generation.drafter as drafter_mod
    original_dir = drafter_mod.DRAFTS_DIR
    drafter_mod.DRAFTS_DIR = tmp_path

    try:
        from pipeline.orchestrator import Pipeline
        pipeline = Pipeline()
        enriched, draft_path, edit_result = pipeline.research_and_draft(story)

        assert draft_path.exists()
        assert edit_result["verdict"] == "pass"
        assert enriched.entities == ["World"]
    finally:
        drafter_mod.DRAFTS_DIR = original_dir


@patch("pipeline.orchestrator.Anthropic")
@patch("pipeline.orchestrator.EmberSource")
@patch("pipeline.orchestrator.EIASource")
@patch("pipeline.orchestrator.load_dotenv")
@patch.dict("os.environ", {"EMBER_API_KEY": "fake", "EIA_API_KEY": "fake"})
def test_research_and_draft_raises_on_no_data(mock_dotenv, mock_eia_cls, mock_ember_cls, mock_anthropic_cls):
    """research_and_draft() raises ValueError when no data is available."""
    story = Story(
        title="No data story",
        url="https://example.com/nodata",
        summary="No relevant data exists.",
        published="2026-04-01",
        source="manual",
        feed_name="manual",
    )

    mock_ember = MagicMock()
    mock_ember.get_generation_context.return_value = {
        "entity": "Atlantis",
        "generation": [],
        "carbon_intensity": [],
    }
    mock_ember_cls.return_value = mock_ember

    mock_client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text='{"fetches": [{"source": "ember", "entity": "Atlantis", "role": "primary"}], "reasoning": "test"}')]
    msg.usage.input_tokens = 100
    msg.usage.output_tokens = 50
    mock_client.messages.create.return_value = msg
    mock_anthropic_cls.return_value = mock_client

    from pipeline.orchestrator import Pipeline
    pipeline = Pipeline()

    with pytest.raises(ValueError, match="No data available"):
        pipeline.research_and_draft(story)
