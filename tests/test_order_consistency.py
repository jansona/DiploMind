"""Offline structural checks never enforce prose promises or strategic choices."""
import json
import pytest
from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.memory import Memory
from diplomind.personalities import PERSONAS
from diplomind.schemas import OrderSet, UnitPlan


class Gateway:
    def __init__(self, output):
        self.output, self.calls = output, 0
        self.health = {"status": "ready", "fallbacks": 0}
    async def achat(self, *args, **kwargs):
        self.calls += 1
        return self.output


async def run(output, country="FRANCE", eng=None):
    gateway = Gateway(output)
    agent = Agent(country, PERSONAS["diplomat"], gateway)
    engine = eng or OperationEngine()
    result, chosen = await agent.a_decide_orders(engine)
    return agent, gateway, engine, result, chosen


def test_schema_emits_brief_decision_then_plan_and_final_orders_last():
    keys = list(OrderSet.model_json_schema()["properties"])
    assert keys[0] == "reasoning" and keys[-1] == "orders"
    assert keys.index("unit_plan") < keys.index("orders")
    assert OrderSet(orders=["A PAR H"]).unit_plan == []
    assert OrderSet(unit_plan=None).unit_plan == []
    assert UnitPlan(unit="A PAR", order=0).order == "0"


@pytest.mark.asyncio
async def test_conflicting_unit_rejected_without_silently_substituting_plan():
    out = OrderSet(reasoning="Use GAS, not BUR", unit_plan=[UnitPlan(unit="A PAR", order="A PAR - GAS"), UnitPlan(unit="F BRE", order="F BRE - MAO")], orders=["A PAR - BUR", "F BRE - MAO"])
    ag, gw, eng, result, chosen = await run(out)
    assert result is out and chosen == ["F BRE - MAO"]
    assert "A PAR - GAS" not in chosen
    warnings = [d for d in ag.mem.order_diagnostics if d["code"] == "structured_plan_mismatch"]
    assert len(warnings) == 1 and warnings[0]["location"] == "PAR"
    assert set(warnings[0]["orders"]) == {"A PAR - GAS", "A PAR - BUR"}
    assert gw.calls == 1 and gw.health["status"] == ag.decision_health["status"] == "degraded"
    assert gw.health["last_error"] == "structured_plan_mismatch"
    assert eng.submit("FRANCE", chosen).accepted == chosen


@pytest.mark.asyncio
async def test_wrong_unit_label_rejects_both_ambiguous_units_keeps_coherent_third():
    out = OrderSet(unit_plan=[UnitPlan(unit="F BRE", order="A PAR - BUR"), UnitPlan(unit="A MAR", order="A MAR - SPA")], orders=["A PAR - BUR", "F BRE - MAO", "A MAR - SPA"])
    ag, _, _, _, chosen = await run(out)
    assert chosen == ["A MAR - SPA"]
    assert {d["location"] for d in ag.mem.order_diagnostics if d["code"] == "structured_plan_mismatch"} == {"PAR", "BRE"}


@pytest.mark.asyncio
async def test_matching_deliberate_betrayal_is_not_rejected_and_rationale_is_not_parsed():
    out = OrderSet(reasoning="I will honor the BUR DMZ and go GAS", unit_plan=[UnitPlan(unit="A PAR", order="A PAR - BUR")], orders=["A PAR - BUR"])
    ag, gw, _, _, chosen = await run(out)
    assert chosen == ["A PAR - BUR"]  # No NLP rationale/promise enforcement.
    assert not any(d["code"] == "structured_plan_mismatch" for d in ag.mem.order_diagnostics)
    assert gw.health["status"] == "ready"


@pytest.mark.asyncio
async def test_legacy_provider_without_plan_keeps_previous_behavior():
    _, gw, _, _, chosen = await run(OrderSet(orders=["A PAR - BUR"]))
    assert chosen == ["A PAR - BUR"] and gw.calls == 1


@pytest.mark.asyncio
async def test_plan_and_final_numeric_ids_use_same_canonical_engine_table():
    eng = OperationEngine(); ag = Agent("FRANCE", PERSONAS["diplomat"], None)
    flat = ag._legal_flat(eng); idx = flat.index("A PAR - GAS")
    out = OrderSet(unit_plan=[UnitPlan(unit="A PAR", order=str(idx))], orders=["A PAR-GAS"])
    _, _, _, _, chosen = await run(out, eng=eng)
    assert chosen == ["A PAR - GAS"]


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", [
    [UnitPlan(unit="A PAR", order="A PAR - GAS"), UnitPlan(unit="A PAR", order="A PAR - BUR")],
    [UnitPlan(unit="A PAR", order="UNTRUSTED_PRIVATE_CANARY")],
])
async def test_duplicate_conflict_or_illegal_plan_defaults_affected_unit_without_raw_diagnostics(plan):
    ag, _, _, _, chosen = await run(OrderSet(unit_plan=plan, orders=["A PAR - BUR"]))
    assert chosen == []
    assert "UNTRUSTED_PRIVATE_CANARY" not in json.dumps(ag.mem.order_diagnostics)
    restored = Memory("FRANCE"); restored.restore(ag.mem.snapshot())
    assert any(d["code"] == "structured_plan_mismatch" for d in restored.order_diagnostics)


@pytest.mark.asyncio
async def test_present_partial_plan_rejects_unplanned_final_unit_only():
    _, _, _, _, chosen = await run(OrderSet(unit_plan=[UnitPlan(unit="A PAR", order="A PAR - GAS")], orders=["A PAR - GAS", "F BRE - MAO"]))
    assert chosen == ["A PAR - GAS"]


@pytest.mark.asyncio
async def test_coherent_intentional_self_standoff_keeps_acknowledgement():
    orders = ["F EDI - NTH", "F LON - NTH", "A LVP H"]
    out = OrderSet(unit_plan=[UnitPlan(unit=" ".join(o.split()[:2]), order=o) for o in orders], orders=orders, intentional_self_standoffs=["NTH"])
    ag, _, _, _, chosen = await run(out, "ENGLAND")
    assert chosen == orders
    assert any(d["code"] == "own_destination_collision" and d["acknowledged"] for d in ag.mem.order_diagnostics)


def test_move_into_own_nonvacating_unit_is_diagnostic_only():
    eng = OperationEngine(); eng.game.clear_units(); eng.game.set_units("ENGLAND", ["A YOR", "F LON", "F EDI"])
    ag = Agent("ENGLAND", PERSONAS["diplomat"], None)
    orders = ["A YOR - LON", "F LON S F EDI - NTH", "F EDI - NTH"]
    assert all(o in ag._legal_flat(eng) for o in orders)
    warnings = ag._diagnose_orders(eng, orders, [])
    assert any(d["code"] == "own_nonvacating_destination" for d in warnings)
    assert eng.submit("ENGLAND", orders).accepted == orders


@pytest.mark.asyncio
async def test_completely_unknown_plan_row_is_reported_without_leaking_raw_text():
    out = OrderSet(unit_plan=[UnitPlan(unit="A XYZ", order="SECRET_CANARY"), UnitPlan(unit="A PAR", order="A PAR - GAS")], orders=["A PAR - GAS"])
    ag, gw, _, _, chosen = await run(out)
    assert chosen == ["A PAR - GAS"]
    assert ag.decision_health["status"] == gw.health["status"] == "degraded"
    assert any(d["code"] == "structured_plan_mismatch" for d in ag.mem.order_diagnostics)
    assert "SECRET_CANARY" not in json.dumps(ag.mem.order_diagnostics)
