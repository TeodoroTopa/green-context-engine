"""Tests for the pipeline orchestrator."""

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
        return msg

    # Claude calls: strategist, analysis, draft, quality_gate
    mock_client.messages.create.side_effect = [
        make_response('{"fetches": [{"source": "ember", "entity": "World", "role": "primary"}], "reasoning": "test"}'),
        make_response('{"summary": "Solar growing.", "angles": ["Growth"]}'),
        make_response("---\ntitle: Test\nstatus: draft\n---\n\nTest content."),
        make_response('{"pass": true, "violations": [], "summary": "Clean."}'),
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
