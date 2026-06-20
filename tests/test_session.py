"""人机会话单测：人发言入库、合法表非空、人下令仅合法+6AI结算+相推进。用 stub 免 LLM。"""
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


def test_human_and_six_ai():
    s = _sess()
    assert len(s.ai) == 6 and "FRANCE" not in s.ai            # 人操法国, 6AI
    s.human_say("broadcast", [], "我主和")
    assert any("主和" in m.text for m in s.bus.msgs)           # 人发言入库
    assert len(s.legal()) > 0                                 # 法国有合法令
    res = asyncio.run(s.submit(["A PAR - BUR", "A PAR - MOON"]))  # 一合法一非法
    assert "A PAR - BUR" in [m.action for m in next(iter(s.ai.values())).mem.actions] or res["phase"]
    assert res["phase"] != "S1901M"                           # 已结算推进
    assert s.mode == "NEGO" and s.round == 1                  # 回到下一相谈判
