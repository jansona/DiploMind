"""Server-only provider controls, exercised exclusively with fake HTTP transports."""
import asyncio
import importlib
import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from diplomind.config import Config, load
from diplomind.gateway import Gateway
from diplomind.rooms import RoomManager
from diplomind.schemas import Intent
from diplomind.session import Session
import diplomind.web as web


FAKE_KEY = "synthetic-request-options-test-key"
BASE_URL = "https://provider.invalid/v1"
OPTIONS = {"max_tokens": 4096, "enable_thinking": False, "reasoning_effort": "low"}
MESSAGES = [{"role": "system", "content": "Return a short decision"}]


@pytest.fixture(autouse=True)
def safe_runtime(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"api": "mock", "model": "test-model"}))
    monkeypatch.setenv("DIPLOMIND_CONFIG", str(path))
    for key in ("DIPLOMIND_API", "DIPLOMIND_MODEL", "DIPLOMIND_BASE_URL", "DIPLOMIND_CLI_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DIPLOMIND_API_KEY", FAKE_KEY)
    monkeypatch.setattr("diplomind.debuglog.LOG_DIR", tmp_path / "calls")
    (tmp_path / "calls").mkdir()
    return path


@pytest.fixture(autouse=True)
def fake_http(monkeypatch):
    requests = []
    responses = []

    def handle(request):
        requests.append(request)
        envelope = responses.pop(0) if responses else {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"goal":"expand"}'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        }
        return httpx.Response(200, json=envelope)

    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
    monkeypatch.setattr("diplomind.gateway._runtime_proxy", lambda url: None)
    return SimpleNamespace(requests=requests, responses=responses)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("options", [
    {}, {"max_tokens": 1}, {"max_tokens": 32768}, {"enable_thinking": False},
    {"enable_thinking": True}, {"reasoning_effort": "low"},
    {"reasoning_effort": "high"}, {"reasoning_effort": "max"}, OPTIONS,
])
def test_http_body_preserves_explicit_options_and_bounded_defaults(fake_http, asynchronous, options):
    gw = Gateway(api="openai", model="deepseek-v4.1-flash", base_url=BASE_URL,
                 api_key=FAKE_KEY, request_options=options)
    try:
        out = asyncio.run(gw.achat(MESSAGES, Intent)) if asynchronous else gw.chat(MESSAGES, Intent)
        assert out.goal == "expand"
        assert len(fake_http.requests) == 1
        request = fake_http.requests[0]
        body = json.loads(request.content)
        assert request.url == BASE_URL + "/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert body == {
            "model": "deepseek-v4.1-flash", "messages": gw._msgs(MESSAGES, Intent),
            "temperature": .7, "response_format": {"type": "json_object"},
            "max_tokens": 2048, **options,
        }
        assert FAKE_KEY not in request.content.decode()
        assert gw.log.stats()["tokens"] == 130
        assert FAKE_KEY not in gw.log.path.read_text()
    finally:
        gw.close()


@pytest.mark.parametrize("options", [
    [], "not-an-object", 0, True,
    {"max_tokens": 0}, {"max_tokens": -1}, {"max_tokens": 32769},
    {"max_tokens": True}, {"max_tokens": False}, {"max_tokens": "2048"},
    {"max_tokens": 2048.0}, {"max_tokens": None},
    {"enable_thinking": "false"}, {"enable_thinking": 0}, {"enable_thinking": 1},
    {"enable_thinking": None}, {"reasoning_effort": "medium"},
    {"reasoning_effort": "HIGH"}, {"reasoning_effort": 1},
    {"reasoning_effort": None}, {"reasoning_effort": []},
    {"extra_body": {"enable_thinking": False}}, {"headers": {"x-test": FAKE_KEY}},
    {"api_key": FAKE_KEY}, {"base_url": BASE_URL}, {"model": "different-model"},
    {"messages": []}, {"temperature": .2}, {"stream": True}, {"unknown": FAKE_KEY},
])
def test_invalid_options_fail_in_config_file_and_gateway_before_clients(options, safe_runtime, monkeypatch):
    def no_client(*args, **kwargs):
        pytest.fail("Invalid configuration must be rejected before constructing HTTP clients")
    monkeypatch.setattr(httpx, "Client", no_client)
    monkeypatch.setattr(httpx, "AsyncClient", no_client)
    safe_runtime.write_text(json.dumps({"api": "openai", "request_options": options}))
    for make in (lambda: Config(api="openai", request_options=options), load,
                 lambda: Gateway(api="openai", request_options=options)):
        with pytest.raises(ValueError) as error:
            make()
        assert FAKE_KEY not in str(error.value)
        assert BASE_URL not in str(error.value)


