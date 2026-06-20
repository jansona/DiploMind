"""P2 Agent 五步单测：意图延续、下令仅合法、态度更新。用假网关免 LLM。"""
from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS
from diplomind.schemas import AttitudeUpdate, Intent, OrderSet


class FakeGW:
    """按 schema 返回固定对象，记录收到的 prompt。"""
    def __init__(self): self.seen = []
    def chat(self, messages, schema, tag="", retry=2, temp=None):
        self.seen.append(messages[-1]["content"])
        if schema is Intent:
            return Intent(goal="扩张", ally="ENGLAND", target="GERMANY", move_turn=2)
        if schema is OrderSet:
            return OrderSet(orders=["A PAR - BUR", "A PAR - MOON"], reasoning="x")  # 一合法一非法
        if schema is AttitudeUpdate:
            return AttitudeUpdate(scores={"GERMANY": -60})
        return None


def _ag():
    return Agent("FRANCE", PERSONAS["bully"], FakeGW()), OperationEngine(["ENGLAND", "FRANCE", "GERMANY"])


def test_orders_only_legal():
    ag, eng = _ag()
    _, chosen = ag.decide_orders(eng)
    assert "A PAR - BUR" in chosen and "A PAR - MOON" not in chosen   # 非法剔除

def test_intent_continuity():
    ag, eng = _ag()
    ag.intent(eng)
    ag.intent(eng)                                # 第二次应带上回合意图
    assert "上回合意图" in ag.gw.seen[-1]

def test_attitude_update():
    ag, eng = _ag()
    ag.update(eng)
    assert ag.mem.relation("GERMANY").trust == -60
