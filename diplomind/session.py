"""人机对局会话 — 1 人 + 6 AI(或全AI观战)。人操一国，谈判发言/下令点选；AI 异步陪跑。

流程：每移动相 NEGO(≤5轮，人发言→AI回) → ORDERS(人点合法令→6AI下令→结算) → 下一相。
撤退/造兵相引擎兜底。复用 Agent/Engine/Bus/Chronicle/Orchestrator 已成件。
"""
from __future__ import annotations

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
        self.human = human                    # None=全AI观战
        self.gw = Gateway()
        self.eng = OperationEngine(POWERS)
        self.ai = {c: Agent(c, list(PERSONAS.values())[i], self.gw)
                   for i, c in enumerate(POWERS) if c != human}
        self.bus = MessageBus()
        self.round = 1
        self.mode = "NEGO"
        self.chronicle: list[str] = []

    # 谈判前 AI 评态度+定意图
    async def begin_phase(self) -> None:
        import asyncio
        await asyncio.gather(*(a.a_update(self.eng) for a in self.ai.values()))
        await asyncio.gather(*(a.a_intent(self.eng) for a in self.ai.values()))

    def human_say(self, scope: str, recipient: list[str], content: str) -> None:
        if self.human:
            self.bus.post(self.round, self.human, scope, recipient, content)

    async def ai_round(self) -> int:
        """AI 各发一条→投递，轮次推进；满5轮或全静默转下令。"""
        import asyncio
        inboxes = {c: self.bus.inbox(c, self.round - 1) for c in self.ai}
        msgs = await asyncio.gather(*(a.a_negotiate(self.eng, inboxes[c]) for c, a in self.ai.items()))
        for c, m in zip(self.ai, msgs):
            if m:
                self.bus.post(self.round, c, m.type, m.recipient, m.content)
        self.round += 1
        if self.round > MAX_ROUNDS:
            self.mode = "ORDERS"
        return self.round - 1

    def legal(self) -> list[str]:
        if not self.human:
            return []
        return sorted({o for v in self.eng.legal_orders(self.human).values() for o in v})

    async def submit(self, human_orders: list[str]) -> dict:
        import asyncio
        if self.human:
            ok = set(self.legal())
            self.eng.submit(self.human, [o for o in human_orders if o in ok])
        res = await asyncio.gather(*(a.a_decide_orders(self.eng) for a in self.ai.values()))
        for c, (_, chosen) in zip(self.ai, res):
            self.eng.submit(c, chosen)
        nxt = self.eng.process()
        while self.eng.phase_type() != "M" and not self.eng.is_done():
            self.eng.auto_resolve(); nxt = self.eng.process()   # 撤退/造兵兜底
        self.chronicle.append(generate(self.bus, nxt, self.eng.centers()))
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"
        for a in self.ai.values():
            a.mem.tick()
        return {"phase": nxt, "end": self.eng.check_end()}

    def state(self) -> dict:
        return {"human": self.human, "phase": self.eng.phase(), "mode": self.mode,
                "round": self.round, "centers": self.eng.centers(),
                "inbox": self.bus.inbox(self.human, self.round) if self.human else "",
                "legal": self.legal()}
