"""Offline evidence/coordination regressions; no real gateway or credentials."""
import json

import pytest

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.memory import Memory
from diplomind.personalities import PERSONAS
from diplomind.providers.mock import context_from
from diplomind.schemas import AttitudeUpdate, Intent, Message, OrderSet


class CaptureGateway:
    def __init__(self, orders=None, intentional=None):
        self.orders = orders or []
        self.intentional = intentional or []
        self.calls = []

    async def achat(self, messages, schema, **kwargs):
        self.calls.append((messages, schema))
        if schema is OrderSet:
            return OrderSet(orders=self.orders, reasoning="Local test plan", intentional_self_standoffs=self.intentional)
        return schema()


def agent(country="ENGLAND", gateway=None):
    return Agent(country, PERSONAS["diplomat"], gateway)


def collide(eng):
    eng.submit("ENGLAND", ["F EDI - NTH", "F LON - NTH", "A LVP - YOR"])
    eng.submit("AUSTRIA", ["A BUD - GAL"])
    eng.submit("RUSSIA", ["A WAR - GAL"])
    eng.process()


def test_initial_context_never_publishes_pending_orders():
    eng = OperationEngine()
    france = agent("FRANCE")
    before = france._context(eng)
    eng.submit("ENGLAND", ["F EDI - NTH", "F LON - NTH"])
    eng.submit("GERMANY", ["A MUN - RUH"])
    assert france._context(eng) == before
    assert before["last_adjudication"] is None
    assert eng.recent_adjudications() == []


def test_published_results_distinguish_bounces_from_locations_and_future_orders():
    eng = OperationEngine()
    collide(eng)
    france = agent("FRANCE")
    ctx = france._context(eng)
    result = ctx["last_adjudication"]
    assert result["phase"] == "S1901M" and result["source"] == "public_result"
    assert result["results"]["F EDI"] == result["results"]["F LON"] == ["bounce"]
    assert result["results"]["A BUD"] == result["results"]["A WAR"] == ["bounce"]
    assert set(result["units_after"]["ENGLAND"]) == {"F EDI", "F LON", "A YOR"}
    assert "A WAR" in result["units_after"]["RUSSIA"]
    assert "A GAL" not in result["units_after"]["RUSSIA"]
    assert result["units_after"] == ctx["units"]
    assert "A LVP" in result["units_before"]["ENGLAND"]
    eng.submit("ENGLAND", ["F EDI - NWG", "F LON - ENG", "A YOR - LVP"])
    eng.submit("GERMANY", ["A MUN - RUH"])
    assert france._context(eng) == ctx
    assert "F EDI - NWG" not in json.dumps(ctx)
    # Result data is detached, not a mutable view into the live rules engine.
    result["results"]["F EDI"].clear()
    assert eng.last_adjudication()["results"]["F EDI"] == ["bounce"]


def test_claims_keep_delivered_provenance_and_cannot_replace_board_facts():
    eng = OperationEngine()
    collide(eng)
    claim = {"sender": "ENGLAND", "scope": "private", "to": ["GERMANY"],
             "rnd": 1, "text": "Both my fleets are already in the North Sea."}
    germany, france = agent("GERMANY"), agent("FRANCE")
    for power in (germany, france):
        power.observe_messages(eng.phase(), [claim])
    visible = germany._context(eng)
    assert visible["visible_evidence"][0]["speaker"] == "ENGLAND"
    assert visible["visible_evidence"][0]["source"] == "direct_private"
    assert visible["visible_evidence"][0]["verified"] is False
    assert "F NTH" not in visible["units"]["ENGLAND"]
    assert not france._context(eng)["visible_evidence"]
    assert "可以策略性说谎" in germany.perceive(eng)
    assert "不能当作事实" in germany.perceive(eng)


