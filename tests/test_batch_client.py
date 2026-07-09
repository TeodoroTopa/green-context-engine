"""Tests for the Message Batches API wrapper."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pipeline.batch_client import BatchClient, BatchResult


def _text_message(text):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def _succeeded(cid, text):
    return SimpleNamespace(
        custom_id=cid,
        result=SimpleNamespace(type="succeeded", message=_text_message(text)),
    )


def _errored(cid, err_type="invalid_request"):
    return SimpleNamespace(
        custom_id=cid,
        result=SimpleNamespace(type="errored", error=SimpleNamespace(type=err_type)),
    )


def _client(results, statuses=("ended",)):
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id="batch_123")
    client.messages.batches.retrieve.side_effect = [
        SimpleNamespace(processing_status=s) for s in statuses
    ]
    client.messages.batches.results.return_value = iter(results)
    return client


def test_empty_requests_returns_empty():
    bc = BatchClient(MagicMock())
    assert bc.run([]) == {}


def test_successful_batch_keyed_by_custom_id():
    client = _client([_succeeded("a", "Alpha"), _succeeded("b", "Beta")])
    bc = BatchClient(client, poll_interval=0)
    results = bc.run([
        {"custom_id": "a", "params": {"model": "m", "max_tokens": 10, "messages": []}},
        {"custom_id": "b", "params": {"model": "m", "max_tokens": 10, "messages": []}},
    ])
    assert results["a"].ok and results["a"].text == "Alpha"
    assert results["b"].text == "Beta"


def test_errored_request_marked_not_ok():
    client = _client([_succeeded("a", "Alpha"), _errored("b")])
    bc = BatchClient(client, poll_interval=0)
    results = bc.run([
        {"custom_id": "a", "params": {}},
        {"custom_id": "b", "params": {}},
    ])
    assert results["a"].ok
    assert not results["b"].ok
    assert results["b"].error == "invalid_request"
    assert results["b"].text == ""


def test_polls_until_ended(monkeypatch):
    monkeypatch.setattr("pipeline.batch_client.time.sleep", lambda s: None)
    client = _client([_succeeded("a", "A")], statuses=("in_progress", "in_progress", "ended"))
    bc = BatchClient(client, poll_interval=0.01)
    results = bc.run([{"custom_id": "a", "params": {}}])
    assert results["a"].text == "A"
    assert client.messages.batches.retrieve.call_count == 3


def test_missing_result_becomes_error_entry():
    # results() yields nothing for "b"
    client = _client([_succeeded("a", "A")])
    bc = BatchClient(client, poll_interval=0)
    results = bc.run([
        {"custom_id": "a", "params": {}},
        {"custom_id": "b", "params": {}},
    ])
    assert results["a"].ok
    assert results["b"].error == "no_result"


def test_timeout_raises(monkeypatch):
    monkeypatch.setattr("pipeline.batch_client.time.sleep", lambda s: None)
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id="b1")
    client.messages.batches.retrieve.return_value = SimpleNamespace(processing_status="in_progress")
    bc = BatchClient(client, poll_interval=1, max_wait=2)
    with pytest.raises(TimeoutError):
        bc.run([{"custom_id": "a", "params": {}}])


def test_batchresult_text_helper():
    assert BatchResult("x", error="boom").text == ""
    assert not BatchResult("x", error="boom").ok
