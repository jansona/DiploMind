"""人机会话单测：对等轮次(人发→AI齐才进轮)、人静默不挡、满轮转下令、人下令仅合法+6AI结算。stub 免 LLM。"""
import asyncio

from diplomind.schemas import Intent, Message, OrderSet, AttitudeUpdate
from diplomind.session import Session


class StubGW:
    concurrency = 3
    log = type("L", (), {"stats": staticmethod(lambda: {})})()
    def chat(self, m, s, **k): return self._mk(s)
    async def achat(self, m, s, **k): return self._mk(s)
    def _mk(self, s):
        if s is Intent: return Intent(goal="扩张")
        if s is AttitudeUpdate: return AttitudeUpdate()
        if s is Message: return Message(content="结盟?")
        if s is OrderSet: return OrderSet(orders=[])
        return None


def _sess():
    s = Session("FRANCE"); s.gw = StubGW()
    for a in s.ai.values(): a.gw = s.gw
    return s


def test_peer_round_advances_when_all_sent():
    s = _sess(); assert len(s.ai) == 6
    asyncio.run(s.begin_phase())
    assert s.round == 1 and s.human in s.pending()       # AI已生成,等人
    asyncio.run(s.human_say("broadcast", [], "我主和"))    # 人发→投递→进2轮
    assert s.round == 2 and any("主和" in m.text for m in s.bus.msgs)

def test_human_skip_does_not_block():
    s = _sess(); asyncio.run(s.begin_phase())
    asyncio.run(s.human_say("broadcast", [], "", skip=True))
    assert s.round == 2                                   # 人跳过仍推进

def test_full_negotiation_then_orders():
    s = _sess(); asyncio.run(s.begin_phase())
    for _ in range(5):
        if s.mode == "NEGO": asyncio.run(s.human_say("broadcast", [], "talk"))
    assert s.mode == "ORDERS" and len(s.legal()) > 0
    res = asyncio.run(s.submit(["A PAR - BUR", "A PAR - MOON"]))
    assert res["phase"] != "S1901M" and s.mode == "NEGO"
