"""编排器 Orchestrator — 一回合闭环：意图→谈判(≤5轮,全员静默提前止)→下令→结算。

七国并发：每轮 asyncio.gather，各国基于上一轮快照同时写，轮末统一投递。"""
from __future__ import annotations

import asyncio

from .agent import Agent
from .bus import MessageBus
from .engine import OperationEngine

MAX_ROUNDS = 5


class Orchestrator:
    def __init__(self, eng: OperationEngine, agents: dict[str, Agent]) -> None:
        self.eng, self.agents, self.bus = eng, agents, MessageBus()

    async def negotiate(self) -> int:
        await asyncio.gather(*(a.a_update(self.eng) for a in self.agents.values()))   # 先评态度
        await asyncio.gather(*(a.a_intent(self.eng) for a in self.agents.values()))
        for rnd in range(1, MAX_ROUNDS + 1):
            inboxes = {c: self.bus.inbox(c, rnd - 1) for c in self.agents}
            msgs = await asyncio.gather(*(a.a_negotiate(self.eng, inboxes[c]) for c, a in self.agents.items()))
            for c, m in zip(self.agents, msgs):
                if m:
                    self.bus.post(rnd, c, m.type, m.recipient, m.content)
            if self.bus.round_silent(rnd):   # 全员静默 → 提前止
                return rnd
        return MAX_ROUNDS

    async def collect_and_process(self) -> dict:
        results = await asyncio.gather(*(a.a_decide_orders(self.eng) for a in self.agents.values()))
        report = {}
        for c, (out, chosen) in zip(self.agents, results):
            r = self.eng.submit(c, chosen)
            report[c] = {"orders": chosen, "rejected": r.rejected}
        nxt = self.eng.process()
        return {"phase": nxt, "orders": report, "centers": self.eng.centers()}

    async def run_round(self) -> dict:
        stop = await self.negotiate()
        out = await self.collect_and_process()
        for a in self.agents.values():           # 回合末承诺倒计时
            a.mem.tick()
        out["nego_rounds"] = stop
        return out
