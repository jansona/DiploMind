"""启动配置文件: API/模型/轮次/语言/并发可配, env 覆盖, OpenAI兼容路由。"""
import json, os
from diplomind.config import load
from diplomind.gateway import Gateway
from diplomind.session import Session


def test_config_file_loads(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"api": "openai", "model": "glm-4", "rounds": 4, "concurrency": 5}))
    os.environ["DIPLOMIND_CONFIG"] = str(p)
    try:
        c = load(); assert c.model == "glm-4" and c.rounds == 4 and c.api == "openai" and c.concurrency == 5
        s = Session(None, cfg=c); assert s.rounds == 4               # 轮次生效
    finally:
        del os.environ["DIPLOMIND_CONFIG"]


def test_gateway_openai_route():
    gw = Gateway(api="openai", base_url="https://x/v1", api_key="k")
    assert gw.path == "/chat/completions"                             # 非ollama走openai兼容(base_url含/v1)
    assert Gateway(api="ollama").path == "/api/chat"