def test_null_config_options_are_not_silently_treated_as_omitted(safe_runtime):
    with pytest.raises(ValueError, match="must be an object"):
        Config(api="openai", request_options=None)
    safe_runtime.write_text(json.dumps({"api": "openai", "request_options": None}))
    with pytest.raises(ValueError, match="must be an object"):
        load()


@pytest.mark.parametrize("api", ["mock", "ollama", "codex", "claude-code", "qoder"])
@pytest.mark.parametrize("options", [{"max_tokens": 2048}, {"enable_thinking": False}, {"reasoning_effort": "low"}])
def test_non_openai_providers_reject_api_specific_options(api, options, safe_runtime):
    safe_runtime.write_text(json.dumps({"api": api, "request_options": options}))
    for make in (lambda: Config(api=api, request_options=options), load,
                 lambda: Gateway(api=api, request_options=options)):
        with pytest.raises(ValueError, match="requires the openai provider"):
            make()


def test_server_environment_provider_override_cannot_leak_api_options(safe_runtime, monkeypatch):
    safe_runtime.write_text(json.dumps({"api": "openai", "request_options": OPTIONS}))
    monkeypatch.setenv("DIPLOMIND_API", "ollama")
    with pytest.raises(ValueError, match="requires the openai provider"):
        load()


def test_options_are_copied_and_do_not_leak_between_instances_or_providers():
    source = dict(OPTIONS)
    cfg = Config(api="openai", request_options=source)
    source["max_tokens"] = 1
    assert cfg.request_options == OPTIONS
    configured = Gateway.from_config(cfg)
    plain = Gateway(api="openai", think=True)
    ollama = Gateway(api="ollama", think=True)
    mock = Gateway(api="mock")
    try:
        cfg.request_options.update(api_key=FAKE_KEY, enable_thinking=True)
        assert dict(configured.request_options) == OPTIONS
        with pytest.raises(TypeError):
            configured.request_options["api_key"] = FAKE_KEY
        configured._body([], Intent)["enable_thinking"] = True
        assert configured._body([], Intent)["enable_thinking"] is False
        plain_body = plain._body([], Intent)
        assert plain_body["max_tokens"] == 2048
        assert "enable_thinking" not in plain_body and "reasoning_effort" not in plain_body
        ollama_body = ollama._body([], Intent)
        assert ollama_body["think"] is True and ollama_body["options"]["num_predict"] == 2048
        assert not set(OPTIONS).intersection(ollama_body)
        assert not mock.request_options
        assert Config().request_options is not Config().request_options
        assert "request_options" not in configured.capabilities()
    finally:
        for gw in (configured, plain, ollama, mock):
            gw.close()


def write_provider_config(path, options):
    path.write_text(json.dumps({"api": "openai", "model": "deepseek-v4.1-flash",
                               "base_url": BASE_URL, "request_options": options,
                               "concurrency": 2, "timeout": 45, "rounds": 1}))


