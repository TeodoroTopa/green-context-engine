"""Tests for the editor agent (fact-checking with pass/fix/fail)."""

from unittest.mock import MagicMock

from pipeline.generation.editor import check_draft, verify_draft


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage.input_tokens = 100
    msg.usage.output_tokens = 50
    return msg


def test_editor_pass(tmp_path):
    """Editor returns pass verdict when draft is clean."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nAccurate content.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"verdict": "pass", "summary": "All claims verified."}'
    )

    result = check_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="Some data",
    )
    assert result["verdict"] == "pass"


def test_editor_fix(tmp_path):
    """Editor returns fix verdict with corrected draft."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nEU emits 210 gCO2/kWh.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"verdict": "fix", '
        '"fixed_draft": "---\\ntitle: \\"Test\\"\\n---\\n\\nThe global average is 471 gCO2/kWh (Ember).", '
        '"changes": ["Replaced unsourced EU figure with sourced global average"], '
        '"summary": "One unsourced claim fixed."}'
    )

    result = check_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="World: 471 gCO2/kWh",
    )
    assert result["verdict"] == "fix"
    assert "fixed_draft" in result
    assert len(result["changes"]) == 1


def test_editor_fail(tmp_path):
    """Editor returns fail verdict for fundamental problems."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nCompletely fabricated content.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"verdict": "fail", '
        '"errors": [{"severity": "critical", "claim": "fabricated", "issue": "not in source", "fix": "rewrite"}], '
        '"summary": "Draft is entirely fabricated."}'
    )

    result = check_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="Some data",
    )
    assert result["verdict"] == "fail"
    assert len(result["errors"]) == 1


def test_editor_legacy_format(tmp_path):
    """Editor handles legacy pass/fail boolean format."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nContent.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"pass": true, "errors": [], "summary": "Clean."}'
    )

    result = check_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="Data",
    )
    assert result["verdict"] == "pass"


def test_editor_prose_fallback_fail(tmp_path):
    """Editor parses prose FAIL response in dev mode."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nContent.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        "## Editor Review\n\n### Score: NEEDS REVISION\n\n"
        "### Summary\nTemporal mismatch."
    )

    result = check_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="Data",
    )
    assert result["verdict"] == "fail"


def test_verify_pass(tmp_path):
    """Verification pass returns pass verdict."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nClean content.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"verdict": "pass", "summary": "All claims verified."}'
    )

    result = verify_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="Data",
    )
    assert result["verdict"] == "pass"


def test_verify_fail(tmp_path):
    """Verification catches issues in editor-fixed draft."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nNew unsourced claim.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"verdict": "fail", "summary": "Editor fix introduced new unsourced claim."}'
    )

    result = verify_draft(
        client, "test-model", draft,
        story_title="Test", story_summary="Summary",
        story_source="Mongabay", data_text="Data",
    )
    assert result["verdict"] == "fail"


def test_editor_receives_source_data(tmp_path):
    """Editor prompt includes source material, article text, and draft."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nDraft text.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"verdict": "pass", "summary": "Clean."}'
    )

    check_draft(
        client, "test-model", draft,
        story_title="Indonesia deforestation",
        story_summary="66% surge in 2025",
        story_source="Mongabay",
        data_text="Indonesia: 680 gCO2/kWh (2024)",
        story_full_text="Full article about Indonesia...",
    )

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Indonesia deforestation" in prompt
    assert "66% surge" in prompt
    assert "680 gCO2/kWh" in prompt
    assert "Full article about Indonesia" in prompt
    assert "Draft text" in prompt
