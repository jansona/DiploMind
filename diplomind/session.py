"""人机对局会话 — 全员对等的轮次同步谈判。

每轮：6AI 后台并发各拟一条(自主选群发/私聊)，人同时编辑；人点发送/跳过。
人+AI 都齐 → 打包投递 → 下一轮。人静默不挡 AI。满5轮或全员静默 → 下令。
人可见谁还没发(pending)、当前第几轮。撤退/造兵相引擎兜底。
"""
from __future__ import annotations

import asyncio

from .agent import Agent
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

    async def begin_phase(self) -> None:
        await asyncio.gather(*(a.a_update(self.eng) for a in self.ai.values()))
        await asyncio.gather(*(a.a_intent(self.eng) for a in self.ai.values()))
        self._start_ai_round()

    def _start_ai_round(self) -> None:
        self._ai_msgs, self.human_done = {}, self.human is None
        ib = {c: self.bus.inbox(c, self.round - 1) for c in self.ai}
        self._ai_task = asyncio.ensure_future(self._gen(ib))

    async def _gen(self, ib) -> None:
        outs = await asyncio.gather(*(a.a_negotiate(self.eng, ib[c]) for c, a in self.ai.items()))
        self._ai_msgs = {c: m for c, m in zip(self.ai, outs)}

    def pending(self) -> list[str]:
        p = [] if (self._ai_task and self._ai_task.done()) else list(self.ai)
        return ([] if self.human_done else [self.human]) + p

    async def human_say(self, scope: str, recipient: list[str], content: str, skip: bool = False) -> None:
        if self.human and not skip:
            self.bus.post(self.round, self.human, scope, recipient, content)
        self.human_done = True
        await self._maybe_advance()

    async def _maybe_advance(self) -> None:
        if self.pending():                         # 还有人没发，等
            return
        any_msg = bool(self.human and not self.human_done) or any(self._ai_msgs.values())
        for c, m in self._ai_msgs.items():         # AI 本轮投递
            if m:
                self.bus.post(self.round, c, m.type, m.recipient, m.content)
        self._silent_streak = self._silent_streak + 1 if self.bus.round_silent(self.round) else 0
        self.round += 1
        if self.round > MAX_ROUNDS or self._silent_streak >= 1:
            self.mode = "ORDERS"
        else:
            self._start_ai_round()

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
        self.chronicle.append(generate(self.bus, nxt, self.eng.centers()))
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"; self._silent_streak = 0
        for a in self.ai.values():
            a.mem.tick()
        return {"phase": nxt, "end": self.eng.check_end()}

    def state(self) -> dict:
        return {"human": self.human, "phase": self.eng.phase(), "mode": self.mode,
                "round": self.round, "pending": self.pending(), "centers": self.eng.centers(),
                "inbox": self.bus.inbox(self.human, self.round, include_self=True) if self.human else "",
                "legal": self.legal() if self.mode == "ORDERS" else []}
