"""Drop-in replacement for the Anthropic client that routes through claude CLI.

Uses `claude -p` which runs on your Claude Code subscription instead of
billing the Anthropic API. Toggle via PIPELINE_MODE=dev in .env.

Usage:
    from pipeline.claude_code_client import ClaudeCodeClient
    client = ClaudeCodeClient()
    response = client.messages.create(model="...", max_tokens=3000, messages=[...])
    print(response.content[0].text)
"""

import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


class _TextBlock:
    """Mimics anthropic.types.ContentBlock."""

    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _Usage:
    """Mimics anthropic.types.Usage."""

    def __init__(self, input_tokens: int = 0, output_tokens: int = 0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Response:
    """Mimics anthropic.types.Message."""

    def __init__(self, text: str, input_tokens: int = 0, output_tokens: int = 0):
        self.content = [_TextBlock(text)]
        self.usage = _Usage(input_tokens, output_tokens)
        self.model = "claude-code-proxy"
        self.stop_reason = "end_turn"


class _Messages:
    """Mimics client.messages with a create() method."""

    def create(self, *, model: str = "", max_tokens: int = 4096,
               messages: list[dict], system: str = "", **kwargs) -> _Response:
        """Build a prompt from messages and call claude -p."""
        prompt_parts = []
        if system:
            prompt_parts.append(f"[System]\n{system}\n")
        for msg in messages:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            prompt_parts.append(f"[{role}]\n{content}")
        prompt = "\n\n".join(prompt_parts)

        logger.info(f"Claude Code proxy: routing {len(prompt)} chars through claude CLI")

        try:
            # Remove ANTHROPIC_API_KEY from env so claude CLI uses subscription
            # auth instead of the API (which may have no credits).
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

            result = subprocess.run(
                ["claude", "-p", "--output-format", "json"],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                env=env,
            )
            # Parse JSON even on non-zero exit (CLI returns rc=1 for some errors
            # but still provides valid JSON with error details)
            if not result.stdout.strip():
                logger.error(f"claude CLI returned no output: {result.stderr}")
                return _Response("Error: claude CLI returned no output")

            data = json.loads(result.stdout)
            if data.get("is_error"):
                logger.error(f"claude CLI error: {data.get('result', '')[:200]}")
                return _Response(f"Error: {data.get('result', 'unknown')}")
            text = data.get("result", "")
            usage = data.get("usage", {})
            return _Response(
                text=text,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
        except subprocess.TimeoutExpired:
            logger.error("claude CLI timed out after 120s")
            return _Response("Error: claude CLI timed out")
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse claude CLI output: {e}")
            return _Response("Error: failed to parse claude CLI response")


class ClaudeCodeClient:
    """Drop-in replacement for anthropic.Anthropic() that uses claude CLI."""

    def __init__(self):
        self.messages = _Messages()
