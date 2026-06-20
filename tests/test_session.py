"""人机会话单测(统一Player接口,单事件循环): 等齐推进/人静默不挡/满轮转下令/下令结算。stub免LLM。"""
import asyncio
import pytest

from diplomind.schemas import Intent, Message, OrderSet, AttitudeUpdate
from diplomind.session import Session


class StubGW:
    concurrency = 3
    log = type("L", (), {"stats": staticmethod(lambda: {})})()
    async def achat(self, m, s, **k): return self._mk(s)
    def chat(self, m, s, **k): return self._mk(s)
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


async def _tick():
    for _ in range(3): await asyncio.sleep(0)         # 放 AI 任务跑完


@pytest.mark.asyncio
async def test_six_ai_one_human():
    s = _sess(); await s.begin_phase(); await _tick()
    assert len(s.ai) == 6 and s.pending() == ["FRANCE"]   # AI齐, 只等人

@pytest.mark.asyncio
async def test_human_send_advances():
    s = _sess(); await s.begin_phase(); await _tick()
    await s.human_say("broadcast", [], "和平"); await _tick()
    assert s.round == 2 and any("和平" in m.text for m in s.bus.msgs)

@pytest.mark.asyncio
async def test_skip_and_full_to_orders():
    s = _sess(); await s.begin_phase()
    for _ in range(5):
        await _tick()
        if s.mode == "NEGO": await s.human_say("broadcast", [], "", skip=True)
    await _tick()
    assert s.mode == "ORDERS" and len(s.legal()) > 0
    res = await s.submit(["A PAR - BUR", "A PAR - MOON"])
    assert res["phase"] != "S1901M" and s.mode == "NEGO"
