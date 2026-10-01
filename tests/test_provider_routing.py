from diplomind.gateway import _runtime_proxy


def test_provider_uses_runtime_https_proxy_not_all_proxy(monkeypatch):
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://approved-proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://unrelated.invalid:1080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,.private.invalid")
    assert _runtime_proxy("https://api.example.invalid/v1") == "http://approved-proxy.invalid:8080"
    assert _runtime_proxy("https://api.private.invalid/v1") is None
    assert _runtime_proxy("http://localhost:11434") is None
    assert _runtime_proxy("http://127.0.0.1:11434") is None


def test_provider_route_is_direct_when_no_matching_proxy_configured(monkeypatch):
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5://unrelated.invalid:1080")
    assert _runtime_proxy("https://api.example.invalid/v1") is None
