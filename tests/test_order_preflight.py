"""Offline opt-in preflight: one bounded review without enforcing strategy."""
import asyncio
import json

import pytest

from diplomind.agent import Agent
from diplomind.context_budget import PROMPT_BUDGETS
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS
from diplomind.schemas import OrderSet


class ScriptedGateway:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.health = {"status": "ready", "fallbacks": 0}

    async def achat(self, messages, schema, **kwargs):
        self.calls.append((messages, schema, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def setup(*responses, country="ENGLAND", own=None, foreign=None):
    eng = OperationEngine()
    if own is not None:
        eng.game.clear_units()
        eng.game.set_units(country, own)
        for power, units in (foreign or {}).items():
            eng.game.set_units(power, units)
    gw = ScriptedGateway(*responses)
    return Agent(country, PERSONAS["diplomat"], gw), eng, gw


def decision(*orders, **kwargs):
    return OrderSet(orders=list(orders), **kwargs)


COLLISION = ("F EDI - NTH", "F LON - NTH", "A LVP H")
REPAIRED = ("F EDI - NWG", "F LON - NTH", "A LVP H")


@pytest.mark.asyncio
async def test_default_does_not_review_or_change_initial_prompt():
    out = decision(*COLLISION)
    baseline, eng, gw = setup(out)
    _, chosen = await baseline.a_decide_orders(eng)
    opted, other, other_gw = setup(out, decision(*REPAIRED))
    await opted.a_decide_orders(other, preflight_review=True)
    assert chosen == list(COLLISION) and len(gw.calls) == 1
    assert gw.calls[0][0] == other_gw.calls[0][0]
    assert baseline.decision_health["review_attempted"] is False


@pytest.mark.asyncio
async def test_clean_plan_has_no_extra_call():
    out = decision(*REPAIRED)
    ag, eng, gw = setup(out)
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is out and chosen == list(REPAIRED) and len(gw.calls) == 1
    assert ag.decision_health["initial_errors"] == ag.decision_health["final_errors"] == []
    assert ag.decision_health["status"] == "ready"


@pytest.mark.asyncio
async def test_collision_review_records_only_final_actions_and_diagnostics():
    repaired = decision(*REPAIRED)
    ag, eng, gw = setup(decision(*COLLISION), repaired)
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is repaired and chosen == list(REPAIRED)
    assert len(gw.calls) == 2
    assert gw.calls[1][2] == {"tag": "ENGLAND:order_review", "retry": 0, "temp": 0.2}
    assert [a.action for a in ag.mem.actions] == list(REPAIRED)
    assert ag.mem.order_diagnostics == []
    assert ag.decision_health["initial_errors"] == ["own_destination_collision"]
    assert ag.decision_health["final_errors"] == []
    assert ag.decision_health["review_attempted"] is ag.decision_health["review_used"] is True


@pytest.mark.asyncio
async def test_repeated_errors_stop_after_one_review_and_keep_legal_feint():
    retained = decision(*COLLISION, reasoning="Keep the legal failed orders as a feint.")
    ag, eng, gw = setup(decision(*COLLISION), retained)
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is retained and chosen == list(COLLISION) and len(gw.calls) == 2
    assert ag.decision_health["final_errors"] == ["own_destination_collision"]
    assert ag.decision_health["status"] == "degraded"
    prompt = gw.calls[1][0][-1]["content"]
    assert "deliberately retain a legal feint" in prompt
    assert "Do not enforce promises" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("budget_exhausted SECRET_PROVIDER_KEY"), TimeoutError()])
async def test_review_failure_preserves_usable_initial_without_raw_exception(failure):
    initial = decision(*COLLISION)
    ag, eng, gw = setup(initial, failure)
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is initial and chosen == list(COLLISION) and len(gw.calls) == 2
    assert ag.decision_health["review_attempted"] and not ag.decision_health["review_used"]
    assert ag.decision_health["review_error"] in {"no_review_response", "review_unavailable"}
    assert [a.action for a in ag.mem.actions] == list(COLLISION)
    assert "SECRET_PROVIDER_KEY" not in json.dumps(ag.snapshot())


