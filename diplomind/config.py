"""Runtime config: pick a config file at startup. Supports ollama and any OpenAI-compatible API."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    base_url: str = "http://localhost:11434"   # ollama default; or OpenAI-compatible https://api.x.com/v1
    api_key: str = "ollama"
    model: str = "qwen3.5:4b"
    api: str = "ollama"                          # "ollama" (native /api/chat) or "openai" (/chat/completions)
    rounds: int = 3                              # negotiation rounds per phase
    lang: str = "zh-Hans"
    concurrency: int = 3


def load() -> Config:
    path = os.getenv("DIPLOMIND_CONFIG")         # DIPLOMIND_CONFIG=conf/glm.json uvicorn ...
    c = Config()
    if path and Path(path).exists():
        for k, v in json.loads(Path(path).read_text()).items():
            if hasattr(c, k):
                setattr(c, k, v)
    for env, attr in [("DIPLOMIND_MODEL", "model"), ("DIPLOMIND_LANG", "lang")]:  # env overrides file
        if os.getenv(env):
            setattr(c, attr, os.getenv(env))
    return c
