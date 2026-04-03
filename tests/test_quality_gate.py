"""Tests for the automated quality gate."""

from unittest.mock import MagicMock

from pipeline.generation.quality_gate import run_quality_gate


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_quality_gate_pass(tmp_path):
    """Quality gate returns pass=True when draft is clean."""
    draft = tmp_path / "test-draft.md"
    draft.write_text('---\ntitle: "Test"\n---\n\n## The Hook\n\nGood content.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"pass": true, "violations": [], "summary": "Clean draft, no violations."}'
    )

    result = run_quality_gate(client, "claude-sonnet-4-6", draft)

    assert result["pass"] is True
    assert result["violations"] == []


def test_quality_gate_fail_with_violations(tmp_path):
    """Quality gate returns pass=False with violation details."""
    draft = tmp_path / "test-draft.md"
    draft.write_text('---\ntitle: "Test"\n---\n\n## The Hook\n\nSolar grew 20%.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"pass": false, "violations": [{"category": "Source Grounding", '
        '"text": "Solar grew 20%", "issue": "No source cited"}], '
        '"summary": "Missing source attribution."}'
    )

    result = run_quality_gate(client, "claude-sonnet-4-6", draft)

    assert result["pass"] is False
    assert len(result["violations"]) == 1
    assert result["violations"][0]["category"] == "Source Grounding"


def test_quality_gate_handles_bad_json(tmp_path):
    """Quality gate returns fail on malformed Claude response."""
    draft = tmp_path / "test-draft.md"
    draft.write_text('---\ntitle: "Test"\n---\n\nContent.')

    client = MagicMock()
    client.messages.create.return_value = _mock_response("not json at all")

    result = run_quality_gate(client, "claude-sonnet-4-6", draft)

    assert result["pass"] is False
