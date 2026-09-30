"""Server-only runtime configuration. New installs use deterministic offline play."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .credentials import validate_key_file_reference


def validate_request_options(options: object, api: str) -> dict[str, int | bool | str]:
    """Copy only supported server-side OpenAI-compatible JSON body options.

    Provider-specific options are never inferred or translated for other APIs.
    Errors deliberately omit supplied keys/values, which could contain secrets.
    """
    if not isinstance(options, dict):
        raise ValueError("request_options must be an object")
    if set(options) - {"max_tokens", "enable_thinking", "reasoning_effort"}:
        raise ValueError("Unsupported request_options field")
    if options and api != "openai":
        raise ValueError("request_options requires the openai provider")
    if "max_tokens" in options:
        value = options["max_tokens"]
        if type(value) is not int or not 1 <= value <= 32768:
            raise ValueError("request_options.max_tokens must be an integer between 1 and 32768")
    if "enable_thinking" in options and type(options["enable_thinking"]) is not bool:
        raise ValueError("request_options.enable_thinking must be a boolean")
    if "reasoning_effort" in options:
        value = options["reasoning_effort"]
        if type(value) is not str or value not in {"low", "high", "max"}:
            raise ValueError("request_options.reasoning_effort must be low, high, or max")
    return dict(options)


@dataclass
class Config:
    base_url: str = "http://localhost:11434"
    api_key: str | None = field(default="ollama", repr=False)
    model: str = "qwen3.5:4b"
    api: str = "mock"
    rounds: int = 5
    lang: str = "zh-Hans"
    concurrency: int = 3
    human: str | None = "FRANCE"
    timeout: int = 120
    max_year: int | None = None
    end_rule: str = "draw"
    game_mode: str = "classic"
    cli_enabled: bool = False
    order_preflight_review: bool = False
    request_options: dict[str, int | bool | str] = field(default_factory=dict)
    api_key_file: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.order_preflight_review) is not bool:
            raise ValueError("order_preflight_review must be a boolean")
        self.request_options = validate_request_options(self.request_options, self.api)
        self.api_key_file = validate_key_file_reference(api=self.api, api_key=self.api_key,
                                                       api_key_file=self.api_key_file)


DEFAULT_CONF = "conf/default.json"


def load() -> Config:
    path = os.getenv("DIPLOMIND_CONFIG") or DEFAULT_CONF
    c = Config()
    if path and Path(path).exists():
        for k, v in json.loads(Path(path).read_text()).items():
            if hasattr(c, k):
                setattr(c, k, v)
    for env, attr in [("DIPLOMIND_MODEL", "model"), ("DIPLOMIND_LANG", "lang"), ("DIPLOMIND_API", "api"),
                      ("DIPLOMIND_API_KEY", "api_key"), ("DIPLOMIND_BASE_URL", "base_url")]:
        if os.getenv(env):
            setattr(c, attr, os.getenv(env))
    if os.getenv("DIPLOMIND_CLI_ENABLED") is not None:
        c.cli_enabled = os.getenv("DIPLOMIND_CLI_ENABLED") == "1"
    c.max_year = int(c.max_year) if c.max_year is not None else None
    c.rounds = max(1, min(20, int(c.rounds)))
    if c.game_mode not in {"classic", "plus"}:
        raise ValueError("game_mode must be classic or plus")
    if type(c.order_preflight_review) is not bool:
        raise ValueError("order_preflight_review must be a boolean")
    c.request_options = validate_request_options(c.request_options, c.api)
    c.api_key_file = validate_key_file_reference(api=c.api, api_key=c.api_key, api_key_file=c.api_key_file)
    return c
