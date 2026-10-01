"""No live model calls: guardrails for the order-only follow-up experiment."""
import json
import httpx
import pytest

from diplomind.providers.mock import MockProvider
from diplomind.schemas import OrderSet
from scripts import run_order_consistency as trial

KEY = "synthetic-fake-key"


@pytest.mark.asyncio
async def test_eighteen_order_trials_have_fixed_policy_and_total_ceiling(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "OUT", tmp_path)
    seen = []
    mock = MockProvider()
    def endpoint(request):
        data = json.loads(request.content); seen.append(data)
        output = mock.complete(data["messages"], OrderSet)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130,
                      "completion_tokens_details": {"reasoning_tokens": 10 if data["enable_thinking"] else 0}}})
    assert await trial.evaluate(KEY, httpx.MockTransport(endpoint)) == 18
    report = json.loads((tmp_path / "report.json").read_text())
    assert len(report["trials"]) == 18
    assert all(t["status"] == "completed" and t["plan_present"] and not t["dropped_to_fallback"] for t in report["trials"])
    assert sum(p["max_tokens"] for p in seen) == 53248 <= report["limits"]["total_reserved_output_cap"]
    assert sum(p["enable_thinking"] for p in seen) == 8
    assert all(p["max_tokens"] == (4096 if p["enable_thinking"] else 2048) for p in seen)
    assert all(p.get("reasoning_effort") == ("low" if p["enable_thinking"] else None) for p in seen)
    assert KEY not in (tmp_path / "report.json").read_text()


@pytest.mark.asyncio
async def test_mixed_mode_budget_cannot_accidentally_allow_18_all_large_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "OUT", tmp_path)
    seen = []
    def endpoint(request):
        seen.append(request)
        return httpx.Response(500, json={"error": KEY})
    gateway = trial.DecisionGateway(KEY, transport=httpx.MockTransport(endpoint))
    gateway.meta = {"mode": "thinking_low"}
    for _ in range(13): assert await gateway.achat([], OrderSet) is None
    with pytest.raises(RuntimeError, match="ab_output_budget_exhausted"):
        await gateway.achat([], OrderSet)
    assert len(seen) == 13
    await gateway.close()


def test_survival_and_opportunity_are_different_public_positions_not_hidden_orders():
    ally, ordinary, exclusion = trial.scenario("opportunity", "diplomat", None)
    survivor, crisis, _ = trial.scenario("survival", "diplomat", None)
    assert ordinary.centers()["FRANCE"] == 3 and crisis.centers()["FRANCE"] == 1
    assert exclusion == "MUN"
    assert "A BUR - MUN" in survivor._legal_flat(crisis)
    assert all(not p.orders for p in crisis.game.powers.values())
    assert "INVISIBLE_PRIVATE_CANARY" not in survivor.perceive(crisis)
    opportunist, _, _ = trial.scenario("opportunity", "backstabber", None)
    assert opportunist.mem.profile != ally.mem.profile
