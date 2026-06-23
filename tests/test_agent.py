"""P2 Agent 五步单测(异步)：意图延续、下令仅合法、态度更新。假网关免 LLM。"""
import pytest

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS
from diplomind.schemas import AttitudeUpdate, Intent, OrderSet


class FakeGW:
    def __init__(self): self.seen = []
    async def achat(self, messages, schema, tag="", retry=2, temp=None):
        self.seen.append(messages[-1]["content"])
        if schema is Intent: return Intent(goal="扩张", ally="ENGLAND", target="GERMANY", move_turn=2)
        if schema is OrderSet: return OrderSet(orders=["A PAR - BUR", "A PAR - MOON"], reasoning="x")
        if schema is AttitudeUpdate: return AttitudeUpdate(scores={"GERMANY": -60})
        return None


def _ag():
    return Agent("FRANCE", PERSONAS["bully"], FakeGW()), OperationEngine(["ENGLAND", "FRANCE", "GERMANY"])


@pytest.mark.asyncio
async def test_orders_only_legal():
    ag, eng = _ag()
    _, chosen = await ag.a_decide_orders(eng)
    assert "A PAR - BUR" in chosen and "A PAR - MOON" not in chosen     # 非法剔除

@pytest.mark.asyncio
async def test_intent_continuity():
    ag, eng = _ag()
    await ag.a_intent(eng); await ag.a_intent(eng)
    assert ag.mem.intent["goal"] == "扩张"

@pytest.mark.asyncio
async def test_attitude_update():
    ag, eng = _ag()
    await ag.a_update(eng)
    assert ag.mem.relation("GERMANY").trust == -60


def test_stab_cue_when_due():
    ag, eng = _ag()
    ag.mem.intent = {"target": "GERMANY", "move_turn": 1901}
    assert "GERMANY" in ag._stab_cue(eng) and "背刺" in ag._stab_cue(eng)   # 到点提示捅刀
    ag.mem.intent = {"target": "GERMANY", "move_turn": 1905}
    assert ag._stab_cue(eng) == ""                                          # 未到不提示


def test_order_fuzzy_match():
    from diplomind.personalities import PERSONAS
    a = Agent("FRANCE", PERSONAS["bully"], gw=None)
    flat = ["A PAR - BUR", "F BRE - MAO", "A MAR H"]
    assert a._match(["A PAR-BUR", "f bre-mao", "A MAR H"], flat) == ["A PAR - BUR", "F BRE - MAO", "A MAR H"]  # near-miss recovered
    assert a._match(["A PAR - XYZ"], flat) == []   # truly illegal stays dropped
