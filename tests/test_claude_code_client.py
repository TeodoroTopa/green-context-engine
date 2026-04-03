"""Tests for the Claude Code client adapter."""

import json
from unittest.mock import patch, MagicMock

from pipeline.claude_code_client import ClaudeCodeClient, _Messages


def test_create_builds_prompt_with_system():
    """create() prepends system prompt and formats messages."""
    msgs = _Messages()

    cli_output = json.dumps({
        "result": "Test response",
        "usage": {"input_tokens": 50, "output_tokens": 10},
    })
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = cli_output

    with patch("pipeline.claude_code_client.subprocess.run", return_value=mock_result) as mock_run:
        response = msgs.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system="You are a test assistant.",
            messages=[{"role": "user", "content": "Hello"}],
        )

    # Check the prompt sent to claude CLI
    call_args = mock_run.call_args
    prompt = call_args.args[0][2]  # ["claude", "-p", <prompt>, ...]
    assert "[System]" in prompt
    assert "You are a test assistant." in prompt
    assert "[User]" in prompt
    assert "Hello" in prompt


def test_create_returns_matching_response_shape():
    """Response has .content[0].text and .usage.input_tokens."""
    msgs = _Messages()

    cli_output = json.dumps({
        "result": "The answer is 42",
        "usage": {"input_tokens": 100, "output_tokens": 25},
    })
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = cli_output

    with patch("pipeline.claude_code_client.subprocess.run", return_value=mock_result):
        response = msgs.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": "What is 6*7?"}],
        )

    assert response.content[0].text == "The answer is 42"
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 25
    assert response.content[0].type == "text"


def test_create_handles_cli_error():
    """Returns error message when claude CLI fails."""
    msgs = _Messages()

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "CLI error"

    with patch("pipeline.claude_code_client.subprocess.run", return_value=mock_result):
        response = msgs.create(
            model="test",
            max_tokens=300,
            messages=[{"role": "user", "content": "test"}],
        )

    assert "Error" in response.content[0].text


def test_client_has_messages_attribute():
    """ClaudeCodeClient() has a .messages.create() interface."""
    client = ClaudeCodeClient()
    assert hasattr(client, "messages")
    assert hasattr(client.messages, "create")
