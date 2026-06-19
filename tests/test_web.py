"""P9 web 后端单测：端点起得来、返结构(不触 LLM 的 /step)。"""
from fastapi.testclient import TestClient

from diplomind.web import app

c = TestClient(app)


def test_index_and_state():
    assert "DiploMind" in c.get("/").text
    s = c.get("/api/state").json()
    assert s["running"] is False and "centers" in s


def test_chronicle_empty():
    assert "text" in c.get("/api/chronicle").json()
