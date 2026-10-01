"""Bounded structured-output gateway: offline simulation, HTTP APIs, opt-in CLIs.

Provider selection and credentials are server configuration. No prompt, model
response, endpoint, header, subprocess stderr, or credential is written to logs.
Invalid/unavailable decisions return None; engine-safe holds remain explicit.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from typing import Type, TypeVar
from types import MappingProxyType
from urllib.parse import urlsplit
from urllib.request import proxy_bypass

import httpx
from pydantic import BaseModel, ValidationError

from .debuglog import DebugLog
from .config import Config, validate_request_options
from .credentials import resolve_api_key
from .providers.cli import CLIProvider, EXECUTABLES, ProviderUnavailable, MAX_OUTPUT
from .providers.mock import MockProvider

T = TypeVar("T", bound=BaseModel)
BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = os.getenv("DIPLOMIND_MODEL", "qwen3.5:4b")
DIFFICULTY = {"easy": "qwen3.5:4b", "normal": "qwen3.5:4b", "hard": "qwen3.5:9b"}


def assign(difficulty: str = "normal") -> str:
    return DIFFICULTY.get(difficulty, DEFAULT_MODEL)


def _runtime_proxy(base_url: str) -> str | None:
    """Use the server's approved HTTP proxy route; never log its credentials.

    Explicit transports avoid an unrelated ALL_PROXY/SOCKS setting requiring a
    SOCKS package for every request. Loopback/Ollama and NO_PROXY stay direct.
    Transport trust_env=True below retains the runtime's trusted CA bundle.
    """
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"} or proxy_bypass(host):
        return None
    name = "HTTPS_PROXY" if parts.scheme == "https" else "HTTP_PROXY"
    return os.getenv(name) or os.getenv(name.lower())


def provider_capabilities(cli_enabled: bool = False) -> list[dict]:
    """Safe, passive discovery. Available != authenticated or live-tested."""
    rows = [
        {"id": "mock", "label": "Offline simulation · 零费用模拟", "kind": "simulation", "implemented": True,
         "available": True, "status": "ready", "requires_credentials": False,
         "warning": "Deterministic heuristic, not a language model"},
        {"id": "ollama", "label": "Ollama", "kind": "http", "implemented": True,
         "available": True, "status": "configuration_required", "requires_credentials": False,
         "warning": "A running local Ollama server and installed model are required"},
        {"id": "openai", "label": "OpenAI-compatible API", "kind": "http", "implemented": True,
         "available": True, "status": "configuration_required", "requires_credentials": True,
         "warning": "Provider usage may incur charges"},
    ]
    for name, executable in EXECUTABLES.items():
        installed = bool(shutil.which(executable))
        rows.append({"id": name, "label": {"codex": "Codex CLI", "claude-code": "Claude Code", "qoder": "Qoder CLI"}[name],
                     "kind": "server_local_cli", "implemented": True, "available": cli_enabled and installed,
                     "status": "disabled" if not cli_enabled else "unverified" if installed else "not_installed",
                     "requires_credentials": True, "live_verified": False,
                     "warning": "Experimental, subprocess-contract tested only; requires explicit server opt-in and dedicated environment auth. May incur charges"})
    return rows


def _fields(schema: Type[BaseModel]) -> str:
    return ", ".join(f'"{k}"({v.get("type", "")})' for k, v in schema.model_json_schema().get("properties", {}).items())


def _extract(txt: str) -> str:
    txt = re.sub(r"```(?:json)?|```", "", txt)
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    txt = txt.translate(str.maketrans("“”„‟‘’", '\"\"\"\"\'\'')).strip()
    i = txt.find("{")
    if i < 0: return txt
    # Decode the first complete object, not a greedy first-to-last brace slice.
    try:
        _, length = json.JSONDecoder().raw_decode(txt[i:])
        return txt[i:i + length]
    except ValueError:
        j = txt.rfind("}")
        if j > i: return txt[i:j + 1]
        return txt[i:] + "}" * max(0, txt.count("{") - txt.count("}"))


class Gateway:
    def __init__(self, model: str = DEFAULT_MODEL, log: DebugLog | None = None,
                 temperature: float = 0.7, think: bool = False, concurrency: int = 3,
                 constrain: bool = True, base_url: str = BASE_URL, api_key: str | None = "ollama",
                 api: str = "ollama", timeout: float = 120, cli_enabled: bool = False,
                 request_options: dict[str, int | bool | str] | None = None) -> None:
        if api not in {"mock", "ollama", "openai", *EXECUTABLES}:
            raise ValueError("Unknown provider")
        self.request_options = MappingProxyType(validate_request_options(
            {} if request_options is None else request_options, api))
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model):
            raise ValueError("Invalid model identifier")
        if isinstance(concurrency, bool) or not 1 <= int(concurrency) <= 32:
            raise ValueError("Concurrency must be between 1 and 32")
        if not 0 < float(timeout) <= 600:
            raise ValueError("Timeout must be between 0 and 600 seconds")
        if api in ("ollama", "openai"):
            parts = urlsplit(base_url)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError("Provider URL must be a plain HTTP(S) server URL without credentials")
        self.model, self.temperature, self.think = model, temperature, think
        self.api, self.constrain, self.timeout = api, constrain, float(timeout)
        self.path = "/api/chat" if api == "ollama" else "/chat/completions"
        self.log = log or DebugLog()
        headers = {"Authorization": f"Bearer {api_key}"} if api == "openai" and api_key else {}
        url = base_url if api in ("ollama", "openai") else BASE_URL
        proxy = _runtime_proxy(url) if api in ("ollama", "openai") else None
        self.sync = httpx.Client(base_url=url, trust_env=False, timeout=self.timeout, headers=headers,
                                 transport=httpx.HTTPTransport(proxy=proxy, trust_env=True, retries=0))
        self.aclient = httpx.AsyncClient(base_url=url, trust_env=False, timeout=self.timeout, headers=headers,
                                       transport=httpx.AsyncHTTPTransport(proxy=proxy, trust_env=True, retries=0))
        self.concurrency, self.cli_enabled = int(concurrency), bool(cli_enabled)
        self._sem: asyncio.Semaphore | None = None
        self._loop = None
        self._closed = False
        self._mock = MockProvider()
        self._cli = CLIProvider(api, model, enabled=cli_enabled) if api in EXECUTABLES else None
        self.health = {"status": "ready" if api == "mock" else "unverified", "calls": 0, "successes": 0,
                       "failures": 0, "fallbacks": 0, "cancelled": 0, "last_error": None}

    @classmethod
    def from_config(cls, cfg: Config) -> "Gateway":
        """Use current server configuration; never recover providers from game saves."""
        api_key = resolve_api_key(api=cfg.api, api_key=cfg.api_key, api_key_file=cfg.api_key_file)
        return cls(model=cfg.model, base_url=cfg.base_url, api_key=api_key,
                   api=cfg.api, concurrency=cfg.concurrency, timeout=cfg.timeout,
                   cli_enabled=cfg.cli_enabled, request_options=cfg.request_options)

    def capabilities(self) -> dict:
        return {"selected": self.api, "model": self.model, "health": dict(self.health),
                "providers": provider_capabilities(self.cli_enabled)}

    async def aclose(self) -> None:
        self._closed = True
        self.sync.close()
        await self.aclient.aclose()
        if self._cli: await self._cli.aclose()
        self.health["status"] = "closed"

    def close(self) -> None:
        self._closed = True
        self.sync.close()
        if self._cli: self._cli.close()
        try:
            asyncio.get_running_loop().create_task(self.aclose())
        except RuntimeError:
            asyncio.run(self.aclose())
        self.health["status"] = "closed"

    def _gate(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._loop is not loop:
            self._sem, self._loop = asyncio.Semaphore(self.concurrency), loop
        return self._sem

    def _msgs(self, messages, schema):
        spec = f"\nReturn exactly one JSON object with fields: {_fields(schema)}. No markdown or commentary."
        return [{**m, "content": m["content"] + spec} if m["role"] == "system" else dict(m) for m in messages]

    def _body(self, messages, schema, temp=None):
        msgs = self._msgs(messages, schema)
        temperature = self.temperature if temp is None else temp
        if self.api == "ollama":
            body = {"model": self.model, "messages": msgs, "stream": False, "think": self.think,
                    "options": {"temperature": temperature, "num_predict": 2048}}
            if self.constrain: body["format"] = schema.model_json_schema()
            return body
        return {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": 2048,
                "response_format": {"type": "json_object"}, **self.request_options}

    @staticmethod
    def _retry_hint(messages, txt=None):
        # Do not echo malformed output (or possible provider secrets) into prompts.
        return messages + [{"role": "user", "content": "Previous response did not match the schema. Return one complete JSON object, using the required field names and types."}]

    def _content(self, data):
        if not isinstance(data, dict): raise ValueError("invalid_envelope")
        if self.api == "ollama": content = data.get("message", {}).get("content", "")
        else:
            choice = (data.get("choices") or [{}])[0]
            # Even syntactically valid (or repairable) JSON is not a completed decision.
            if choice.get("finish_reason") == "length": raise ValueError("output_truncated")
            content = choice.get("message", {}).get("content", "")
        if not isinstance(content, str) or not content or len(content) > MAX_OUTPUT:
            raise ValueError("invalid_content")
        return content

    def _tokens(self, data) -> int:
        """Only bounded integer usage metadata; never retain reasoning or raw output."""
        def valid(value):
            return type(value) is int and 0 <= value <= 1_000_000_000
        if not isinstance(data, dict): return 0
        if self.api == "ollama":
            counts = [data.get("prompt_eval_count"), data.get("eval_count")]
        else:
            usage = data.get("usage")
            if not isinstance(usage, dict): return 0
            total = usage.get("total_tokens")
            if valid(total): return total
            counts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
        return sum(counts) if all(valid(value) for value in counts) and valid(sum(counts)) else 0

    def _record(self, tag, started, attempt, error=None, tokens=0):
        # Log metadata only. In particular HTTP error text often contains URLs or keys.
        self.log.record(kind="llm", tag=str(tag)[:64], provider=self.api, model=self.model,
                        latency_ms=round((time.monotonic()-started)*1000), retries=attempt,
                        tokens=tokens, fmt_fail=int(error is not None), error=error)

    def _success(self):
        self.health.update(status="ready", last_error=None)
        self.health["successes"] += 1

    def _failure(self, error):
        self.health.update(status="degraded", last_error=error)
        self.health["failures"] += 1

    def _validate(self, data, schema, ms, tag, attempt, fails):
        # Legacy helper retained for callers; all failures stay non-fatal.
        try:
            return schema.model_validate_json(_extract(self._content(data))), fails
        except (ValidationError, ValueError, TypeError, AttributeError, IndexError):
            return None, fails + 1

    @staticmethod
    def _response_data(response):
        if isinstance(response, httpx.Response):
            response.raise_for_status()
            if len(response.content) > MAX_OUTPUT: raise ValueError("response_limit")
        return response.json()

    @staticmethod
    def _error(exc) -> str:
        if isinstance(exc, httpx.HTTPStatusError): return f"http_{exc.response.status_code}"
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)): return "timeout"
        if isinstance(exc, ProviderUnavailable): return str(exc)  # fixed internal error codes only
        if isinstance(exc, (ValidationError, ValueError, TypeError, AttributeError, IndexError)): return "invalid_response"
        return "provider_unavailable"

    @staticmethod
    def _retryable(exc) -> bool:
        if isinstance(exc, ProviderUnavailable): return False
        if isinstance(exc, httpx.HTTPStatusError): return exc.response.status_code in (408, 429) or exc.response.status_code >= 500
        return True

    def chat(self, messages, schema: Type[T], tag: str = "", retry: int = 2, temp=None) -> T | None:
        if self._closed: return None
        if self._cli:
            try: asyncio.get_running_loop()
            except RuntimeError: return asyncio.run(self.achat(messages, schema, tag, retry, temp))
            raise RuntimeError("Use await achat for CLI providers inside an event loop")
        self.health["calls"] += 1
        started = time.monotonic(); msgs = messages
        for attempt in range(max(0, min(2, retry)) + 1):
            tokens = 0
            try:
                remaining = self.timeout - (time.monotonic() - started)
                if remaining <= 0: raise TimeoutError()
                if self.api == "mock": out = schema.model_validate(self._mock.complete(msgs, schema, tag))
                else:
                    data = self._response_data(self.sync.post(self.path, json=self._body(msgs, schema, temp), timeout=remaining))
                    tokens = self._tokens(data)
                    out = schema.model_validate_json(_extract(self._content(data)))
                self._success(); self._record(tag, started, attempt, tokens=tokens); return out
            except Exception as exc:
                error = self._error(exc); self._failure(error); self._record(tag, started, attempt, error, tokens=tokens)
                if not self._retryable(exc): break
                msgs = self._retry_hint(messages)
        self.health["fallbacks"] += 1
        return None

    async def achat(self, messages, schema: Type[T], tag: str = "", retry: int = 2, temp=None) -> T | None:
        if self._closed: return None
        self.health["calls"] += 1
        started = time.monotonic(); msgs = messages
        try:
            # Entire decision budget includes queueing, all retries, and subprocess cleanup.
            async with asyncio.timeout(self.timeout):
                async with self._gate():
                    for attempt in range(max(0, min(2, retry)) + 1):
                        tokens = 0
                        try:
                            if self.api == "mock":
                                await asyncio.sleep(0)  # keep offline rooms cooperative/cancellable
                                out = schema.model_validate(self._mock.complete(msgs, schema, tag))
                            elif self._cli:
                                txt = await self._cli.complete(self._msgs(msgs, schema), schema.model_json_schema(), self.timeout)
                                out = schema.model_validate_json(_extract(txt))
                            else:
                                data = self._response_data(await self.aclient.post(self.path, json=self._body(msgs, schema, temp)))
                                tokens = self._tokens(data)
                                out = schema.model_validate_json(_extract(self._content(data)))
                            self._success(); self._record(tag, started, attempt, tokens=tokens); return out
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            error = self._error(exc); self._failure(error); self._record(tag, started, attempt, error, tokens=tokens)
                            if not self._retryable(exc): break
                            msgs = self._retry_hint(messages)
                            if attempt < min(2, retry): await asyncio.sleep(.05 * (attempt + 1))
        except asyncio.CancelledError:
            self.health["cancelled"] += 1
            raise  # room shutdown must never turn cancellation into a late hold response
        except TimeoutError:
            self._failure("timeout"); self._record(tag, started, 0, "timeout")
        self.health["fallbacks"] += 1
        return None
