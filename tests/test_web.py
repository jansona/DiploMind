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
