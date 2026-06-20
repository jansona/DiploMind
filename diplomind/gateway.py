"""LLM 网关 Gateway — 接 ollama；prompt 注入字段说明 + 宽松提取 JSON + pydantic 校验+重试；
记每次调用耗时/token/重试/格式失败；think:false 关思考省延迟。

注：qwen3.5:9b 上 ollama 的 format=schema 语法约束慢/失效，故走 prompt 引导 + 容错解析。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .debuglog import DebugLog

T = TypeVar("T", bound=BaseModel)

BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = os.getenv("DIPLOMIND_MODEL", "qwen3.5:4b")   # 开服可换: DIPLOMIND_MODEL=qwen3.5:2b

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
                 temperature: float = 0.7, think: bool = False, concurrency: int = 3,
                 constrain: bool = True) -> None:
        self.model, self.temperature, self.think = model, temperature, think
        self.constrain = constrain                       # 重开 ollama format 语法硬约束(4b)
        self.log = log or DebugLog()
        self.sync = httpx.Client(base_url=BASE_URL, trust_env=False, timeout=180)
        self.aclient = httpx.AsyncClient(base_url=BASE_URL, trust_env=False, timeout=180)
        self.concurrency = concurrency
        self._sem: asyncio.Semaphore | None = None      # 限并发：最多 N 国同时打 ollama，余者排队
        self._loop = None

    def _gate(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._loop is not loop:  # 换了事件循环就重建(web 每请求一循环)
            self._sem, self._loop = asyncio.Semaphore(self.concurrency), loop
        return self._sem

    def _msgs(self, messages, schema):
        spec = f"\n严格只输出一个 JSON 对象，含字段: {_fields(schema)}。无解释、无 markdown。"
        return [{**m, "content": m["content"] + spec} if m["role"] == "system" else m for m in messages]

    def _body(self, messages, schema, temp=None):
        b = {"model": self.model, "messages": self._msgs(messages, schema), "stream": False, "think": self.think,
             "options": {"temperature": self.temperature if temp is None else temp, "num_predict": 320}}  # 截输出, 压尾延迟
        if self.constrain:                               # 语法硬约束：解码只能产出合法 schema
            b["format"] = schema.model_json_schema()
        return b

    @staticmethod
    def _retry_hint(messages, txt):                      # 失败把报错喂回去重试
        return messages + [{"role": "user", "content": f"上次输出无法解析为目标JSON：{txt[:120]}。只输出合法JSON，别加任何解释。"}]

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
        msgs, fails = messages, 0
        for attempt in range(retry + 1):
            t0 = time.time()
            data = self.sync.post("/api/chat", json=self._body(msgs, schema, temp)).json()
            obj, fails = self._validate(data, schema, round((time.time() - t0) * 1000), tag, attempt, fails)
            if obj is not None:
                return obj
            msgs = self._retry_hint(messages, data.get("message", {}).get("content", ""))
        return None

    async def achat(self, messages, schema: Type[T], tag: str = "", retry: int = 2, temp=None) -> T | None:
        async with self._gate():                        # 整次调用(含重试)占一个名额
            msgs, fails = messages, 0
            for attempt in range(retry + 1):
                t0 = time.time()
                data = (await self.aclient.post("/api/chat", json=self._body(msgs, schema, temp))).json()
                obj, fails = self._validate(data, schema, round((time.time() - t0) * 1000), tag, attempt, fails)
                if obj is not None:
                    return obj
                msgs = self._retry_hint(messages, data.get("message", {}).get("content", ""))
            return None
