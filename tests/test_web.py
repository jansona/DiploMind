"""P9 web 后端单测：启动即开同一局, 刷新只读不重置。"""
from fastapi.testclient import TestClient

from diplomind.web import app


def test_persistent_game_on_boot():
    with TestClient(app) as c:                       # 触发 startup 建局
        assert "DiploMind" in c.get("/").text
        assert c.get("/api/state").json()["mode"] in ("NEGO", "ORDERS")
        assert c.get("/api/state").json()["human"] == "FRANCE"     # 同一局, 只读
        assert len(c.get("/api/map").text) > 1000                  # 真棋盘已就绪
