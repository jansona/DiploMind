"""人机对局会话 — 全员对等的轮次同步谈判。

每轮：6AI 后台并发各拟一条(自主选群发/私聊)，人同时编辑；人点发送/跳过。
人+AI 都齐 → 打包投递 → 下一轮。人静默不挡 AI。满5轮或全员静默 → 下令。
人可见谁还没发(pending)、当前第几轮。撤退/造兵相引擎兜底。
"""
from __future__ import annotations

import asyncio
import logging
import os

from .agent import Agent

log = logging.getLogger("diplomind")
logging.basicConfig(level=logging.DEBUG if os.getenv("DIPLOMIND_DEBUG") else logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
from .bus import MessageBus
from .chronicle import generate
from .engine import OperationEngine
from .gateway import Gateway
from .personalities import PERSONAS

POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]
MAX_ROUNDS = 5


class Session:
    def __init__(self, human: str | None = "FRANCE") -> None:
        self.human = human
        self.gw = Gateway()
        self.eng = OperationEngine(POWERS)
        self.ai = {c: Agent(c, list(PERSONAS.values())[i], self.gw)
                   for i, c in enumerate(POWERS) if c != human}
        self.bus = MessageBus()
        self.round = 1
        self.mode = "NEGO"
        self.chronicle: list[str] = []
        self._ai_task: asyncio.Task | None = None
        self._ai_msgs: dict[str, object] = {}     # 本轮 AI 待投递
        self.human_done = human is None
        self._silent_streak = 0
        self._committed: set[int] = set()         # 已结算轮次, 防重复推进
        self._opened: set[str] = set()            # 人手动开过的私聊频道(空也保留)

    async def begin_phase(self) -> None:
        await asyncio.gather(*(a.a_update(self.eng) for a in self.ai.values()))
        await asyncio.gather(*(a.a_intent(self.eng) for a in self.ai.values()))
        self._start_ai_round()

    def _start_ai_round(self) -> None:
        self._ai_msgs, self.human_done = {}, self.human is None
        ib = {c: self.bus.inbox(c, self.round - 1) for c in self.ai}
        self._ai_task = asyncio.ensure_future(self._gen(ib))
        log.debug("R%d start: AI 拟言中, human_done=%s", self.round, self.human_done)

    async def _gen(self, ib) -> None:
        outs = await asyncio.gather(*(a.a_negotiate(self.eng, ib[c]) for c, a in self.ai.items()))
        self._ai_msgs = {c: m for c, m in zip(self.ai, outs)}
        log.debug("R%d AI 拟言完成, pending=%s", self.round, self.pending())
        await self._maybe_advance()                # AI 跑完也来判一次, 否则人先发会卡死

    def pending(self) -> list[str]:
        p = [] if (self._ai_task and self._ai_task.done()) else list(self.ai)
        return ([] if self.human_done else [self.human]) + p

    async def human_say(self, scope: str, recipient: list[str], content: str, skip: bool = False) -> None:
        if self.human_done:                        # 本轮已操作, 重复发送幂等忽略
            log.debug("R%d 人重复操作被忽略", self.round); return
        if self.human and not skip and content.strip():
            self.bus.post(self.round, self.human, scope, recipient, content)
        self.human_done = True
        log.debug("R%d 人%s, pending=%s", self.round, "跳过" if skip else "发言", self.pending())
        await self._maybe_advance()

    async def _maybe_advance(self) -> None:
        if self.pending() or self.round in self._committed:   # 没齐 / 已结算 → 不重复推进
            return
        self._committed.add(self.round)
        log.info("R%d 齐, 投递推进; 静默=%s", self.round, self.bus.round_silent(self.round))
        for c, m in self._ai_msgs.items():         # AI 本轮投递
            if m:
                self.bus.post(self.round, c, m.type, m.recipient, m.content)
        self._silent_streak = self._silent_streak + 1 if self.bus.round_silent(self.round) else 0
        self.round += 1
        if self.round > MAX_ROUNDS or self._silent_streak >= 1:
            self.mode = "ORDERS"; log.info("转下令 (满%d轮/静默)", MAX_ROUNDS)
        else:
            self._start_ai_round()

    def open_private(self, recipients: list[str]) -> str:
        key = "·".join(sorted({self.human, *[r.upper() for r in recipients]}))
        self._opened.add(key)
        return key

    def legal(self) -> list[str]:
        return sorted({o for v in self.eng.legal_orders(self.human).values() for o in v}) if self.human else []

    async def submit(self, human_orders: list[str]) -> dict:
        if self.human:
            ok = set(self.legal())
            self.eng.submit(self.human, [o for o in human_orders if o in ok])
        res = await asyncio.gather(*(a.a_decide_orders(self.eng) for a in self.ai.values()))
        for c, (_, chosen) in zip(self.ai, res):
            self.eng.submit(c, chosen)
        nxt = self.eng.process()
        while self.eng.phase_type() != "M" and not self.eng.is_done():
            self.eng.auto_resolve(); nxt = self.eng.process()
        log.info("结算 -> %s, 中心=%s", nxt, self.eng.centers())
        self.chronicle.append(generate(self.bus, nxt, self.eng.centers()))
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"; self._silent_streak = 0; self._committed = set()
        for a in self.ai.values():
            a.mem.tick()
        return {"phase": nxt, "end": self.eng.check_end()}

    def state(self) -> dict:
        chans = self.bus.channels(self.human, self.round) if self.human else {}
        for k in self._opened:                       # 人开过的空私聊也回, 前端不必本地存
            chans.setdefault(k, [])
        return {"human": self.human, "phase": self.eng.phase(), "mode": self.mode,
                "round": self.round, "pending": self.pending(), "human_done": self.human_done,
                "centers": self.eng.centers(), "channels": chans,
                "powers": [p for p in self.eng.active_powers if p != self.human],
                "legal": self.legal() if self.mode == "ORDERS" else []}
