"""LLM 网关 Gateway — 接 ollama；prompt 注入字段说明 + 宽松提取 JSON + pydantic 校验+重试；
记每次调用耗时/token/重试/格式失败；think:false 关思考省延迟。

注：qwen3.5:9b 上 ollama 的 format=schema 语法约束慢/失效，故走 prompt 引导 + 容错解析。"""
from __future__ import annotations

import json
import re
import asyncio
import time
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .debuglog import DebugLog

T = TypeVar("T", bound=BaseModel)

BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:4b"

# 难度=纯模型档位：弱模型策略/圆谎差=简单，强=困难。AI 目标不变、不放水。
DIFFICULTY = {"easy": "qwen3.5:4b", "normal": "qwen3.5:4b", "hard": "qwen3.5:9b"}


def assign(difficulty: str = "normal") -> str:
    return DIFFICULTY.get(difficulty, DEFAULT_MODEL)


def _fields(schema: Type[BaseModel]) -> str:
    props = schema.model_json_schema().get("properties", {})
    return ", ".join(f'"{k}"({v.get("type","")})' for k, v in props.items())


def _extract(txt: str) -> str:
    """宽松提取：剥 markdown/思考残留，抠最外层 {…}，缺右括号则补齐。"""
    txt = re.sub(r"```(?:json)?|```", "", txt)
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    txt = txt.translate(str.maketrans("“”„‟‘’", '""""\'\'')).strip()  # 全角引号→直引号
    i = txt.find("{")
    if i < 0:
        return txt
    j = txt.rfind("}")
    if j > i:
        return txt[i:j + 1]
    return txt[i:] + "}" * (txt.count("{") - txt.count("}"))  # 补未闭合括号


class Gateway:
    def __init__(self, model: str = DEFAULT_MODEL, log: DebugLog | None = None,
                 temperature: float = 0.7, think: bool = False, concurrency: int = 3) -> None:
        self.model, self.temperature, self.think = model, temperature, think
        self.log = log or DebugLog()
        self.sync = httpx.Client(base_url=BASE_URL, trust_env=False, timeout=180)
        self.aclient = httpx.AsyncClient(base_url=BASE_URL, trust_env=False, timeout=180)
        self.concurrency = concurrency
        self._sem: asyncio.Semaphore | None = None      # 限并发：最多 N 国同时打 ollama，余者排队

    def _gate(self) -> asyncio.Semaphore:
        if self._sem is None:                           # 懒建，绑当前事件循环
            self._sem = asyncio.Semaphore(self.concurrency)
        return self._sem

    def _msgs(self, messages, schema):
        spec = f"\n严格只输出一个 JSON 对象，含字段: {_fields(schema)}。无解释、无 markdown。"
        return [{**m, "content": m["content"] + spec} if m["role"] == "system" else m for m in messages]

    def _body(self, messages, schema, temp=None):
        return {"model": self.model, "messages": self._msgs(messages, schema), "stream": False,
                "think": self.think, "options": {"temperature": self.temperature if temp is None else temp}}

    def _validate(self, data, schema, ms, tag, attempt, fails):
        txt = data.get("message", {}).get("content", "")
        tok = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
        try:
            obj = schema.model_validate_json(_extract(txt))
            self.log.record(kind="llm", tag=tag, model=self.model, latency_ms=ms, tokens=tok,
                            retries=attempt, fmt_fail=0, response=txt)
            return obj, fails
        except (ValidationError, json.JSONDecodeError):
            self.log.record(kind="llm", tag=tag, model=self.model, latency_ms=ms, tokens=tok,
                            retries=attempt, fmt_fail=1, response=txt, error="parse")
            return None, fails + 1

    def chat(self, messages, schema: Type[T], tag: str = "", retry: int = 2, temp=None) -> T | None:
        fails = 0
        for attempt in range(retry + 1):
            t0 = time.time()
            r = self.sync.post("/api/chat", json=self._body(messages, schema, temp))
            obj, fails = self._validate(r.json(), schema, round((time.time() - t0) * 1000), tag, attempt, fails)
            if obj is not None:
                return obj
        return None

    async def achat(self, messages, schema: Type[T], tag: str = "", retry: int = 2, temp=None) -> T | None:
        async with self._gate():                        # 整次调用(含重试)占一个名额
            fails = 0
            for attempt in range(retry + 1):
                t0 = time.time()
                r = await self.aclient.post("/api/chat", json=self._body(messages, schema, temp))
                obj, fails = self._validate(r.json(), schema, round((time.time() - t0) * 1000), tag, attempt, fails)
                if obj is not None:
                    return obj
            return None
