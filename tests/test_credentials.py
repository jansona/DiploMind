"""Credential-file seam tests use synthetic files in pytest's temporary directory.

No test reads or starts a provider with the deployment's actual credential path.
"""
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest

import diplomind.credentials as credentials
from diplomind.config import Config, load
from diplomind.credentials import CredentialError, resolve_api_key, validate_key_file_reference
from diplomind.gateway import Gateway
from diplomind.schemas import Intent
from diplomind.session import Session
import diplomind.web as web


FAKE_KEY = "synthetic-file-backed-test-key"


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    root = tmp_path / "diplomind-private"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(credentials, "_ALLOWED_KEY_ROOT", root)
    path = root / "api-key.txt"
    path.write_text(FAKE_KEY + "\n")
    path.chmod(0o600)
    cfg_path = tmp_path / "server.json"
    cfg_path.write_text(json.dumps({"api": "mock"}))
    monkeypatch.setenv("DIPLOMIND_CONFIG", str(cfg_path))
    for key in ("DIPLOMIND_API", "DIPLOMIND_MODEL", "DIPLOMIND_API_KEY", "DIPLOMIND_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    logdir = tmp_path / "calls"
    logdir.mkdir()
    monkeypatch.setattr("diplomind.debuglog.LOG_DIR", logdir)
    requests = []
    def fake_http(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": '{"goal":"expand"}'}}], "usage": {"total_tokens": 10}})
    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(fake_http))
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(fake_http))
    monkeypatch.setattr("diplomind.gateway._runtime_proxy", lambda url: None)
    return SimpleNamespace(root=root, path=path, config=cfg_path, requests=requests)


def config_values(runtime):
    return {"api": "openai", "api_key": None, "api_key_file": str(runtime.path),
            "base_url": "https://provider.invalid/v1", "model": "test-model",
            "request_options": {"max_tokens": 2048, "enable_thinking": False}}


def resolve(runtime):
    return resolve_api_key(api="openai", api_key=None, api_key_file=str(runtime.path))


