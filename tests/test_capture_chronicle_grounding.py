"""No paid narration or fabricated betrayal on the adjudication path."""
import pytest

from diplomind.bus import MessageBus
from diplomind.chronicle import generate
from diplomind.config import Config
from diplomind.engine import OperationEngine
from diplomind.session import POWERS, Session


def test_claimed_gal_capture_stays_attributed_beside_real_bounce():
    engine = OperationEngine()
    engine.submit("AUSTRIA", ["A BUD - GAL"])
    engine.submit("RUSSIA", ["A WAR - GAL"])
    engine.process()
    bus = MessageBus()
    bus.post(1, "AUSTRIA", "broadcast", [], "Russia is already in GAL and betrayed us")
    bus.post(1, "AUSTRIA", "private", ["GERMANY"], "PRIVATE_CANARY")
    text = generate(bus, engine.phase(), engine.centers(), adjudication=engine.last_adjudication())
    assert "PRIVATE_CANARY" not in text
    assert "AUSTRIA公开宣称：Russia is already" in text
    assert "不代表已确认" in text
    assert "A WAR: bounce" in text
    assert "RUSSIA裁决后位置：A WAR" in text


@pytest.mark.parametrize("taker_human", [False, True])
def test_agreed_center_handover_is_not_automatically_confirmed_betrayal(taker_human):
    session = Session("ITALY" if taker_human else None, cfg=Config(api="mock"))
    memory = session.ai["AUSTRIA"].mem
    memory.apply_attitude({"ITALY": {"trust": 60, "attitude": "Trusted partner"}})
    records = [
        {"rnd": 1, "sender": "AUSTRIA", "scope": "private", "to": ["ITALY"],
         "text": "I agree to hand TRI to Italy this fall in exchange for support next year."},
        {"rnd": 1, "sender": "ITALY", "scope": "private", "to": ["AUSTRIA"],
         "text": "I accept the agreed TRI handover."},
    ]
    memory.observe_messages("F1901M", records)
    before = {country: set(p.centers) for country, p in session.eng.game.powers.items()}
    session.eng.game.set_centers("AUSTRIA", ["BUD", "VIE"])
    session.eng.game.set_centers("ITALY", ["NAP", "ROM", "VEN", "TRI"])
    session._detect_betrayal(before, "F1901M")
    assert memory.relation("ITALY").trust == 60
    assert not any(action.betray for action in memory.actions)
    assert any("TRI" in action.action and "not assessed" in action.action for action in memory.actions)
    assert all(action.source == "public_result" for action in memory.actions)
    assert not session.ai["FRANCE"].mem.evidence
    session.close()


@pytest.mark.asyncio
async def test_normal_settlement_generates_grounded_chronicle_without_gateway_call():
    session = Session(list(POWERS), cfg=Config(api="mock", rounds=1))
    await session.begin_phase()
    for country in POWERS:
        await session.say(country, "broadcast", [], "", skip=True)
    assert session.mode == "ORDERS"
    before_calls = session.gw.health["calls"]
    for country in POWERS:
        await session.submit_orders(country, [])
    assert session.gw.health["calls"] == before_calls == 0
    assert session.chronicle and "引擎裁决事实" in session.chronicle[-1]
    await session.aclose()
