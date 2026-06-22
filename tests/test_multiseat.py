"""多座位: 两个人类同局, 谁没发都不推进; 下令需全员交齐才结算。stub 免 LLM。"""
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
    s = Session(["FRANCE", "GERMANY"]); s.gw = StubGW()
    for a in s.ai.values(): a.gw = s.gw
    return s


async def _tick():
    for _ in range(3): await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_two_humans_both_must_act():
    s = _sess(); await s.begin_phase(); await _tick()
    assert len(s.ai) == 5 and set(s.pending()) == {"FRANCE", "GERMANY"}   # 5 AI, wait both humans
    await s.say("FRANCE", "broadcast", [], "", skip=True); await _tick()
    assert s.pending() == ["GERMANY"] and s.round == 1                    # FR done, still wait DE
    await s.say("GERMANY", "broadcast", [], "", skip=True); await _tick()
    assert s.round == 2                                                   # both done -> advance


@pytest.mark.asyncio
async def test_orders_need_all_humans():
    s = _sess(); await s.begin_phase()
    for _ in range(6):
        await _tick()
        if s.mode == "NEGO":
            for p in ("FRANCE", "GERMANY"):
                if s.your_turn(p): await s.say(p, "broadcast", [], "", skip=True)
    await _tick(); assert s.mode == "ORDERS"
    r = await s.submit_orders("FRANCE", []); assert r.get("waiting") == ["GERMANY"]   # one in, wait other
    assert s.mode == "ORDERS"
    r = await s.submit_orders("GERMANY", []); assert r.get("phase") and s.mode == "NEGO"  # both in -> settle


@pytest.mark.asyncio
async def test_per_seat_state_view():
    s = _sess(); await s.begin_phase(); await _tick()
    assert s.state("FRANCE")["your_turn"] and s.state("GERMANY")["your_turn"]
    await s.say("FRANCE", "broadcast", [], "", skip=True); await _tick()
    assert not s.state("FRANCE")["your_turn"] and s.state("GERMANY")["your_turn"]   # seats independent
