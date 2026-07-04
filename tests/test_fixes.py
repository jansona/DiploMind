"""评审修复回归: 终局停局/ORDERS踢人/编年史增量/空收件人私聊/网关关闭/存档回座。stub 免 LLM。"""
import asyncio
import pytest

from diplomind.bus import MessageBus
from diplomind.chronicle import generate
from diplomind.rooms import RoomManager
from diplomind.schemas import AttitudeUpdate, Intent, Message, OrderSet
from diplomind.session import Session


class StubGW:
    concurrency = 3
    log = type("L", (), {"stats": staticmethod(lambda: {})})()
    def close(self): pass
    async def achat(self, m, s, **k): return self._mk(s)
    def chat(self, m, s, **k): return self._mk(s)
    def _mk(self, s):
        if s is Intent: return Intent(goal="扩张")
        if s is AttitudeUpdate: return AttitudeUpdate()
        if s is Message: return Message(content="结盟?")
        if s is OrderSet: return OrderSet(orders=[])
        return None


def _sess(humans, **kw):
    s = Session(humans, **kw); s.gw = StubGW()
    for a in s.ai.values(): a.gw = s.gw
    return s


async def _tick(n=3):
    for _ in range(n): await asyncio.sleep(0)


async def _to_orders(s):
    for _ in range(s.rounds + 1):
        await _tick()
        if s.mode == "NEGO":
            for p in list(s.humans):
                if s.your_turn(p): await s.say(p, "broadcast", [], "", skip=True)
    await _tick()
    assert s.mode == "ORDERS"


# --- fix: private w/o recipient must not become a black hole ---
def test_private_no_recipient_downgrades_to_broadcast():
    m = Message(type="private", recipient=[], content="hello")
    assert m.type == "broadcast"
    m = Message(type="private", recipient=["FRANCE"], content="hello")
    assert m.type == "private"                       # real privates untouched


# --- fix: fallback chronicle only covers msgs since the last entry ---
def test_chronicle_generate_since_no_repeat():
    b = MessageBus()
    b.post(1, "FRANCE", "broadcast", [], "第一相发言", "S1901M")
    first = generate(b, "F1901M", {"FRANCE": 3}, since=0)
    assert "第一相发言" in first
    idx = len(b.msgs)
    b.post(1, "GERMANY", "broadcast", [], "第二相发言", "F1901M")
    second = generate(b, "S1902M", {"FRANCE": 3}, since=idx)
    assert "第二相发言" in second and "第一相发言" not in second   # 旧广播不再重复入史


# --- fix: kick during ORDERS must not re-commit stale round / drop orders / stall ---
@pytest.mark.asyncio
async def test_kick_last_holdout_during_orders_settles():
    s = _sess(["FRANCE", "GERMANY"]); await s.begin_phase()
    await _to_orders(s)
    n_msgs = len(s.bus.msgs)
    await s.submit_orders("FRANCE", [])              # FRANCE in, GERMANY is the holdout
    s.aiify("GERMANY")                               # kicked -> all remaining humans already submitted
    await _tick(20)
    assert s.eng.phase() != "S1901M" and s.mode == "NEGO"        # settled + rolled into next phase, no stall
    assert all(m.rnd <= s.rounds for m in s.bus.msgs[:n_msgs])   # no stale round re-post


@pytest.mark.asyncio
async def test_kick_during_orders_waits_other_humans():
    s = _sess(["FRANCE", "GERMANY", "ITALY"]); await s.begin_phase()
    await _to_orders(s)
    await s.submit_orders("FRANCE", [])
    s.aiify("GERMANY"); await _tick(10)
    assert s.mode == "ORDERS" and s.eng.phase() == "S1901M"      # ITALY still owes orders: no premature settle
    r = await s.submit_orders("ITALY", [])
    assert r.get("phase")                                        # last human in -> settle as usual


# --- fix: decided game must not start another negotiation round ---
@pytest.mark.asyncio
async def test_no_new_round_after_end():
    s = _sess(["FRANCE"], max_year=1901)             # year-cap ruling hits after the first settle
    await s.begin_phase(); await _to_orders(s)
    res = await s.submit_orders("FRANCE", [])         # last human in -> settle
    assert res.get("end") and s.state("FRANCE")["end"]           # decided; web gate skips begin_phase on end
    s._done = {}                                      # emulate idle: nothing must revive the round on its own
    await _tick(10)
    assert s.pending() == list(s.players)             # no _start_round ran: nobody drafted a new round


# --- fix: gc reaps decided games, closes gateway clients; never live games ---
def test_gc_reaps_finished_and_closes_gateway():
    m = RoomManager()
    a = m.create("live", "x", "FRANCE"); a.start(); a.active = 0
    b = m.create("done", "y", "FRANCE"); b.start(); b.active = 0
    b.session.max_year = 1901                        # 1901 >= cap: ruling reached
    gw = b.session.gw
    m.gc()
    assert a.code in m.rooms                          # live game survives even when stale
    assert b.code not in m.rooms and gw.sync.is_closed   # decided + idle reaped, httpx released


# --- fix: loaded multi-human save: seats reclaimable by power ---
def test_claim_unclaimed_seat_midgame_only():
    m = RoomManager(); r = m.create("t", "Al", "FRANCE"); r.start()
    r.seats["GERMANY"] = {"name": "GERMANY", "token": "", "kind": "human"}   # loaded, unclaimed
    assert r.claim("GERMANY", "Bo", "tok2")                    # reclaim by power works mid-game
    assert not r.claim("GERMANY", "Eve", "tok3")               # now taken
    assert not r.claim("ITALY", "Eve", "tok3")                 # AI seat not grabbable mid-game
    assert not r.claim("FRANCE", "Eve", "tok3")                # owner's live seat protected


def test_load_multihuman_rejoin(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from diplomind.web import app
    monkeypatch.setattr(Session, "SAVES", tmp_path)
    with TestClient(app) as c:
        d = c.post("/api/room/create", json={"power": "FRANCE"}).json()
        c.post("/api/room/join", json={"code": d["code"], "power": "GERMANY", "name": "Bo"})
        c.post("/api/room/start", json={"token": d["token"]})
        c.post("/api/save", params={"name": "mh", "token": d["token"]})
        nd = c.post("/api/load", params={"name": "mh"}).json()
        assert nd["seat"] == "FRANCE"                          # loader takes primary seat only
        j = c.post("/api/room/join", json={"code": nd["code"], "power": "GERMANY", "name": "Bo"}).json()
        assert j["seat"] == "GERMANY"                          # second player reclaims own power
        s = c.get("/api/state", params={"token": j["token"]}).json()
        assert s["human"] == "GERMANY" and s["mode"] != "MENU"
        e = c.post("/api/room/join", json={"code": nd["code"], "power": "GERMANY", "name": "Eve"}).json()
        assert e["seat"] is None                               # claimed seat not stealable
