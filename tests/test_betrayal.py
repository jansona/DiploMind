"""P0 背叛/记仇集成测: 盟友抢中心→记背叛+信任暴跌; 承诺到期失效。"""
import asyncio

from diplomind.schemas import Intent, Message, OrderSet, AttitudeUpdate
from diplomind.session import POWERS, Session


class StubGW:
    concurrency = 3; log = type("L", (), {"stats": staticmethod(lambda: {})})()
    async def achat(self, m, s, **k):
        if s is Intent: return Intent(goal="x")
        if s is AttitudeUpdate: return AttitudeUpdate()
        if s is Message: return Message(content="")
        if s is OrderSet: return OrderSet(orders=[])
        return None


def _s():
    s = Session(None, max_year=1903); s.gw = StubGW()
    for a in s.ai.values(): a.gw = s.gw
    return s


def test_ally_capture_marks_betrayal():
    s = _s()
    aus = s.ai["AUSTRIA"].mem; aus.apply_attitude({"ITALY": {"trust": 60, "attitude": "盟友"}})  # 信任意大利
    before = {c: set(s.eng.game.powers[c].centers) for c in POWERS}
    s.eng.game.set_centers("ITALY", "TRI"); s.eng.game.set_centers("AUSTRIA", [])  # 意大利夺奥地利中心
    s._detect_betrayal(before)
    assert any(a.betray for a in aus.actions)            # 记为背叛
    assert aus.relation("ITALY").trust == -80            # 记仇: 信任暴跌


def test_commitment_expiry():
    m = _s().ai["FRANCE"].mem
    m.add_commitment("GERMANY", "三回合不打", 1, 3)
    for _ in range(3): m.tick()
    assert m.ledger[0].expired
