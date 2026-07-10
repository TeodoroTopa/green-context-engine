"""Tests for the batched morning orchestrator (run_batched)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pipeline.monitors.rss_monitor import Story


def _msg(text, in_tok=100, out_tok=50):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


def _batch_result(cid, text):
    return SimpleNamespace(
        custom_id=cid,
        result=SimpleNamespace(type="succeeded", message=_msg(text)),
    )


DRAFT_MD = "---\ntitle: Solar Test\ndate: 2026-04-01\nstatus: draft\n---\n\nSolar generation rose."


@patch("pipeline.orchestrator.NotionPublisher", side_effect=ValueError("no token"))
@patch("pipeline.orchestrator.Anthropic")
@patch("pipeline.orchestrator.EmberSource")
@patch("pipeline.orchestrator.EIASource")
@patch("pipeline.orchestrator.RSSMonitor")
@patch("pipeline.orchestrator.yaml.safe_load")
@patch("pipeline.orchestrator.load_dotenv")
@patch.dict("os.environ", {"EMBER_API_KEY": "fake", "EIA_API_KEY": "fake"}, clear=False)
def test_run_batched_produces_passing_draft(
    mock_dotenv, mock_yaml, mock_monitor_cls, mock_eia_cls, mock_ember_cls,
    mock_anthropic_cls, mock_notion_cls, tmp_path,
):
    story = Story(
        title="Solar Test",
        url="https://example.com/solar",
        summary="A story about solar.",
        published="2026-04-01",
        source="pvmagazine",
        feed_name="test",
        full_text="Full article about solar generation.",
    )
    mock_monitor = MagicMock()
    mock_monitor.check_feeds.return_value = [story]
    mock_monitor_cls.return_value = mock_monitor
    mock_yaml.return_value = {"feeds": [{"name": "t", "url": "http://x", "source": "pvmagazine"}]}

    mock_ember = MagicMock()
    mock_ember.get_generation_context.return_value = {
        "entity": "World",
        "source": "ember",
        "generation": [{"series": "Solar", "generation_twh": 100, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 400, "date": "2025"}],
    }
    mock_ember_cls.return_value = mock_ember

    mock_eia = MagicMock()
    mock_eia.get_generation_context.return_value = {
        "entity": "World",
        "source": "eia",
        "generation": [{"period": "2025", "fuel_type": "SUN", "fuel_description": "Solar", "value": 500}],
    }
    mock_eia_cls.return_value = mock_eia

    client = MagicMock()
    # Sync calls in the passing path: strategist only (1 story <= max, editor passes).
    client.messages.create.side_effect = [
        _msg(
            '{"fetches": ['
            '{"source": "ember", "entity": "World", "role": "primary"}, '
            '{"source": "eia", "entity": "World", "role": "primary"}'
            '], "reasoning": "t"}'
        ),
    ]
    # Two batches: draft, then editor. BatchClient calls create/retrieve/results per batch.
    client.messages.batches.create.return_value = SimpleNamespace(id="batch_1")
    client.messages.batches.retrieve.return_value = SimpleNamespace(processing_status="ended")
    client.messages.batches.results.side_effect = [
        iter([_batch_result("s0", DRAFT_MD)]),
        iter([_batch_result("s0", '{"verdict": "pass", "summary": "ok"}')]),
    ]
    mock_anthropic_cls.return_value = client

    import pipeline.generation.drafter as drafter_mod
    original_dir = drafter_mod.DRAFTS_DIR
    drafter_mod.DRAFTS_DIR = tmp_path
    try:
        from pipeline.orchestrator import Pipeline
        pipe = Pipeline()
        assert pipe.notion is None  # NotionPublisher raised → disabled
        drafts = pipe.run_batched(source="pvmagazine", max_stories=5)

        assert len(drafts) == 1
        assert drafts[0].exists()
        # draft + editor batches each submitted once
        assert client.messages.batches.create.call_count == 2
        # each batch request carried the mixed model tier
        draft_call = client.messages.batches.create.call_args_list[0].kwargs["requests"][0]
        assert draft_call["params"]["model"] == "claude-sonnet-5"
    finally:
        drafter_mod.DRAFTS_DIR = original_dir


@patch("pipeline.orchestrator.NotionPublisher", side_effect=ValueError("no token"))
@patch("pipeline.orchestrator.Anthropic")
@patch("pipeline.orchestrator.EmberSource")
@patch("pipeline.orchestrator.EIASource")
@patch("pipeline.orchestrator.RSSMonitor")
@patch("pipeline.orchestrator.yaml.safe_load")
@patch("pipeline.orchestrator.load_dotenv")
@patch.dict("os.environ", {"EMBER_API_KEY": "fake", "EIA_API_KEY": "fake"}, clear=False)
def test_run_batched_skips_single_provider_story(
    mock_dotenv, mock_yaml, mock_monitor_cls, mock_eia_cls, mock_ember_cls,
    mock_anthropic_cls, mock_notion_cls, tmp_path,
):
    """A story enriched from only 1 data provider is skipped, not drafted."""
    story = Story(
        title="Single Source Test",
        url="https://example.com/singlesource",
        summary="A story with only one data provider.",
        published="2026-04-01",
        source="pvmagazine",
        feed_name="test",
        full_text="Full article text.",
    )
    mock_monitor = MagicMock()
    mock_monitor.check_feeds.return_value = [story]
    mock_monitor_cls.return_value = mock_monitor
    mock_yaml.return_value = {"feeds": [{"name": "t", "url": "http://x", "source": "pvmagazine"}]}

    mock_ember = MagicMock()
    mock_ember.get_generation_context.return_value = {
        "entity": "World",
        "source": "ember",
        "generation": [{"series": "Solar", "generation_twh": 100, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 400, "date": "2025"}],
    }
    mock_ember_cls.return_value = mock_ember

    client = MagicMock()
    # Strategist plan only fetches from ember — a single provider.
    client.messages.create.side_effect = [
        _msg('{"fetches": [{"source": "ember", "entity": "World", "role": "primary"}], "reasoning": "t"}'),
    ]
    mock_anthropic_cls.return_value = client

    import pipeline.generation.drafter as drafter_mod
    original_dir = drafter_mod.DRAFTS_DIR
    drafter_mod.DRAFTS_DIR = tmp_path
    try:
        from pipeline.orchestrator import Pipeline
        pipe = Pipeline()
        drafts = pipe.run_batched(source="pvmagazine", max_stories=5)

        # No draft batch should even be submitted — the story never entered
        # the pending pool.
        assert drafts == []
        client.messages.batches.create.assert_not_called()
    finally:
        drafter_mod.DRAFTS_DIR = original_dir


@patch("pipeline.orchestrator.NotionPublisher", side_effect=ValueError("no token"))
@patch("pipeline.orchestrator.Anthropic")
@patch("pipeline.orchestrator.EmberSource")
@patch("pipeline.orchestrator.EIASource")
@patch("pipeline.orchestrator.RSSMonitor")
@patch("pipeline.orchestrator.yaml.safe_load")
@patch("pipeline.orchestrator.load_dotenv")
@patch.dict(
    "os.environ",
    {"EMBER_API_KEY": "fake", "EIA_API_KEY": "fake", "PIPELINE_DAILY_BUDGET_USD": "0.0000001"},
    clear=False,
)
def test_run_batched_budget_guard_aborts_before_spend(
    mock_dotenv, mock_yaml, mock_monitor_cls, mock_eia_cls, mock_ember_cls,
    mock_anthropic_cls, mock_notion_cls, tmp_path,
):
    story = Story(
        title="Budget Test", url="https://example.com/b", summary="s",
        published="2026-04-01", source="pvmagazine", feed_name="t",
        full_text="text",
    )
    mock_monitor = MagicMock()
    mock_monitor.check_feeds.return_value = [story]
    mock_monitor_cls.return_value = mock_monitor
    mock_yaml.return_value = {"feeds": [{"name": "t", "url": "http://x", "source": "pvmagazine"}]}

    mock_ember = MagicMock()
    mock_ember.get_generation_context.return_value = {
        "entity": "World",
        "generation": [{"series": "Solar", "generation_twh": 100, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 400, "date": "2025"}],
    }
    mock_ember_cls.return_value = mock_ember

    client = MagicMock()
    client.messages.create.side_effect = [
        _msg('{"fetches": [{"source": "ember", "entity": "World", "role": "primary"}], "reasoning": "t"}'),
    ]
    mock_anthropic_cls.return_value = client

    import pipeline.generation.drafter as drafter_mod
    original_dir = drafter_mod.DRAFTS_DIR
    drafter_mod.DRAFTS_DIR = tmp_path
    try:
        from pipeline.orchestrator import Pipeline
        pipe = Pipeline()
        drafts = pipe.run_batched(source="pvmagazine", max_stories=5)
        # Guard trips before the draft batch is ever submitted.
        assert drafts == []
        client.messages.batches.create.assert_not_called()
    finally:
        drafter_mod.DRAFTS_DIR = original_dir