@pytest.mark.asyncio
async def test_cancellation_propagates_without_recording_provisional_actions():
    ag, eng, gw = setup(decision(*COLLISION), asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await ag.a_decide_orders(eng, preflight_review=True)
    assert len(gw.calls) == 2 and ag.mem.actions == [] and ag.mem.order_diagnostics == []


@pytest.mark.asyncio
async def test_no_initial_response_does_not_review_and_is_degraded_hold():
    ag, eng, gw = setup(None)
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is None and chosen == [] and len(gw.calls) == 1
    assert not ag.decision_health["review_attempted"]
    assert ag.decision_health["status"] == "degraded"
    assert "no_order_response" in ag.decision_health["final_errors"]
    assert "missing_order" in ag.decision_health["final_errors"]


@pytest.mark.asyncio
async def test_empty_review_cannot_replace_usable_initial_with_degraded_holds():
    initial = decision(*COLLISION)
    ag, eng, gw = setup(initial, decision("RAW_REVIEW_SECRET"))
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is initial and chosen == list(COLLISION) and len(gw.calls) == 2
    assert ag.decision_health["review_error"] == "unusable_review"
    assert not ag.decision_health["review_used"]
    assert "RAW_REVIEW_SECRET" not in json.dumps(ag.snapshot())


@pytest.mark.asyncio
async def test_acknowledged_standoff_does_not_trigger_review():
    out = decision(*COLLISION, intentional_self_standoffs=["NTH"], reasoning="Deliberate defensive standoff")
    ag, eng, gw = setup(out)
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is out and chosen == list(COLLISION) and len(gw.calls) == 1
    assert ag.decision_health["final_errors"] == []
    assert ag.mem.order_diagnostics[0]["acknowledged"]


@pytest.mark.asyncio
async def test_foreign_convoy_uncertainty_does_not_trigger_or_read_sealed_orders():
    out = decision("A APU - GRE VIA")
    ag, eng, gw = setup(out, country="ITALY", own=["A APU"], foreign={"TURKEY": ["F ION"]})
    eng.game.powers["TURKEY"].orders = {"F ION": "SEALED_PRIVATE_CANARY"}
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is out and chosen == ["A APU - GRE VIA"] and len(gw.calls) == 1
    assert ag.decision_health["final_errors"] == []
    assert ag.mem.order_diagnostics[0]["code"] == "convoy_requires_foreign_cooperation"
    assert "SEALED_PRIVATE_CANARY" not in json.dumps(gw.calls, default=str)


@pytest.mark.asyncio
async def test_impossible_own_convoy_triggers_single_review():
    initial = decision("A APU - GRE VIA", "F ION - TUN")
    repair = decision("A APU - GRE VIA", "F ION C A APU - GRE")
    ag, eng, gw = setup(initial, repair, country="ITALY", own=["A APU", "F ION"])
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is repair and chosen == repair.orders and len(gw.calls) == 2
    assert ag.decision_health["initial_errors"] == ["no_planned_convoy_path"]
    assert ag.decision_health["final_errors"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("orders,code", [
    (("F EDI S F LON - NTH", "F LON - ENG", "A LVP H"), "own_support_mismatch"),
    (("A YOR - LON", "F LON H", "F EDI H"), "own_nonvacating_destination"),
])
async def test_demonstrable_own_coordination_error_triggers(orders, code):
    out = decision(*orders)
    ag, eng, gw = setup(out, out, own=["A YOR", "F LON", "F EDI"] if code == "own_nonvacating_destination" else None)
    await ag.a_decide_orders(eng, preflight_review=True)
    assert len(gw.calls) == 2 and code in ag.decision_health["initial_errors"]


@pytest.mark.asyncio
@pytest.mark.parametrize("initial,code", [
    (decision("A PAR - GAS", "A PAR - BUR"), "duplicate_order"),
    (decision("A PAR - GAS", "RAW_CREDENTIAL_SECRET"), "unrecognized_order"),
    (decision("A PAR - GAS", unit_plan=[{"unit": "A PAR", "order": "A PAR - BUR"}]), "structured_plan_mismatch"),
])
async def test_structural_errors_trigger_without_echoing_untrusted_output(initial, code):
    initial.reasoning = "INITIAL_REASONING_SECRET"
    repaired = decision("A PAR H", "A MAR H", "F BRE H")
    ag, eng, gw = setup(initial, repaired, country="FRANCE")
    ag.observe_messages(eng.phase(), [{"sender": "RUSSIA", "scope": "private", "to": ["TURKEY"], "rnd": 1,
                                      "text": "OTHER_POWERS_PRIVATE_SECRET"}])
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is repaired and chosen == repaired.orders and len(gw.calls) == 2
    assert code in ag.decision_health["initial_errors"]
    prompt = gw.calls[1][0][-1]["content"]
    for secret in ("RAW_CREDENTIAL_SECRET", "INITIAL_REASONING_SECRET", "OTHER_POWERS_PRIVATE_SECRET"):
        assert secret not in prompt and secret not in json.dumps(ag.snapshot())
    feedback = json.loads(prompt.split("PREFLIGHT_DIAGNOSTICS:", 1)[1])
    assert set(feedback["candidate_orders"]).issubset(ag._legal_flat(eng))
    assert all(set(d["orders"]).issubset(ag._legal_flat(eng)) for d in feedback["diagnostics"])
    assert len(json.dumps(feedback, ensure_ascii=False, separators=(",", ":")).encode()) <= 4096


@pytest.mark.asyncio
async def test_legal_betrayal_and_prose_contradictions_do_not_trigger_review():
    out = decision("A PAR - BUR", "A MAR H", "F BRE H", reasoning="Honor the DMZ, never enter BUR")
    ag, eng, gw = setup(out, country="FRANCE")
    ag.observe_diplomacy(eng.phase(), "FRANCE promised Germany not to enter BUR.")
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is out and "A PAR - BUR" in chosen and len(gw.calls) == 1


@pytest.mark.asyncio
async def test_missing_orders_alone_are_degraded_without_speculative_review():
    ag, eng, gw = setup(decision("F EDI H"))
    await ag.a_decide_orders(eng, preflight_review=True)
    assert len(gw.calls) == 1 and ag.decision_health["status"] == "degraded"
    assert ag.decision_health["final_errors"] == ["missing_order"]


@pytest.mark.asyncio
async def test_prompt_budget_prevents_extra_call_without_losing_initial(monkeypatch):
    initial = decision(*COLLISION)
    ag, eng, gw = setup(initial)
    initial_prompt = ag._order_prompt(eng, ag._legal_flat(eng)) + ag._stab_cue(eng)
    byte_count = len((ag.sys["content"] + "\n" + initial_prompt).encode())
    monkeypatch.setitem(PROMPT_BUDGETS, "order", byte_count + 1)
    result, chosen = await ag.a_decide_orders(eng, preflight_review=True)
    assert result is initial and chosen == list(COLLISION) and len(gw.calls) == 1
    assert ag.decision_health["review_error"] == "review_prompt_budget"
    assert not ag.decision_health["review_attempted"]


@pytest.mark.asyncio
async def test_many_diagnostics_are_bounded_and_omission_is_reported():
    initial = decision(*COLLISION, *([COLLISION[0]] * 100))
    ag, eng, gw = setup(initial, decision(*REPAIRED))
    await ag.a_decide_orders(eng, preflight_review=True)
    prompt = gw.calls[1][0][-1]["content"]
    payload = prompt.split("PREFLIGHT_DIAGNOSTICS:", 1)[1]
    feedback = json.loads(payload)
    assert len(payload.encode()) <= 4096 and len(feedback["diagnostics"]) <= 16
    assert feedback["details_omitted"]
    assert ag.context_stats["order_review"]["prompt_bytes"] <= PROMPT_BUDGETS["order"]


@pytest.mark.asyncio
async def test_later_clean_decision_clears_prior_review_metadata():
    ag, eng, gw = setup(decision(*COLLISION), decision(*REPAIRED), decision(*REPAIRED))
    await ag.a_decide_orders(eng, preflight_review=True)
    assert ag.decision_health["review_used"] and "order_review" in ag.context_stats
    await ag.a_decide_orders(eng, preflight_review=True)
    assert len(gw.calls) == 3
    assert not ag.decision_health["review_used"] and not ag.decision_health["review_attempted"]
    assert ag.decision_health["initial_errors"] == [] and "order_review" not in ag.context_stats
