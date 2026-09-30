"""Offline context recall/budget checks, not assertions of model strategy quality."""
import asyncio
import json

import pytest

from diplomind.agent import Agent
from diplomind.context_budget import CONTEXT_BUDGETS, PROMPT_BUDGETS, encoded
from diplomind.engine import OperationEngine
from diplomind.memory import Memory
from diplomind.personalities import PERSONAS
from diplomind.providers.mock import MockProvider, context_from
from diplomind.schemas import OrderSet


class Capture:
    def __init__(self): self.calls = []
    async def achat(self, messages, schema, **kwargs):
        self.calls.append((messages, kwargs))
        return schema()


def make_agent(country="FRANCE"):
    gateway = Capture()
    return Agent(country, PERSONAS["diplomat"], gateway), OperationEngine(), gateway


def private(sender, text, rnd=1, to=None):
    return {"sender": sender, "scope": "private", "to": to or ["FRANCE"], "rnd": rnd, "text": text}


def crowded(agent, eng, count=180):
    records = [private("ENGLAND", "I promise to support A PAR - BUR. OLD_UNRESOLVED_NEEDLE")]
    records.extend({"sender": "ITALY", "scope": "broadcast", "to": [], "rnd": i + 2,
                    "text": ("I will support diplomatic conversations about distant borders. 无关的南部消息。" * 45) + str(i)}
                   for i in range(count))
    records += [private("ENGLAND", "I withdraw my earlier offer. LAST_REVISION_NEEDLE", count + 3),
                private("GERMANY", "England betrayed Turkey, allegedly. ACCUSATION_NEEDLE", count + 3),
                private("RUSSIA", "INVISIBLE_PRIVATE_CANARY", count + 3, ["TURKEY"])]
    agent.observe_messages(eng.phase(), records)
    return records


@pytest.mark.parametrize("stage", ["attitude", "intent", "nego", "order"])
def test_long_cjk_history_has_hard_utf8_budget_and_priority_recall(stage):
    ag, eng, _ = make_agent()
    crowded(ag, eng)
    ag.mem.add_commitment("ENGLAND", "Keep BUR demilitarized. LEDGER_NEEDLE", 1901, None)
    ag.mem.intent = {"ally": "ENGLAND", "target": "GERMANY", "grab": ["BUR"]}
    ctx = ag._context(eng, stage=stage)
    serialized = encoded(ctx)
    assert len(serialized.encode("utf-8")) <= CONTEXT_BUDGETS[stage]
    assert json.loads(serialized) == ctx
    assert "OLD_UNRESOLVED_NEEDLE" in serialized
    assert "LAST_REVISION_NEEDLE" in serialized
    assert "LEDGER_NEEDLE" in serialized
    assert "INVISIBLE_PRIVATE_CANARY" not in serialized
    assert ctx["units"] == eng.game.get_state()["units"]
    assert ctx["centers"] == {p: list(v.centers) for p, v in eng.game.powers.items()}
    assert any(e["kind"] == "reported_claim" and e["verified"] is False for e in ctx["visible_evidence"])
    assert ctx["context_omissions"]["evidence"] > 0
    stats = ag.context_stats[stage]
    assert "NEEDLE" not in json.dumps(stats) and "CANARY" not in json.dumps(stats)
    assert stats["context_bytes"] == len(serialized.encode())


def test_old_offer_remains_unverified_and_original_phase_after_transition_and_restore():
    ag, eng, _ = make_agent()
    crowded(ag, eng)
    restored = Agent("FRANCE", PERSONAS["diplomat"], None)
    restored.mem.restore(ag.mem.snapshot())
    eng.game.set_current_phase("F1902M")
    ctx = restored._context(eng)
    proposal = next(e for e in ctx["visible_evidence"] if "OLD_UNRESOLVED_NEEDLE" in e["text"])
    revision = next(e for e in ctx["visible_evidence"] if "LAST_REVISION_NEEDLE" in e["text"])
    assert proposal["phase"] == revision["phase"] == "S1901M"
    assert proposal["verified"] is False
    assert proposal["candidate"] == {"kind": "proposal_candidate", "status": "unverified_unresolved",
        "acceptance": "not_inferred", "expiry": "not_inferred", "source_id": proposal["id"]}
    assert revision["candidate"]["kind"] == "revision_or_refusal_candidate"
    assert not restored.mem.ledger  # No language heuristic invents an accepted promise.


def test_multi_recipient_scope_survives_save_and_cannot_enter_nonmember_context():
    memory = Memory("FRANCE")
    memory.observe_messages("S1901M", [private("ENGLAND", "I will support you. PRIVATE_GROUP_CANARY", to=["FRANCE", "GERMANY"])])
    record, = memory.evidence
    assert record["participants"] == ["ENGLAND", "FRANCE", "GERMANY"]
    outsider, eng, _ = make_agent("ITALY")
    outsider.mem.restore(memory.snapshot())
    assert not outsider.mem.evidence
    assert "PRIVATE_GROUP_CANARY" not in outsider.perceive(eng)


