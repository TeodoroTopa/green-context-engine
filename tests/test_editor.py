"""Tests for the editor agent (fact-checking)."""

from unittest.mock import MagicMock

from pipeline.generation.editor import check_draft


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_editor_pass(tmp_path):
    """Editor returns pass when draft is factually accurate."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nAccurate content.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"pass": true, "errors": [], "summary": "All claims verified."}'
    )

    result = check_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="Some data",
    )
    assert result["pass"] is True
    assert result["errors"] == []


def test_editor_catches_critical_error(tmp_path):
    """Editor flags claims not in source data."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nSnapping a multi-year decline.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"pass": false, "errors": [{"severity": "critical", '
        '"claim": "snapping a multi-year decline", '
        '"issue": "Story says decline was 2017-2021 then increases", '
        '"fix": "following moderate increases after a 2017-2021 decline"}], '
        '"summary": "One critical factual distortion."}'
    )

    result = check_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Decline 2017-2021, then increases",
        story_source="Mongabay", data_text="Some data",
    )
    assert result["pass"] is False
    assert len(result["errors"]) == 1
    assert result["errors"][0]["severity"] == "critical"


def test_editor_prose_fallback_fail(tmp_path):
    """Editor parses prose FAIL response in dev mode."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nContent.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        "## Editor Review\n\n### Score: NEEDS REVISION\n\n"
        "### Summary\nTemporal mismatch: data from 2024 used without qualifier."
    )

    result = check_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="Data from 2024",
    )
    assert result["pass"] is False
    assert "Temporal" in result["summary"]


def test_editor_receives_source_data(tmp_path):
    """Editor prompt includes both the draft and source material."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nDraft text.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"pass": true, "errors": [], "summary": "Clean."}'
    )

    check_draft(
        client, "test-model", draft,
        story_title="Indonesia deforestation",
        story_summary="66% surge in 2025",
        story_source="Mongabay",
        data_text="Indonesia: 680 gCO2/kWh (2024)",
    )

    # Verify the prompt contains both source material and draft
    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Indonesia deforestation" in prompt
    assert "66% surge" in prompt
    assert "680 gCO2/kWh" in prompt
    assert "Draft text" in prompt
