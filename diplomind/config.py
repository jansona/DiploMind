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
    rounds: int = 5                              # negotiation rounds per phase
    lang: str = "zh-Hans"
    concurrency: int = 3
    human: str = "FRANCE"                         # which power the human plays; null = all-AI spectate
    timeout: int = 120                            # per-call LLM timeout (s); slow calls give up -> hold
    max_year: int = 1910                          # year-end draw cap (hard ceiling 1910)


DEFAULT_CONF = "conf/deepseek.json"              # default AI service = deepseek (was local ollama)


def load() -> Config:
    path = os.getenv("DIPLOMIND_CONFIG") or DEFAULT_CONF   # DIPLOMIND_CONFIG=conf/ollama_qwen35_2b.json for local
    c = Config()
    if path and Path(path).exists():
        for k, v in json.loads(Path(path).read_text()).items():
            if hasattr(c, k):
                setattr(c, k, v)
    for env, attr in [("DIPLOMIND_MODEL", "model"), ("DIPLOMIND_LANG", "lang")]:  # env overrides file
        if os.getenv(env):
            setattr(c, attr, os.getenv(env))
    c.max_year = min(1910, int(c.max_year))      # hard ceiling: engine retreat/build only to 1910
    return c