def test_unstructured_latest_inbox_is_retained_even_if_structured_messages_already_exist():
    ag, eng, _ = make_agent()
    ag.observe_messages(eng.phase(), [private("ENGLAND", "I will support A PAR - BUR.")])
    text = "R1 ENGLAND·私聊@你: I will support A PAR - BUR.\nR2 ENGLAND·私聊@你: FINAL_UNSYNCED_NEEDLE: cancel that offer."
    ctx = ag._context(eng, inbox=text)
    assert "FINAL_UNSYNCED_NEEDLE" in ctx["diplomacy"]
    assert "I will support" not in ctx["diplomacy"]
    assert ctx["diplomacy_source"].endswith("unverified")


def test_transcript_is_deduplicated_and_order_ids_are_full_stable_once():
    ag, eng, _ = make_agent()
    text = "I will support A PAR - BUR. EXACT_ONCE_NEEDLE"
    ag.observe_messages(eng.phase(), [private("ENGLAND", text)])
    ag.observe_diplomacy(eng.phase(), "R1 ENGLAND·私聊@你: " + text)
    flat = ag._legal_flat(eng)
    prompt = ag._order_prompt(eng, flat)
    ctx = context_from([{"role": "user", "content": prompt}])
    assert prompt.count("EXACT_ONCE_NEEDLE") == 1
    assert ctx["legal"] == flat
    assert all(prompt.count('"' + order + '"') == 1 for order in flat)
    assert ag._resolve([str(i) for i in range(len(flat))], flat)  # Same IDs remain resolvable.
    assert ag._context(eng, stage="attitude")["legal"] == []
    assert len(ag._context(eng, stage="intent")["legal"]) < len(flat)


@pytest.mark.asyncio
async def test_all_stages_keep_profile_grounding_and_bounce_with_no_additional_calls():
    ag, eng, gw = make_agent("ENGLAND")
    ag.mem.record_order_diagnostics(eng.phase(), [{"code": "own_destination_collision", "destination": "NTH", "acknowledged": False}])
    eng.submit("ENGLAND", ["F EDI - NTH", "F LON - NTH", "A LVP H"])
    eng.process()
    await ag.a_update(eng)
    await ag.a_intent(eng)
    await ag.a_negotiate(eng, "")
    await ag.a_decide_orders(eng)
    assert len(gw.calls) == 4
    for messages, options in gw.calls:
        stage = options["tag"].split(":")[-1]
        ctx = context_from(messages)
        assert ctx["behavioral_profile"] == ag.mem.profile
        assert ctx["recent_own_adjudications"][-1]["results"]["F EDI"] == ["bounce"]
        assert ctx["own_order_diagnostics"][0]["acknowledged"] is False
        assert "F NTH" not in ctx["units"]["ENGLAND"]
        assert messages[0] == ag.sys
        assert "candidate" in ag.sys["content"] and "acceptance" in ag.sys["content"]
        assert len("\n".join(m["content"] for m in messages).encode()) <= PROMPT_BUDGETS[stage]
        assert ag.context_stats[stage]["prompt_bytes"] <= PROMPT_BUDGETS[stage]


def test_flooded_commitments_and_candidate_drops_are_explicit_not_silently_resolved():
    ag, eng, _ = make_agent()
    for i in range(180):
        ag.mem.add_commitment("ENGLAND", f"Commitment {i}: " + "Keep BUR demilitarized " * 100, 1901, None)
    ctx = ag._context(eng)
    assert ctx["context_omissions"]["commitments"] > 0
    assert len(encoded(ctx).encode()) <= CONTEXT_BUDGETS["order"]
    assert len(ag.mem.active_commitments()) == 180  # Retrieval never deletes/resolves memory.


def test_fake_statement_does_not_create_commitment_and_unknown_acceptance_is_explicit():
    ag, eng, _ = make_agent()
    records = [private("ENGLAND", "People keep saying promise and support, but no agreement exists."),
               private("GERMANY", "If England says I will support France, that does not mean I agree.", rnd=2)]
    ag.observe_messages(eng.phase(), records)
    assert not any(e.get("candidate") for e in ag.mem.evidence)
    assert not ag.mem.ledger


def test_trust_assessment_retains_evaluated_evidence_provenance():
    memory = Memory("FRANCE")
    memory.apply_attitude({"ENGLAND": {"trust": 30, "attitude": "Possible cooperation"}}, "S1901M", ["evidence-id"])
    restored = Memory("FRANCE")
    restored.restore(memory.snapshot())
    assert restored.relation("ENGLAND").assessment_phase == "S1901M"
    assert restored.relation("ENGLAND").evaluated_evidence_ids == ["evidence-id"]


@pytest.mark.asyncio
async def test_budgeting_does_not_swallow_gateway_cancellation():
    class Cancel:
        async def achat(self, *args, **kwargs): raise asyncio.CancelledError()
    ag = Agent("FRANCE", PERSONAS["diplomat"], Cancel())
    with pytest.raises(asyncio.CancelledError): await ag.a_decide_orders(OperationEngine())


