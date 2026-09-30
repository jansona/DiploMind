"""Offline contracts for the bounded real context evaluation; synthetic auth only."""
import json
import logging

import httpx
import pytest

from diplomind.providers.mock import MockProvider
from diplomind.schemas import AttitudeUpdate, Message, OrderSet
from scripts import run_context_ab as ab

FAKE_KEY = "synthetic-offline-test-key"


def local_endpoint(seen):
    mock = MockProvider()
    schemas = {c.__name__: c for c in (AttitudeUpdate, Message, OrderSet)}
    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        spec = json.loads(payload["messages"][-1]["content"].split("Schema: ", 1)[1])
        output = mock.complete(payload["messages"], schemas[spec["title"]])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                      "prompt_tokens_details": {"cached_tokens": 15}}})
    return httpx.MockTransport(respond)


@pytest.mark.asyncio
async def test_matched_suite_is_exactly_60_bounded_calls_without_hidden_private_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "OUT", tmp_path)
    seen = []
    calls = await ab.evaluate(FAKE_KEY, local_endpoint(seen))
    report = json.loads((tmp_path / "report.json").read_text())
    assert calls == len(seen) == 60
    assert len(report["trials"]) == 20
    assert all(t["status"] == "completed" for t in report["trials"])
    assert all(p["max_tokens"] == 2048 and p["enable_thinking"] is False for p in seen)
    assert all(p["model"] == ab.MODEL for p in seen)
    assert all(ab.CANARY not in json.dumps(p) and FAKE_KEY not in json.dumps(p) for p in seen)
    assert all(r["usage"]["cached_tokens"] == 15 and r["queue_ms"] == 0 for r in report["records"])
    assert FAKE_KEY not in (tmp_path / "report.json").read_text()


@pytest.mark.asyncio
async def test_budget_blocks_61st_request_and_never_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "OUT", tmp_path)
    seen = []
    gw = ab.ABGateway(FAKE_KEY, transport=local_endpoint(seen))
    for _ in range(60):
        await gw.achat([{"role": "user", "content": "synthetic"}], AttitudeUpdate, retry=99)
    with pytest.raises(RuntimeError, match="ab_budget_exhausted"):
        await gw.achat([], AttitudeUpdate)
    assert len(seen) == 60
    await gw.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [(302, "http_302"), (401, "http_401"), (429, "http_429"), (500, "http_500")])
async def test_provider_error_never_copies_body_or_follows_redirect(tmp_path, monkeypatch, status, error):
    monkeypatch.setattr(ab, "OUT", tmp_path)
    seen = []
    def fail(request):
        seen.append(request)
        return httpx.Response(status, json={"error": FAKE_KEY}, headers={"location": "https://invalid.example"})
    gw = ab.ABGateway(FAKE_KEY, transport=httpx.MockTransport(fail))
    assert await gw.achat([], AttitudeUpdate, retry=99) is None
    assert len(seen) == 1 and gw.records[0]["error"] == error
    assert FAKE_KEY not in (tmp_path / "report.json").read_text()
    await gw.close()


@pytest.mark.asyncio
async def test_private_canary_blocks_before_transmission(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "OUT", tmp_path)
    gw = ab.ABGateway(FAKE_KEY, transport=httpx.MockTransport(lambda request: pytest.fail("network called")))
    with pytest.raises(RuntimeError, match="privacy_canary_detected"):
        await gw.achat([{"role": "user", "content": ab.CANARY}], Message)
    assert not gw.records
    await gw.close()


@pytest.mark.asyncio
async def test_schema_failure_and_echoed_key_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "OUT", tmp_path)
    def respond(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"type": "broadcast", "recipient": [], "content": FAKE_KEY})}, "finish_reason": "stop"}]})
    gw = ab.ABGateway(FAKE_KEY, transport=httpx.MockTransport(respond))
    assert await gw.achat([], Message) is None
    assert gw.records[0]["error"] == "credential_echo_detected"
    assert FAKE_KEY not in (tmp_path / "report.json").read_text()
    await gw.close()


@pytest.mark.asyncio
async def test_credential_echo_in_json_dictionary_key_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "OUT", tmp_path)
    def respond(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"scores": {FAKE_KEY: 5}, "attitudes": {FAKE_KEY: "synthetic"}})}, "finish_reason": "stop"}]})
    gw = ab.ABGateway(FAKE_KEY, transport=httpx.MockTransport(respond))
    assert await gw.achat([], AttitudeUpdate) is None
    assert gw.records[0]["error"] == "credential_echo_detected"
    assert FAKE_KEY not in json.dumps(gw.safe({FAKE_KEY: {"nested": FAKE_KEY}}))
    assert FAKE_KEY not in (tmp_path / "report.json").read_text()
    await gw.close()