@pytest.mark.asyncio
async def test_collision_warns_without_rewriting_or_extra_model_calls():
    eng = OperationEngine()
    orders = ["F EDI - NTH", "F LON - NTH", "A LVP - YOR"]
    gateway = CaptureGateway(orders)
    england = agent(gateway=gateway)
    _, chosen = await england.a_decide_orders(eng)
    assert chosen == orders and len(gateway.calls) == 1
    warning, = england.mem.order_diagnostics
    assert warning["code"] == "own_destination_collision"
    assert warning["destination"] == "NTH" and warning["acknowledged"] is False
    assert warning["source"] == "own_order_diagnostic" and warning["phase"] == "S1901M"
    eng.submit("ENGLAND", chosen)
    eng.process()
    gateway.orders = ["F EDI - NWG", "F LON - NTH", "A YOR H"]
    await england.a_update(eng)
    await england.a_intent(eng)
    await england.a_negotiate(eng, "")
    await england.a_decide_orders(eng)
    assert len(gateway.calls) == 5  # Exactly one call per requested decision.
    assert [schema for _, schema in gateway.calls[1:]] == [AttitudeUpdate, Intent, Message, OrderSet]
    for messages, _ in gateway.calls[1:]:
        ctx = context_from(messages)
        assert warning in ctx["own_order_diagnostics"]
        assert ctx["recent_own_adjudications"][-1]["results"]["F EDI"] == ["bounce"]
        assert "F EDI" in ctx["units"]["ENGLAND"] and "F NTH" not in ctx["units"]["ENGLAND"]
        assert "acknowledged=false" in messages[-1]["content"]
    # Each country's private diagnostics/results are its own.
    other = agent("FRANCE")._context(eng)
    assert other["own_order_diagnostics"] == []
    assert "F EDI" not in other["recent_own_adjudications"][-1]["results"]


@pytest.mark.asyncio
async def test_intentional_legal_self_standoff_remains_legal_and_is_acknowledged():
    eng = OperationEngine()
    orders = ["F EDI - NTH", "F LON - NTH", "A LVP H"]
    gateway = CaptureGateway(orders, intentional=["NTH", "GAL"])
    england = agent(gateway=gateway)
    _, chosen = await england.a_decide_orders(eng)
    assert chosen == orders and len(gateway.calls) == 1
    assert eng.submit("ENGLAND", chosen).accepted == orders
    warning, = england.mem.order_diagnostics
    assert warning["destination"] == "NTH" and warning["acknowledged"] is True
    eng.process()
    assert eng.last_adjudication()["results"]["F EDI"] == ["bounce"]
    assert "F EDI" in eng.game.powers["ENGLAND"].units
    assert "F LON" in eng.game.powers["ENGLAND"].units


@pytest.mark.asyncio
async def test_diagnostics_and_results_survive_json_save_load(tmp_path):
    eng = OperationEngine()
    gateway = CaptureGateway(["F EDI - NTH", "F LON - NTH", "A LVP H"])
    england = agent(gateway=gateway)
    _, chosen = await england.a_decide_orders(eng)
    eng.submit("ENGLAND", chosen)
    eng.process()
    original = england._context(eng)
    path = tmp_path / "evidence-save.json"
    path.write_text(json.dumps({"engine": eng.save(), "memory": england.mem.snapshot()}))
    saved = json.loads(path.read_text())
    reloaded = OperationEngine()
    reloaded.load(saved["engine"])
    restored = agent()
    restored.mem.restore(saved["memory"])
    assert restored._context(reloaded) == original
    restored._context(reloaded)
    assert len(restored.mem.own_adjudications) == 1


def test_skipped_retreat_keeps_movement_bounce_evidence_and_phase_correct_positions():
    eng = OperationEngine()
    eng.game.clear_units()
    for power, units in {"ENGLAND": ["F EDI", "F LON"], "FRANCE": ["A PAR", "A PIC"], "GERMANY": ["A BUR"]}.items():
        eng.game.set_units(power, units)
    eng.submit("ENGLAND", ["F EDI - NTH", "F LON - NTH"])
    eng.submit("FRANCE", ["A PAR - BUR", "A PIC S A PAR - BUR"])
    eng.submit("GERMANY", ["A BUR H"])
    assert eng.process() == "S1901R"
    assert "*A BUR" in eng.last_adjudication()["units_after"]["GERMANY"]
    eng.submit("GERMANY", ["A BUR R MUN"])
    assert eng.process() == "F1901M"
    ctx = agent()._context(eng)  # No AI cognition ran in the retreat phase.
    assert ctx["last_adjudication"]["phase"] == "S1901R"
    assert [a["phase"] for a in ctx["recent_own_adjudications"]] == ["S1901M", "S1901R"]
    assert ctx["recent_own_adjudications"][0]["results"]["F EDI"] == ["bounce"]
    assert "*A BUR" in eng.recent_adjudications()[0]["units_after"]["GERMANY"]
    assert ctx["units"]["GERMANY"] == ["A MUN"]
    assert eng.recent_adjudications(limit=0) == []


