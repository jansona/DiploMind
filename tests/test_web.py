"""P9 web 后端单测：端点起得来(不触 LLM 的只读)。"""
from fastapi.testclient import TestClient

from diplomind.web import app

c = TestClient(app)


def test_index_and_empty_state():
    assert "DiploMind" in c.get("/").text
    assert c.get("/api/state").json()["mode"] == "NEW"     # 无局
    assert c.get("/api/chronicle").json()["text"] == ""
    assert c.get("/api/map").text == "<svg/>"              # 无局给空棋盘
