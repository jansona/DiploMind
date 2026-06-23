"""P9 web: main menu (no auto game), presets/saves, i18n; one game from New/Continue."""
from fastapi.testclient import TestClient

from diplomind.web import app


def test_menu_no_autogame():
    with TestClient(app) as c:
        assert c.get("/api/state").json()["mode"] == "MENU"     # no auto game; show menu
        m = c.get("/api/menu").json()
        assert "presets" in m and "saves" in m and "classic" in m["presets"]


def test_i18n_files():
    with TestClient(app) as c:
        assert c.get("/api/i18n/en").json()["send"] == "Send"
        assert c.get("/api/i18n/zh-Hans").json()["send"] == "发送"
        assert c.get("/api/i18n/xx").json()["send"] == "Send"     # fallback


def test_room_create_join_state():
    with TestClient(app) as c:
        d = c.post("/api/room/create", json={"name": "T", "owner_name": "Al", "power": "FRANCE"}).json()
        assert len(d["code"]) == 4 and d["owner"] and d["seat"] == "FRANCE"
        j = c.post("/api/room/join", json={"code": d["code"], "power": "GERMANY", "name": "Bo"}).json()
        assert j["seat"] == "GERMANY" and not j["owner"]
        assert len(c.get("/api/rooms").json()["rooms"]) >= 1
        c.post("/api/room/start", json={"token": d["token"]})
        s = c.get("/api/state", params={"token": d["token"]}).json()
        assert s["human"] == "FRANCE" and s["room"] == d["code"] and s["owner"]
        s2 = c.get("/api/state", params={"token": j["token"]}).json()
        assert s2["human"] == "GERMANY" and not s2["owner"]   # per-seat view


def test_start_requires_owner():
    with TestClient(app) as c:
        d = c.post("/api/room/create", json={"power": "FRANCE"}).json()
        j = c.post("/api/room/join", json={"code": d["code"], "power": "ITALY"}).json()
        r = c.post("/api/room/start", json={"token": j["token"]})
        assert r.status_code == 403   # non-owner can't start


def test_passcode_join_reject_and_accept():
    with TestClient(app) as c:
        d = c.post("/api/room/create", json={"power": "FRANCE", "passcode": "secret"}).json()
        assert c.post("/api/room/join", json={"code": d["code"], "power": "ITALY", "passcode": "nope"}).status_code == 403
        j = c.post("/api/room/join", json={"code": d["code"], "power": "ITALY", "passcode": "secret"}).json()
        assert j["seat"] == "ITALY"


def test_save_load_continue():
    with TestClient(app) as c:
        d = c.post("/api/room/create", json={"power": "FRANCE", "passcode": "p"}).json()
        c.post("/api/room/start", json={"token": d["token"]})
        c.post("/api/save", params={"name": "wtest", "token": d["token"]})
        nd = c.post("/api/load", params={"name": "wtest"}).json()
        s = c.get("/api/state", params={"token": nd["token"]}).json()
        assert s["human"] == "FRANCE" and s["mode"] != "MENU" and s["owner"]   # reopened, continues


def test_transfer_secs_endpoints():
    with TestClient(app) as c:
        d = c.post("/api/room/create", json={"power": "FRANCE"}).json()
        j = c.post("/api/room/join", json={"code": d["code"], "power": "GERMANY"}).json()
        c.post("/api/room/start", json={"token": d["token"]})
        assert c.post("/api/room/secs", json={"token": d["token"], "secs": 0}).json()["timer_on"] is False
        c.post("/api/room/transfer", json={"token": d["token"], "power": "GERMANY"})
        assert not c.get("/api/state", params={"token": d["token"]}).json()["owner"]   # owner moved to Bo
        assert c.get("/api/state", params={"token": j["token"]}).json()["owner"]