def test_collision_normalizes_coasts_but_keeps_original_legal_orders():
    eng = OperationEngine()
    eng.game.clear_units()
    eng.game.set_units("FRANCE", ["F MAO", "F WES"])
    france = agent("FRANCE")
    orders = ["F MAO - SPA/NC", "F WES - SPA/SC"]
    assert all(o in france._legal_flat(eng) for o in orders)
    warning, = france._diagnose_orders(eng, orders, ["SPA/SC"])
    assert warning["destination"] == "SPA" and warning["acknowledged"] is True
    assert warning["orders"] == orders
    assert eng.submit("FRANCE", orders).accepted == orders


@pytest.mark.parametrize("move,support,mismatch", [
    ("A PAR - BUR", "A PIC S A PAR - BUR", False),
    ("A PAR H", "A PIC S A PAR - BUR", True),
    ("A PAR - BUR", "A PIC S A PAR", True),
    ("A PAR H", "A PIC S A PAR", False),
])
def test_own_support_checks_chosen_order(move, support, mismatch):
    eng = OperationEngine()
    eng.game.clear_units()
    eng.game.set_units("FRANCE", ["A PAR", "A PIC"])
    france = agent("FRANCE")
    assert all(o in france._legal_flat(eng) for o in (move, support))
    warnings = france._diagnose_orders(eng, [move, support], [])
    assert bool(warnings) is mismatch
    assert all(w["code"] == "own_support_mismatch" for w in warnings)


def test_support_does_not_consult_another_powers_pending_order():
    eng = OperationEngine()
    eng.game.clear_units()
    eng.game.set_units("FRANCE", ["A PIC"])
    eng.game.set_units("GERMANY", ["A PAR"])
    france = agent("FRANCE")
    order = "A PIC S A PAR - BUR"
    assert order in france._legal_flat(eng)
    eng.submit("GERMANY", ["A PAR H"])
    assert france._diagnose_orders(eng, [order], []) == []


@pytest.mark.asyncio
async def test_unknown_duplicate_and_missing_orders_are_private_diagnostics():
    eng = OperationEngine()
    gateway = CaptureGateway(["F EDI - MOON", "F LON - NTH", "F LON H"])
    england = agent(gateway=gateway)
    _, chosen = await england.a_decide_orders(eng)
    assert chosen == ["F LON - NTH"]
    codes = [d["code"] for d in england.mem.order_diagnostics]
    assert codes.count("missing_order") == 2
    assert "unrecognized_order" in codes and "duplicate_order" in codes
    assert "MOON" not in json.dumps(england.mem.order_diagnostics)
    assert next(d for d in england.mem.order_diagnostics if d["code"] == "unrecognized_order")["input_index"] == 0
    assert all(d["source"] == "own_order_diagnostic" for d in england.mem.order_diagnostics)
    assert agent("FRANCE")._context(eng)["own_order_diagnostics"] == []


def test_old_saves_and_bounded_diagnostics():
    memory = Memory("ENGLAND")
    memory.restore({"country": "ENGLAND"})
    assert memory.order_diagnostics == memory.own_adjudications == []
    for i in range(50):
        memory.record_order_diagnostics(f"S{1901 + i}M", [{"code": "missing_order"}])
    assert len(memory.order_diagnostics) == 40
    memory.record_order_diagnostics("S1950M", [])
    assert len(memory.order_diagnostics) == 39
    assert OrderSet().intentional_self_standoffs == []
    assert OrderSet(intentional_self_standoffs=None).intentional_self_standoffs == []
    assert OrderSet(intentional_self_standoffs="spa/sc").intentional_self_standoffs == ["SPA"]


def test_new_evidence_fields_restore_defensively():
    memory = Memory("ENGLAND")
    for invalid in (None, {}, "not a list", [None, {}, {"phase": 123, "source": "public_result"}]):
        memory.restore({"order_diagnostics": invalid, "own_adjudications": invalid})
        assert memory.order_diagnostics == memory.own_adjudications == []
    memory.restore({
        "order_diagnostics": [{"phase": "S1901M", "source": "own_order_diagnostic", "code": "unrecognized_order",
                               "orders": ["untrusted raw output"], "unknown_field": "discard", "acknowledged": "false"},
                              {"phase": "S1901M", "source": "own_order_diagnostic", "code": []}],
        "own_adjudications": [{"phase": "S1901M", "source": "public_result", "orders": None,
                               "results": None, "units_after": [None, "x" * 100]}],
    })
    assert memory.order_diagnostics == [{"phase": "S1901M", "source": "own_order_diagnostic", "code": "unrecognized_order",
                                        "orders": [], "acknowledged": False}]
    assert memory.own_adjudications[0]["results"] == {}
    assert memory.own_adjudications[0]["units_after"] == ["x" * 16]
