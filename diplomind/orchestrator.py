"""Orchestrator — one round: intent->negotiate(<=5)->orders->process.

7 powers concurrent per round via asyncio.gather; deliver at round end."""
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
        await asyncio.gather(*(a.a_update(self.eng) for a in self.agents.values()))   # attitude first
        await asyncio.gather(*(a.a_intent(self.eng) for a in self.agents.values()))
        for rnd in range(1, MAX_ROUNDS + 1):
            inboxes = {c: self.bus.inbox(c, rnd - 1) for c in self.agents}
            msgs = await asyncio.gather(*(a.a_negotiate(self.eng, inboxes[c]) for c, a in self.agents.items()))
            for c, m in zip(self.agents, msgs):
                if m:
                    self.bus.post(rnd, c, m.type, m.recipient, m.content)
            if self.bus.round_silent(rnd):   # all silent -> stop early
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
        for a in self.agents.values():           # end-of-round commitment tick
            a.mem.tick()
        out["nego_rounds"] = stop
        return out

    async def run_phase(self) -> dict:
        """Movement=full negotiate+orders; retreat/build=engine auto."""
        if self.eng.phase_type() == "M":
            self.bus = MessageBus()
            return await self.run_round()
        self.eng.auto_resolve()
        return {"phase": self.eng.process(), "auto": True}

    async def run_game(self, max_phases: int = 6, max_year: int = 1910) -> dict:
        log = []
        for _ in range(max_phases):
            log.append(await self.run_phase())
            end = self.eng.check_end(max_year)
            if end:
                return {"end": end, "phases": len(log)}
        return {"end": None, "phases": len(log), "centers": self.eng.centers()}
