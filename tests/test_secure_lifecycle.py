"""Deterministic multiplayer security, persistence and lifecycle regression tests."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from diplomind.config import Config
from diplomind.engine import OperationEngine
from diplomind.rooms import RoomManager
from diplomind.schemas import Message
from diplomind.session import POWERS, Session
import diplomind.web as web


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "RM", RoomManager())
    with TestClient(web.app) as client:
        yield client


def create(client, power="FRANCE", **kw):
    response = client.post("/api/room/create", json={"power": power, **kw})
    assert response.status_code == 200
    return response.json()


def join(client, room, power=None):
    return client.post("/api/room/join", json={"code": room["code"], "power": power}).json()


def state(client, player):
    return client.get("/api/state", params={"token": player["token"]}).json()


def test_spectator_never_inherits_primary_private_state(client):
    owner = create(client); observer = join(client, owner)
    assert client.post("/api/room/start", json={"token": owner["token"]}).status_code == 200
    session = web.RM.rooms[owner["code"]].session
    session.bus.post(1, "GERMANY", "private", ["FRANCE"], "secret attack", session.eng.phase())
    session._hmsgs["FRANCE"] = [Message(content="draft secret")]
    session._horders["FRANCE"] = ["A PAR - BUR"]
    session.mode = "ORDERS"
    own = state(client, owner); view = state(client, observer)
    assert any("secret attack" in str(v) for v in own["channels"].values())
    assert "secret attack" not in json.dumps(view)
    assert "draft secret" not in json.dumps(view)
    assert view["human"] is None and view["legal"] == [] and not view["your_turn"]
    assert view["submitted_orders"] == [] and not view["order_submitted"]
    assert session.state()["human"] == "FRANCE"  # explicit local convenience still works
    assert session.state(None)["human"] is None


def test_legacy_svg_never_renders_sealed_orders_during_settlement(client, monkeypatch):
    owner = create(client)
    observer = join(client, owner)
    client.post("/api/room/start", json={"token": owner["token"]})
    session = web.RM.rooms[owner["code"]].session
    session.eng.submit("FRANCE", ["A PAR - BUR"])
    calls = []
    def renderer(self, **kwargs):
        calls.append(kwargs)
        return "<svg><text>PUBLIC BOARD</text></svg>" if kwargs.get("incl_orders") is False else "<svg>SEALED ORDERS</svg>"
    monkeypatch.setattr(type(session.eng.game), "render", renderer)
    for identity in (owner, observer):
        response = client.get("/api/map", params={"token": identity["token"]})
        assert response.status_code == 200
        assert "SEALED ORDERS" not in response.text
    assert calls == [{"incl_orders": False}, {"incl_orders": False}]


def test_browser_cannot_override_server_provider_or_read_key(client, monkeypatch):
    monkeypatch.setenv("DIPLOMIND_API_KEY", "synthetic-secret-not-for-browser")
    response = client.post("/api/room/create", json={"power": "FRANCE", "api": "openai",
        "base_url": "https://untrusted.invalid/v1", "api_key": "client-supplied-key", "cli_enabled": True})
    assert response.status_code == 422
    owner = create(client)
    client.post("/api/room/start", json={"token": owner["token"]})
    assert web.RM.rooms[owner["code"]].session.gw.api == "mock"
    for path in ("/api/providers", "/api/rooms", "/api/menu", "/api/state"):
        response = client.get(path, params={"token": owner["token"]} if path == "/api/state" else {})
        assert "synthetic-secret-not-for-browser" not in response.text
        assert "client-supplied-key" not in response.text and "untrusted.invalid" not in response.text


def test_all_action_routes_require_valid_identity(client):
    owner = create(client); seat = join(client, owner, "GERMANY"); observer = join(client, owner)
    turn = "missing"
    for path, body in [
        ("/api/room/start", {}), ("/api/room/pause", {}), ("/api/room/end", {}),
        ("/api/room/secs", {"secs": 1}), ("/api/room/transfer", {"power": "GERMANY"}),
        ("/api/room/kick", {"power": "GERMANY"}),
        ("/api/say", {"turn_id": turn, "content": "x"}),
        ("/api/orders", {"turn_id": turn}), ("/api/open", {"recipient": ["FRANCE"]}),
        ("/api/orders/cancel", {"turn_id": turn}),
    ]:
        assert client.post(path, json={"token": "invalid", **body}).status_code == 401, path
    for path in ("/api/save", "/api/load"):
        assert client.post(path).status_code == 401
        assert client.post(path, params={"token": seat["token"]}).status_code == 403
    for path in ("/api/room/start", "/api/room/pause", "/api/room/end"):
        assert client.post(path, json={"token": seat["token"]}).status_code == 403
    for path in ("/api/say", "/api/orders", "/api/open"):
        assert client.post(path, json={"token": observer["token"], "turn_id": turn}).status_code == 403
    assert client.get("/api/stream/WRNG", params={"token": owner["token"]}).status_code == 403


def test_start_is_once_and_tokens_have_one_seat(client):
    owner = create(client)
    assert client.post("/api/room/join", json={"code": owner["code"], "token": owner["token"], "power": "GERMANY"}).status_code == 409
    assert client.post("/api/room/create", json={"power": "ATLANTIS"}).status_code == 422
    assert client.post("/api/room/start", json={"token": owner["token"]}).status_code == 200
    session = web.RM.rooms[owner["code"]].session
    assert client.post("/api/room/start", json={"token": owner["token"]}).status_code == 409
    assert web.RM.rooms[owner["code"]].session is session
    assert client.post("/api/room/join", json={"code": owner["code"], "power": "FRANCE"}).status_code == 409


def test_scoped_saves_no_public_names_or_cross_room_restore(client):
    first = create(client); second = create(client, "ITALY")
    for player in (first, second): client.post("/api/room/start", json={"token": player["token"]})
    assert client.post("/api/save", params={"token": first["token"], "name": "private-name"}).status_code == 200
    assert client.get("/api/menu").json()["saves"] == []
    assert client.get("/api/saves", params={"token": first["token"]}).json()["saves"] == ["private-name"]
    assert client.get("/api/saves", params={"token": second["token"]}).json()["saves"] == []
    assert client.post("/api/load", params={"token": second["token"], "name": "private-name"}).status_code == 404
    assert client.post("/api/load", params={"token": first["token"], "name": "private-name"}).json()["code"] == first["code"]
    assert state(client, first)["status"] == "paused"


def test_seat_credentials_and_pending_orders_survive_restart(client, monkeypatch):
    owner = create(client); germany = join(client, owner, "GERMANY")
    client.post("/api/room/start", json={"token": owner["token"]})
    room = web.RM.rooms[owner["code"]]; room.session.mode = "ORDERS"
    room.session._horders["FRANCE"] = ["A PAR - BUR"]
    room.session.ai["ITALY"].mem.intent = {"goal": "keep promise"}
    web.RM.checkpoint(room); room.session.close()
    monkeypatch.setattr(web, "RM", RoomManager())
    view = state(client, owner)
    assert view["human"] == "FRANCE" and view["status"] == "paused"
    assert view["submitted_orders"] == ["A PAR - BUR"] and view["order_submitted"]
    other = state(client, germany)
    assert other["human"] == "GERMANY" and other["submitted_orders"] == []
    restored = web.RM.rooms[owner["code"]]
    assert restored.session.ai["ITALY"].mem.intent == {"goal": "keep promise"}
    assert client.post("/api/room/join", json={"code": owner["code"], "power": "GERMANY"}).status_code == 409
    assert client.post("/api/room/join", json={"code": owner["code"], "power": "GERMANY", "token": germany["token"]}).json()["token"] == germany["token"]


def test_pause_requires_started_room_and_preserves_timer(client):
    owner = create(client)
    assert client.post("/api/room/pause", json={"token": owner["token"]}).status_code == 409
    client.post("/api/room/start", json={"token": owner["token"]})
    room = web.RM.rooms[owner["code"]]; room.deadline = time.time() + 47
    assert client.post("/api/room/pause", json={"token": owner["token"]}).json()["status"] == "paused"
    assert room.deadline is None and 45 <= room.remaining <= 47
    assert client.post("/api/say", json={"token": owner["token"], "turn_id": room.session.turn_id, "skip": True}).status_code == 409
    assert client.post("/api/room/pause", json={"token": owner["token"]}).json()["status"] == "playing"
    assert 45 <= room.deadline - time.time() <= 47


@pytest.mark.asyncio
async def test_stale_and_duplicate_actions_never_submit_twice():
    session = Session(POWERS, cfg=Config(api="mock"))
    turn = session.turn_id
    result = await session.say("FRANCE", "broadcast", [], "hello", turn_id=turn, request_id="one")
    assert result["ok"]
    duplicate = await session.say("FRANCE", "broadcast", [], "hello", turn_id=turn, request_id="one")
    assert duplicate["duplicate"] and len(session._hmsgs["FRANCE"]) == 1
    session.round += 1
    assert (await session.say("FRANCE", "broadcast", [], "late", turn_id=turn))["status"] == 409
    session.mode = "ORDERS"
    current = session.turn_id
    assert (await session.submit_orders("FRANCE", ["A PAR - BUR"], current))["ok"]
    assert (await session.submit_orders("FRANCE", ["A PAR H"], current))["status"] == 409
    assert session.cancel_orders("FRANCE", current)["ok"]
    assert (await session.submit_orders("FRANCE", ["A PAR - MOON"], current))["status"] == 422
    assert (await session.submit_orders("FRANCE", ["A PAR H", "A PAR - BUR"], current))["status"] == 422
    assert "FRANCE" not in session._horders
    await session.aclose()


@pytest.mark.asyncio
async def test_checkpoint_preserves_partial_negotiation_and_orders():
    session = Session(POWERS, cfg=Config(api="mock"))
    await session.say("FRANCE", "private", ["GERMANY"], "private draft")
    await session.say("GERMANY", "broadcast", [], "", skip=True)
    snapshot = session.to_dict(); restored = Session.from_dict(snapshot)
    await restored.begin_phase()
    assert restored.state("FRANCE")["staged_msgs"] == ["private draft"]
    assert restored.state("GERMANY")["human_done"]
    assert restored.state(None)["staged_msgs"] == []
    assert restored.turn_id != session.turn_id  # rollback/restart invalidates stale browser actions
    await session.aclose(); await restored.aclose()


@pytest.mark.asyncio
async def test_pause_blocks_background_advancement_and_close_cancels():
    session = Session(["FRANCE"], cfg=Config(api="mock", rounds=1))
    session.pause(); await session.begin_phase()
    for _ in range(5): await asyncio.sleep(0)
    assert session._done == {} and session.round == 1
    session.resume()
    await asyncio.wait_for(asyncio.gather(*list(session._tasks)), timeout=2)
    assert len(session._done) == 6
    await session.aclose()
    assert not session._tasks and session.gw.sync.is_closed and session.gw.aclient.is_closed


@pytest.mark.asyncio
async def test_final_round_transcript_visible_to_recipient_only():
    session = Session(["FRANCE"], cfg=Config(api="mock", rounds=1))
    await session.begin_phase()
    for _ in range(10): await asyncio.sleep(0)
    await session.say("FRANCE", "private", ["GERMANY"], "FINAL PRIVATE OFFER")
    await session.say("FRANCE", "broadcast", [], "FINAL PUBLIC OFFER")
    await session.say("FRANCE", "broadcast", [], "", skip=True)
    for _ in range(10): await asyncio.sleep(0)
    assert session.mode == "ORDERS"
    assert "FINAL PRIVATE OFFER" in session.ai["GERMANY"].mem.diplomacy
    assert "FINAL PRIVATE OFFER" not in session.ai["ITALY"].mem.diplomacy
    assert "FINAL PUBLIC OFFER" in session.ai["ITALY"].mem.diplomacy
    assert session._ai_orders
    restored = Session.from_dict(session.to_dict())
    assert restored._ai_orders == session._ai_orders
    await session.aclose(); await restored.aclose()


def test_classic_cap_completes_full_year_without_false_solo():
    engine = OperationEngine()
    assert engine.check_end(max_year=1901) is None
    engine.auto_resolve(); assert engine.process() == "F1901M"
    assert engine.check_end(max_year=1901) is None
    engine.auto_resolve(); engine.process()
    result = engine.check_end(max_year=1901)
    assert result["draw"] and len(result["survivors"]) == 7 and "winner" not in result
    assert OperationEngine().check_end() is None


def test_gc_revokes_all_room_tokens():
    manager = RoomManager(); room = manager.create("x", "a", "FRANCE")
    _, observer = manager.join(room.code, None, "watcher", None)
    owner = room.owner; manager.end(room); manager.gc()
    assert owner not in manager.tokens and observer not in manager.tokens
    assert manager.recover(owner) is None and room.code not in manager.rooms


@pytest.mark.asyncio
async def test_client_disconnect_does_not_cancel_adjudication():
    session = Session(["FRANCE"], cfg=Config(api="mock"))
    session.mode = "ORDERS"
    pending_ai = asyncio.get_running_loop().create_future()
    session._ai_task = pending_ai; session._ai_squad = []
    request = asyncio.create_task(session.submit_orders("FRANCE", ["A PAR H"], session.turn_id))
    for _ in range(5): await asyncio.sleep(0)
    assert session._settling
    request.cancel()
    with pytest.raises(asyncio.CancelledError): await request
    assert not pending_ai.cancelled()
    pending_ai.set_result([])
    await asyncio.wait_for(session._settlement_task, timeout=2)
    assert session.eng.phase() != "S1901M" and session.mode == "NEGO"
    await session.aclose()


def test_room_snapshot_is_owner_private_file(client):
    owner = create(client)
    room = web.RM.rooms[owner["code"]]
    snapshot = web.RM._directory(room) / "resume.json"
    assert snapshot.stat().st_mode & 0o077 == 0
    assert snapshot.parent.stat().st_mode & 0o077 == 0
    assert owner["token"] not in json.dumps(client.get("/api/rooms").json())


def test_deterministic_build_fallback_obeys_engine_count():
    engine = OperationEngine()
    engine.game.set_current_phase("W1901A")
    engine.game.set_units("FRANCE", ["A PAR"], reset=True)
    engine._possible = None
    count = engine.game.get_state()["builds"]["FRANCE"]["count"]
    assert count == 2
    engine.auto_resolve()
    orders = engine.game.get_orders("FRANCE")
    assert len(orders) == 2 and all(order.endswith(" B") for order in orders)
    assert len({order.split()[1].split("/")[0] for order in orders}) == 2


def test_explicit_pause_is_idempotent(client):
    owner = create(client)
    client.post("/api/room/start", json={"token": owner["token"]})
    for desired in ("paused", "paused", "playing", "playing"):
        assert client.post("/api/room/pause", json={"token": owner["token"], "status": desired}).json()["status"] == desired


@pytest.mark.asyncio
async def test_new_phase_starts_at_round_one_without_replaying_final_messages():
    session = Session(["FRANCE"], cfg=Config(api="mock", rounds=1))
    await session.begin_phase()
    await asyncio.wait_for(asyncio.gather(*list(session._tasks)), timeout=2)
    await session.say("FRANCE", "broadcast", [], "ONLY IN SPRING")
    await session.say("FRANCE", "broadcast", [], "", skip=True)
    await session.submit_orders("FRANCE", [])
    assert session.round == 1 and session.mode == "NEGO"
    assert session.state("FRANCE")["staged_msgs"] == []
    assert session.your_turn("FRANCE")
    assert len([message for message in session.bus.msgs if message.text == "ONLY IN SPRING"]) == 1
    assert all(message.phase == "S1901M" for message in session.bus.msgs)
    await session.aclose()


@pytest.mark.asyncio
async def test_human_without_retreat_does_not_block_retreating_human():
    session = Session(["FRANCE", "GERMANY"], cfg=Config(api="mock"))
    session.eng.game.clear_units()
    session.eng.game.set_units("FRANCE", ["A PAR", "A PIC"])
    session.eng.game.set_units("GERMANY", ["A BUR"])
    session.eng.submit("FRANCE", ["A PAR - BUR", "A PIC S A PAR - BUR"])
    session.eng.submit("GERMANY", ["A BUR H"])
    assert session.eng.process().endswith("R")
    await session.begin_phase()
    assert session.mode == "ORDERS" and session._horders["FRANCE"] == []
    assert session.state("GERMANY")["order_pending"] == ["GERMANY"]
    result = await session.submit_orders("GERMANY", ["A BUR R MUN"])
    assert result["phase"] == "F1901M"
    await session.aclose()


def test_restart_keeps_frozen_clock_budget(client, monkeypatch):
    owner = create(client)
    client.post("/api/room/start", json={"token": owner["token"]})
    room = web.RM.rooms[owner["code"]]
    room.deadline = time.time() + 39
    web.RM.checkpoint(room); room.session.close()
    monkeypatch.setattr(web, "RM", RoomManager())
    view = state(client, owner)
    assert view["status"] == "paused" and 37 <= view["secs_left"] <= 39
    client.post("/api/room/pause", json={"token": owner["token"], "status": "playing"})
    restored = web.RM.rooms[owner["code"]]
    assert 37 <= restored.deadline - time.time() <= 39
    assert restored.clock_turn == restored.session.turn_id