def test_session_creation_and_legacy_save_reload_use_current_server_config(safe_runtime):
    write_provider_config(safe_runtime, OPTIONS)
    session = Session("FRANCE")
    restored = loaded = None
    try:
        assert dict(session.gw.request_options) == OPTIONS
        assert session.gw.api == "openai" and session.gw.model == "deepseek-v4.1-flash"
        assert session.gw.concurrency == 2 and session.gw.timeout == 45
        assert str(session.gw.sync.base_url).rstrip("/") == BASE_URL
        blob = session.to_dict()
        assert not any(field in blob for field in ("request_options", "api_key", "base_url", "api"))
        assert FAKE_KEY not in json.dumps(blob) and BASE_URL not in json.dumps(blob)
        session.save("test")
        changed = {"max_tokens": 8192, "enable_thinking": True, "reasoning_effort": "high"}
        write_provider_config(safe_runtime, changed)
        blob.update(request_options={"max_tokens": 1}, api_key="injected", base_url="https://wrong.invalid")
        restored = Session.from_dict(blob)
        loaded = Session.load("test")
        assert dict(restored.gw.request_options) == dict(loaded.gw.request_options) == changed
        assert restored.gw.sync.headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert str(restored.gw.sync.base_url).rstrip("/") == BASE_URL
    finally:
        for target in (session, restored, loaded):
            if target: target.close()


def test_room_start_slot_load_and_restart_recovery_use_server_options(safe_runtime):
    write_provider_config(safe_runtime, OPTIONS)
    manager = RoomManager()
    room = manager.create("Configured", "Host", "FRANCE")
    recovered = None
    try:
        room.start()
        assert dict(room.session.gw.request_options) == OPTIONS
        manager.save(room, "test")
        changed = {"max_tokens": 8192, "reasoning_effort": "max"}
        write_provider_config(safe_runtime, changed)
        manager.load(room, "test")
        assert dict(room.session.gw.request_options) == changed
        recovered = RoomManager().recover(room.owner)
        assert recovered and recovered.status == "paused"
        assert dict(recovered.session.gw.request_options) == changed
        for path in Session.SAVES.rglob("*.json"):
            saved = path.read_text()
            assert "request_options" not in saved and FAKE_KEY not in saved and BASE_URL not in saved
    finally:
        room.session.close()
        if recovered: recovered.session.close()


@pytest.mark.parametrize("field,value", [
    ("request_options", OPTIONS), ("request_options", {}), ("request_options", None),
    ("api", "openai"), ("base_url", BASE_URL), ("api_key", FAKE_KEY),
    ("model", "other-model"), ("cli_enabled", True), ("headers", {"x-test": "x"}),
])
def test_browser_create_rejects_provider_overrides(field, value):
    with TestClient(web.app) as client:
        response = client.post("/api/room/create", json={"power": "FRANCE", field: value})
        assert response.status_code == 422
        assert not web.RM.rooms


def test_game_only_browser_payload_and_public_responses(safe_runtime, monkeypatch):
    write_provider_config(safe_runtime, OPTIONS)
    async def no_ai_work(self):
        return None
    monkeypatch.setattr(Session, "begin_phase", no_ai_work)
    with TestClient(web.app) as client:
        response = client.post("/api/room/create", json={
            "name": "Configured game", "owner_name": "Host", "power": "FRANCE",
            "lang": "en", "game_mode": "classic", "passcode": "", "max_year": 1902,
        })
        assert response.status_code == 200
        owner = response.json()
        assert client.post("/api/room/start", json={"token": owner["token"]}).status_code == 200
        assert dict(web.RM.rooms[owner["code"]].session.gw.request_options) == OPTIONS
        for route in ("/api/providers", "/api/rooms", "/api/menu", "/api/state"):
            data = client.get(route, params={"token": owner["token"]} if route == "/api/state" else {})
            assert data.status_code == 200
            assert FAKE_KEY not in data.text and BASE_URL not in data.text
            assert "request_options" not in data.text and "enable_thinking" not in data.text


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("content", ['{"goal":"looks complete"}', '{"goal":"repairable"'])
def test_truncated_output_is_rejected_before_tolerant_json_parsing(fake_http, asynchronous, content):
    envelope = {"choices": [{"finish_reason": "length", "message": {
        "content": content, "reasoning_content": "private reasoning must not be logged"}}],
        "usage": {"total_tokens": 700}}
    fake_http.responses.extend([envelope] * 3)
    gw = Gateway(api="openai", base_url=BASE_URL, request_options={"max_tokens": 700})
    try:
        out = asyncio.run(gw.achat(MESSAGES, Intent)) if asynchronous else gw.chat(MESSAGES, Intent)
        assert out is None and len(fake_http.requests) == 3
        assert gw.health["successes"] == 0 and gw.health["fallbacks"] == 1
        assert gw.log.stats()["tokens"] == 2100
        recorded = gw.log.path.read_text()
        assert "private reasoning" not in recorded and content not in recorded
        assert all(json.loads(request.content)["max_tokens"] == 700 for request in fake_http.requests)
    finally:
        gw.close()