def test_mock_remains_deterministic_with_structured_context():
    ag, eng, _ = make_agent()
    crowded(ag, eng, 20)
    messages = [ag.sys, {"role": "user", "content": ag._order_prompt(eng, ag._legal_flat(eng))}]
    first = MockProvider().complete(messages, OrderSet)
    assert first == MockProvider().complete(messages, OrderSet)
    assert first["orders"] and all(o in ag._legal_flat(eng) for o in first["orders"])


def test_replayed_phase_does_not_make_evicted_old_filler_newest():
    ag, eng, _ = make_agent()
    records = crowded(ag, eng, 180)
    first = ag._context(eng)
    ag.observe_messages(eng.phase(), records)
    second = ag._context(eng)
    assert first["visible_evidence"] == second["visible_evidence"]
    assert max(e["round"] for e in ag.mem.evidence) == 183
    assert "LAST_REVISION_NEEDLE" in encoded(second)


def test_large_legal_table_is_losslessly_compacted_without_holds_or_missing_actions():
    from diplomind.context_budget import legal_from_context
    ag, eng, _ = make_agent()
    eng.game.clear_units()
    eng.game.set_units("FRANCE", ["F " + loc for loc in "MAO NAO IRI ENG NTH NWG BAR BAL BOT SKA HEL WES GOL TYS ION ADR AEG".split()])
    eng.game.set_units("GERMANY", ["A " + loc for loc in "BRE PIC BEL HOL DEN KIE BER PRU LVN FIN SWE NWY GAS MAR TUS ROM APU".split()])
    flat = ag._legal_flat(eng)
    assert len(flat) > 2000
    assert len(encoded(flat).encode()) > CONTEXT_BUDGETS["order"]
    ctx = ag._context(eng)
    assert ctx["legal_encoding"] == "prefix_groups"
    assert legal_from_context(ctx) == flat
    assert len(encoded(ctx).encode()) <= CONTEXT_BUDGETS["order"]
    assert ag.context_stats["order"]["legal_count"] == ag.context_stats["order"]["legal_in_context"] == len(flat)
    messages = [ag.sys, {"role": "user", "content": ag._order_prompt(eng, flat)}]
    out = MockProvider().complete(messages, OrderSet)
    assert out["orders"] and all(o in flat for o in out["orders"])


@pytest.mark.parametrize("targets", ["FRANCE", [], ["FRANCE", "ATLANTIS"], ["FRANCE", None]])
def test_invalid_private_envelopes_fail_closed_before_memory(targets):
    ag, eng, _ = make_agent()
    ag.observe_messages(eng.phase(), [{"sender": "ENGLAND", "scope": "private", "to": targets,
                                     "rnd": 1, "text": "I will support you. INVALID_ENVELOPE_CANARY"}])
    assert not ag.mem.evidence


def test_large_legal_table_and_full_history_trim_optional_memory_before_fallback():
    from diplomind.context_budget import legal_from_context
    ag, eng, _ = make_agent()
    eng.game.clear_units()
    fleets = ["F " + loc for loc in "MAO NAO IRI ENG NTH NWG BAR BAL BOT SKA HEL WES GOL TYS ION ADR AEG".split()]
    eng.game.set_units("FRANCE", fleets)
    eng.game.set_units("GERMANY", ["A " + loc for loc in "BRE PIC BEL HOL DEN KIE BER PRU LVN FIN SWE NWY GAS MAR TUS ROM APU".split()])
    ag.mem.own_adjudications = [{"phase": f"S{1895+i}M", "source": "public_result",
        "orders": [u+" H" for u in fleets], "results": {u: (["bounce"] if i == 4 and u == "F MAO" else []) for u in fleets},
        "units_after": list(fleets)} for i in range(6)]
    ag.mem.order_diagnostics = [{"phase": f"S{1880+i}M", "source": "own_order_diagnostic", "code": "missing_order",
        "location": "MAO", "orders": [], "acknowledged": False,
        "message": "No selected order: engine defaults to hold."} for i in range(39)]
    ag.mem.order_diagnostics += [{"phase": "S1900M", "source": "own_order_diagnostic", "code": "own_destination_collision",
        "destination": "SPA", "orders": ["F MAO - SPA/NC", "F WES - SPA/SC"], "acknowledged": False}]
    ag.observe_messages(eng.phase(), [private("ENGLAND", "I will support F MAO. FINAL_LARGE_NEEDLE")])
    ctx = ag._context(eng)
    assert legal_from_context(ctx) == ag._legal_flat(eng)
    assert len(encoded(ctx).encode()) <= CONTEXT_BUDGETS["order"]
    assert any(a["results"].get("F MAO") == ["bounce"] for a in ctx["recent_own_adjudications"])
    assert ctx["recent_own_adjudications"][-1]["phase"] == "S1900M"
    assert any(w["code"] == "own_destination_collision" for w in ctx["own_order_diagnostics"])
    assert "FINAL_LARGE_NEEDLE" in encoded(ctx)
    assert "shrink_optional_history_before_mandatory_facts" in ag.context_stats["order"]["reasons"]
    assert ctx["context_omissions"].get("own_adjudications", 0) + ctx["context_omissions"].get("own_diagnostics", 0) > 0
