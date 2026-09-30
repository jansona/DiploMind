"""Capture facts must not fabricate betrayal intent or erase agreed handovers."""
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


def test_ally_capture_records_fact_without_universal_trust_penalty():
    s = _s()
    aus = s.ai["AUSTRIA"].mem; aus.apply_attitude({"ITALY": {"trust": 60, "attitude": "盟友"}})  # 信任意大利
    before = {c: set(s.eng.game.powers[c].centers) for c in POWERS}
    s.eng.game.set_centers("ITALY", "TRI"); s.eng.game.set_centers("AUSTRIA", [])  # 意大利夺奥地利中心
    s._detect_betrayal(before)
    assert any("TRI" in a.action and a.source == "public_result" for a in aus.actions)
    assert not any(a.betray for a in aus.actions)
    assert aus.relation("ITALY").trust == 60


def test_human_capture_has_same_evidence_not_special_trust_penalty():
    """Human and AI captors are assessed from the same evidence policy."""
    s = Session("ITALY", max_year=1903); s.gw = StubGW()   # ITALY = human, not in s.ai
    for a in s.ai.values(): a.gw = s.gw
    aus = s.ai["AUSTRIA"].mem; aus.apply_attitude({"ITALY": {"trust": 60, "attitude": "盟友"}})
    before = {c: set(s.eng.game.powers[c].centers) for c in POWERS}
    s.eng.game.set_centers("ITALY", "TRI"); s.eng.game.set_centers("AUSTRIA", [])
    s._detect_betrayal(before)
    assert any("TRI" in a.action and "not assessed" in a.action for a in aus.actions)
    assert not any(a.betray for a in aus.actions)
    assert aus.relation("ITALY").trust == 60


def test_commitment_expiry():
    m = _s().ai["FRANCE"].mem
    m.add_commitment("GERMANY", "三回合不打", 1, 3)
    for _ in range(3): m.tick()
    assert m.ledger[0].expired