@pytest.mark.parametrize("api,data,expected", [
    ("openai", {"usage": {"total_tokens": 130}}, 130),
    ("openai", {"usage": {"total_tokens": 0}}, 0),
    ("openai", {"usage": {"prompt_tokens": 100, "completion_tokens": 30}}, 130),
    ("openai", {"usage": {"total_tokens": "130", "prompt_tokens": 1, "completion_tokens": 2}}, 3),
    ("openai", {"usage": {"total_tokens": -1}}, 0),
    ("openai", {"usage": {"total_tokens": True}}, 0),
    ("openai", {"usage": {"total_tokens": 1.5}}, 0),
    ("openai", {"usage": {"total_tokens": 1_000_000_001}}, 0),
    ("openai", {"usage": {"prompt_tokens": 1_000_000_000, "completion_tokens": 1}}, 0),
    ("openai", {"usage": {"prompt_tokens": 100}}, 0),
    ("openai", {"usage": {"prompt_tokens": True, "completion_tokens": 1}}, 0),
    ("openai", {"usage": []}, 0), ("openai", {}, 0), ("openai", None, 0),
    ("ollama", {"prompt_eval_count": 100, "eval_count": 30}, 130),
    ("ollama", {"prompt_eval_count": 0, "eval_count": 0}, 0),
    ("ollama", {"prompt_eval_count": "100", "eval_count": 30}, 0),
    ("ollama", {"prompt_eval_count": 100, "eval_count": -1}, 0),
    ("ollama", {"eval_count": 30}, 0),
])
def test_usage_is_only_bounded_integer_metadata(api, data, expected):
    gw = Gateway(api=api)
    try:
        assert gw._tokens(data) == expected
    finally:
        gw.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("api", ["openai", "ollama"])
def test_prompt_plus_completion_usage_is_recorded_for_both_http_providers(fake_http, asynchronous, api):
    response = ({"choices": [{"message": {"content": '{"goal":"expand"}'}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
                if api == "openai" else {"message": {"content": '{"goal":"expand"}'},
                                         "prompt_eval_count": 10, "eval_count": 5})
    fake_http.responses.append(response)
    gw = Gateway(api=api)
    try:
        out = asyncio.run(gw.achat(MESSAGES, Intent)) if asynchronous else gw.chat(MESSAGES, Intent)
        assert out.goal == "expand"
        assert gw.log.stats()["tokens"] == 15
    finally:
        gw.close()


@pytest.mark.parametrize("module_name", ["scripts.play_game", "scripts.t2_gateway"])
def test_command_line_entrypoints_forward_loaded_server_config(module_name, safe_runtime, monkeypatch):
    write_provider_config(safe_runtime, OPTIONS)
    monkeypatch.setattr(sys, "argv", ["offline-config-test"])
    module = importlib.import_module(module_name)
    seen = []
    real_factory = Gateway.from_config
    gateways = []
    def capture(cfg):
        seen.append(cfg)
        gw = real_factory(cfg)
        gateways.append(gw)
        return gw
    monkeypatch.setattr(module.Gateway, "from_config", capture)
    if module_name == "scripts.play_game":
        class NoGame:
            def __init__(self, *args): pass
            async def run_game(self, **kwargs): return {"end": None}
        monkeypatch.setattr(module, "Orchestrator", NoGame)
    try:
        if module_name == "scripts.play_game": asyncio.run(module.main())
        else: module.main()
        assert len(seen) == 1
        assert seen[0].request_options == OPTIONS
        assert dict(gateways[0].request_options) == OPTIONS
    finally:
        for gw in gateways: gw.close()
