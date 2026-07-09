"""Message Batches API wrapper for the pipeline.

Submits a set of independent Claude requests as one batch (billed at 50%),
polls until the batch ends, and returns results keyed by the caller's
custom_id. Batch is API-only — it is not available through the CLI proxy, so
this is used exclusively by the scheduled (PIPELINE_MODE=prod) morning run.

Usage:
    bc = BatchClient(anthropic_client)
    results = bc.run([
        {"custom_id": "story-1", "params": {
            "model": "claude-sonnet-5", "max_tokens": 3000,
            "system": SYSTEM, "messages": [{"role": "user", "content": prompt}],
        }},
        ...
    ])
    msg = results["story-1"].message          # anthropic Message (or None)
    text = results["story-1"].text            # convenience, "" if failed
"""

import logging
import time

logger = logging.getLogger(__name__)


class BatchResult:
    """Outcome of one request within a batch."""

    def __init__(self, custom_id: str, message=None, error: str | None = None):
        self.custom_id = custom_id
        self.message = message
        self.error = error

    @property
    def ok(self) -> bool:
        return self.message is not None

    @property
    def text(self) -> str:
        if not self.message:
            return ""
        for block in self.message.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""


class BatchClient:
    """Thin wrapper over client.messages.batches for the pipeline's needs."""

    def __init__(self, client, poll_interval: float = 15.0, max_wait: float = 3600.0):
        self._client = client
        self._poll_interval = poll_interval
        self._max_wait = max_wait

    def run(self, requests: list[dict]) -> dict[str, BatchResult]:
        """Submit requests, wait for completion, return {custom_id: BatchResult}.

        Args:
            requests: list of {"custom_id": str, "params": <messages.create kwargs>}.

        Returns:
            Mapping custom_id -> BatchResult. Missing/errored requests get a
            BatchResult with error set and message None.
        """
        if not requests:
            return {}

        batch = self._client.messages.batches.create(requests=requests)
        batch_id = batch.id
        logger.info("Submitted batch %s with %d request(s)", batch_id, len(requests))

        self._wait_for_end(batch_id)

        results: dict[str, BatchResult] = {}
        for result in self._client.messages.batches.results(batch_id):
            cid = result.custom_id
            rtype = result.result.type
            if rtype == "succeeded":
                results[cid] = BatchResult(cid, message=result.result.message)
            else:
                detail = getattr(getattr(result.result, "error", None), "type", rtype)
                logger.warning("Batch request %s did not succeed: %s", cid, detail)
                results[cid] = BatchResult(cid, error=str(detail))

        # Any request with no result at all (shouldn't happen) -> error entry.
        for req in requests:
            cid = req["custom_id"]
            results.setdefault(cid, BatchResult(cid, error="no_result"))
        return results

    def _wait_for_end(self, batch_id: str) -> None:
        waited = 0.0
        while True:
            batch = self._client.messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended":
                logger.info("Batch %s ended", batch_id)
                return
            if waited >= self._max_wait:
                raise TimeoutError(
                    f"Batch {batch_id} still {batch.processing_status} after "
                    f"{self._max_wait}s"
                )
            logger.debug(
                "Batch %s status=%s, waited %.0fs", batch_id, batch.processing_status, waited
            )
            time.sleep(self._poll_interval)
            waited += self._poll_interval