def test_config_load_only_validates_reference_without_key_file_io(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    runtime.config.write_text(json.dumps(config_values(runtime)))
    # The reference remains valid even when the file does not exist yet.
    runtime.path.unlink()
    runtime.root.rmdir()
    calls = []
    read_text = Path.read_text
    def only_config(path, *args, **kwargs):
        calls.append(path)
        assert path == runtime.config
        return read_text(path, *args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("Config loading must not inspect or read credential files")
    monkeypatch.setattr(Path, "read_text", only_config)
    monkeypatch.setattr(credentials, "_read_pinned_key", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    cfg = load()
    assert cfg.api_key is None and cfg.api_key_file == str(runtime.path)
    assert calls == [runtime.config]
    assert str(runtime.path) not in repr(cfg)


@pytest.mark.parametrize("reference", ["", "api-key.txt", "/tmp/elsewhere/api-key.txt", 1, True, [], {}])
def test_bad_references_fail_without_filesystem_access(isolated_runtime, monkeypatch, reference):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid reference must fail before filesystem access")
    monkeypatch.setattr(os, "open", forbidden)
    with pytest.raises(CredentialError, match="^credential_reference_invalid$"):
        resolve_api_key(api="openai", api_key=None, api_key_file=reference)


def test_reference_is_exact_and_rejects_traversal_and_path_objects(isolated_runtime):
    runtime = isolated_runtime
    for reference in (runtime.path, str(runtime.root / ".." / runtime.root.name / "api-key.txt"),
                      str(runtime.root) + "/./api-key.txt", str(runtime.root / "different.txt")):
        with pytest.raises(CredentialError, match="^credential_reference_invalid$"):
            validate_key_file_reference(api="openai", api_key=None, api_key_file=reference)


@pytest.mark.parametrize("api", ["mock", "ollama", "codex", "claude-code", "qoder"])
def test_key_file_is_openai_only(isolated_runtime, api):
    with pytest.raises(CredentialError, match="^credential_provider_unsupported$"):
        Config(api=api, api_key=None, api_key_file=str(isolated_runtime.path))


@pytest.mark.parametrize("inline", ["", "ollama", FAKE_KEY, False])
def test_non_null_inline_key_conflicts_with_file(isolated_runtime, inline):
    with pytest.raises(CredentialError, match="^credential_sources_conflict$"):
        Config(api="openai", api_key=inline, api_key_file=str(isolated_runtime.path))


def test_environment_key_cannot_silently_override_file(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    runtime.config.write_text(json.dumps(config_values(runtime)))
    monkeypatch.setenv("DIPLOMIND_API_KEY", "synthetic-env-key")
    with pytest.raises(CredentialError, match="^credential_sources_conflict$") as error:
        load()
    assert "synthetic-env-key" not in str(error.value)


def test_no_reference_preserves_existing_inline_behavior_without_filesystem_access(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Inline key resolution must not open a file")
    monkeypatch.setattr(os, "open", forbidden)
    for api in ("mock", "ollama", "openai"):
        assert resolve_api_key(api=api, api_key=FAKE_KEY, api_key_file=None) == FAKE_KEY
        assert resolve_api_key(api=api, api_key=None, api_key_file=None) is None
    cfg = Config()
    assert cfg.api == "mock" and cfg.api_key == "ollama" and cfg.api_key_file is None
    assert FAKE_KEY not in repr(Config(api_key=FAKE_KEY))


@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_secure_file_resolves_bare_key_with_optional_text_newline(isolated_runtime, ending):
    runtime = isolated_runtime
    runtime.path.write_bytes(FAKE_KEY.encode() + ending)
    before = runtime.path.stat()
    assert resolve(runtime) == FAKE_KEY
    after = runtime.path.stat()
    assert after.st_mtime_ns == before.st_mtime_ns
    assert stat.S_IMODE(after.st_mode) == 0o600


@pytest.mark.parametrize("contents,code", [
    (b"", "credential_empty"), (b"\n", "credential_empty"),
    (b"two keys", "credential_invalid"), (b" leading", "credential_invalid"),
    (b"trailing ", "credential_invalid"), (b"bad\x00key", "credential_invalid"),
    (b"first\nsecond", "credential_invalid"), ("非ASCII".encode(), "credential_invalid"),
    (b"API_KEY=synthetic", "credential_invalid"), (b'"synthetic"', "credential_invalid"),
    (b'{"api_key":"synthetic"}', "credential_invalid"),
    (b"Authorization:Bearer-synthetic", "credential_invalid"),
    (b"x" * 8193, "credential_file_unsafe"),
])
def test_invalid_contents_have_fixed_non_secret_errors(isolated_runtime, contents, code):
    runtime = isolated_runtime
    runtime.path.write_bytes(contents)
    with pytest.raises(CredentialError) as error:
        resolve(runtime)
    assert str(error.value) == code
    assert str(runtime.path) not in str(error.value)


def test_maximum_file_length_is_bounded_and_supported(isolated_runtime):
    runtime = isolated_runtime
    runtime.path.write_bytes(b"x" * 8192)
    assert len(resolve(runtime)) == 8192


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o711, 0o777, 0o2700])
def test_private_directory_requires_exact_0700(isolated_runtime, mode):
    runtime = isolated_runtime
    runtime.root.chmod(mode)
    with pytest.raises(CredentialError, match="^credential_file_unsafe$"):
        resolve(runtime)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o400, 0o666, 0o4600])
def test_private_file_requires_exact_0600(isolated_runtime, mode):
    runtime = isolated_runtime
    runtime.path.chmod(mode)
    with pytest.raises(CredentialError, match="^credential_file_unsafe$"):
        resolve(runtime)


def altered_stat(info, **overrides):
    fields = {name: getattr(info, name) for name in ("st_uid", "st_mode", "st_nlink", "st_size")}
    return SimpleNamespace(**{**fields, **overrides})


@pytest.mark.parametrize("target", ["directory", "file"])
def test_directory_and_file_must_belong_to_effective_user(isolated_runtime, monkeypatch, target):
    original = os.fstat
    def other_owner(fd):
        info = original(fd)
        match = stat.S_ISDIR(info.st_mode) if target == "directory" else stat.S_ISREG(info.st_mode)
        return altered_stat(info, st_uid=info.st_uid + 1) if match else info
    monkeypatch.setattr(os, "fstat", other_owner)
    with pytest.raises(CredentialError, match="^credential_file_unsafe$"):
        resolve(isolated_runtime)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo", "missing"])
def test_file_must_be_an_existing_single_link_regular_file(isolated_runtime, kind):
    runtime = isolated_runtime
    if kind == "hardlink":
        os.link(runtime.path, runtime.root / "duplicate.txt")
    else:
        runtime.path.unlink()
        if kind == "symlink":
            other = runtime.root / "synthetic.txt"
            other.write_text(FAKE_KEY)
            other.chmod(0o600)
            runtime.path.symlink_to(other)
        elif kind == "directory": runtime.path.mkdir(mode=0o600)
        elif kind == "fifo": os.mkfifo(runtime.path, 0o600)
    with pytest.raises(CredentialError, match="^credential_file_unsafe$"):
        resolve(runtime)


def test_private_directory_symlink_is_rejected(isolated_runtime):
    runtime = isolated_runtime
    actual = runtime.root.with_name("actual-private")
    runtime.root.rename(actual)
    runtime.root.symlink_to(actual, target_is_directory=True)
    with pytest.raises(CredentialError, match="^credential_file_unsafe$"):
        resolve(runtime)


def test_ancestor_symlink_is_rejected(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    alias = runtime.root.parent / "ancestor-alias"
    alias.symlink_to(runtime.root.parent, target_is_directory=True)
    monkeypatch.setattr(credentials, "_ALLOWED_KEY_ROOT", alias / runtime.root.name)
    with pytest.raises(CredentialError, match="^credential_file_unsafe$"):
        resolve_api_key(api="openai", api_key=None, api_key_file=str(credentials.pinned_key_file()))


def test_read_remains_bounded_if_file_grows_after_stat(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    runtime.path.write_bytes(b"x" * 8193)
    original = os.fstat
    def stale_size(fd):
        info = original(fd)
        return altered_stat(info, st_size=0) if stat.S_ISREG(info.st_mode) else info
    monkeypatch.setattr(os, "fstat", stale_size)
    with pytest.raises(CredentialError, match="^credential_file_unsafe$"):
        resolve(runtime)


@pytest.mark.parametrize("valid", [True, False])
def test_reader_closes_descriptors_on_success_and_failure(isolated_runtime, monkeypatch, valid):
    runtime = isolated_runtime
    if not valid: runtime.path.chmod(0o644)
    original = os.open
    descriptors = []
    def track(*args, **kwargs):
        fd = original(*args, **kwargs)
        descriptors.append(fd)
        return fd
    monkeypatch.setattr(os, "open", track)
    if valid: assert resolve(runtime) == FAKE_KEY
    else:
        with pytest.raises(CredentialError): resolve(runtime)
    assert descriptors
    for fd in set(descriptors):
        with pytest.raises(OSError): os.fstat(fd)


def test_gateway_resolves_at_runtime_without_mutating_config_or_logging_secret(isolated_runtime):
    runtime = isolated_runtime
    runtime.config.write_text(json.dumps(config_values(runtime)))
    cfg = load()
    gw = Gateway.from_config(cfg)
    try:
        assert cfg.api_key is None
        assert gw.sync.headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert gw.aclient.headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert gw.chat([{"role": "system", "content": "test"}], Intent).goal == "expand"
        assert len(runtime.requests) == 1
        assert FAKE_KEY not in runtime.requests[0].content.decode()
        for text in (gw.log.path.read_text(), json.dumps(gw.capabilities()), repr(cfg)):
            assert FAKE_KEY not in text and str(runtime.path) not in text
    finally:
        gw.close()


def test_mutated_config_is_revalidated_before_runtime_file_access(isolated_runtime, monkeypatch):
    cfg = Config(**config_values(isolated_runtime))
    cfg.api_key_file = str(isolated_runtime.root / "other.txt")
    def forbidden(*args, **kwargs):
        pytest.fail("Mutated reference must be rejected before file access")
    monkeypatch.setattr(credentials, "_read_pinned_key", forbidden)
    with pytest.raises(CredentialError, match="^credential_reference_invalid$"):
        Gateway.from_config(cfg)


def test_session_state_and_save_reload_exclude_key_and_reference(isolated_runtime):
    runtime = isolated_runtime
    runtime.config.write_text(json.dumps(config_values(runtime)))
    session = Session("FRANCE")
    restored = None
    try:
        snapshot = session.to_dict()
        session.save("synthetic")
        for text in (json.dumps(session.state()), json.dumps(snapshot),
                     (Session.SAVES / "synthetic.json").read_text()):
            assert FAKE_KEY not in text and str(runtime.path) not in text and "api_key_file" not in text
        snapshot.update(api_key_file="/unapproved/path", api_key="unapproved-key")
        restored = Session.from_dict(snapshot)
        assert restored.gw.sync.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    finally:
        session.close()
        if restored: restored.close()


def test_public_discovery_never_resolves_or_exposes_server_credential_path(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    runtime.config.write_text(json.dumps(config_values(runtime)))
    def forbidden(*args, **kwargs):
        pytest.fail("Public discovery must not resolve provider credentials")
    monkeypatch.setattr(credentials, "_read_pinned_key", forbidden)
    with TestClient(web.app) as client:
        for route in ("/api/providers", "/api/rooms", "/api/menu"):
            response = client.get(route)
            assert response.status_code == 200
            assert FAKE_KEY not in response.text and str(runtime.path) not in response.text
            assert "api_key_file" not in response.text
        response = client.post("/api/room/create", json={"api_key_file": "/browser-supplied/path"})
        assert response.status_code == 422 and not web.RM.rooms


def test_missing_key_fails_before_http_clients_are_created(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    runtime.path.unlink()
    cfg = Config(**config_values(runtime))
    def forbidden(*args, **kwargs):
        pytest.fail("Failed key resolution must precede HTTP client creation")
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(CredentialError, match="^credential_file_unsafe$"):
        Gateway.from_config(cfg)
