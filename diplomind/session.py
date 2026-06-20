"""人机对局会话 — 全员对等轮次同步。人/AI 共用 Player.negotiate/decide 接口,
仅输入源不同(前端 future vs LLM)。后端控流程:发言/跳过/等齐/推进/下令/结算。
"""
from __future__ import annotations

import asyncio
import logging
import os

from .agent import Agent
from .bus import MessageBus
from .chronicle import generate
from .engine import OperationEngine
from .gateway import Gateway
from .personalities import PERSONAS
from .players import AIPlayer, HumanPlayer
from .schemas import Message

log = logging.getLogger("diplomind")
logging.basicConfig(level=logging.DEBUG if os.getenv("DIPLOMIND_DEBUG") else logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]
MAX_ROUNDS = 5


class Session:
    def __init__(self, human: str | None = "FRANCE") -> None:
        self.human = human
        self.gw = Gateway()
        self.eng = OperationEngine(POWERS)
        self.players = {c: (HumanPlayer(c) if c == human else
                            AIPlayer(Agent(c, list(PERSONAS.values())[i], self.gw)))
                        for i, c in enumerate(POWERS)}
        self.ai = {c: p.agent for c, p in self.players.items() if isinstance(p, AIPlayer)}
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"
        self.chronicle: list[str] = []; self._opened: set[str] = set()
        self._done: dict[str, object] = {}; self._committed: set[int] = set()

    async def begin_phase(self) -> None:
        await asyncio.gather(*(p.cognition(self.eng) for p in self.ai_players()))  # AI 私有认知
        self._start_round()

    def ai_players(self):
        return [p for p in self.players.values() if isinstance(p, AIPlayer)]

    def _start_round(self) -> None:
        self._done = {}
        ib = {c: self.bus.inbox(c, self.round - 1) for c in self.players}
        for c, p in self.players.items():
            asyncio.ensure_future(self._run(c, p, ib[c]))   # 每个玩家(人/AI)同样 await act

    async def _run(self, c, p, inbox):
        self._done[c] = await p.negotiate(self.eng, inbox)  # AI 即返, 人阻塞到前端提交
        await self._maybe_advance()

    def pending(self) -> list[str]:
        return [c for c in self.players if c not in self._done]

    async def human_say(self, scope, recipient, content, skip=False) -> dict:
        p = self.players.get(self.human)
        if self.mode != "NEGO" or not p._msg or p._msg.done():     # 没轮到/本轮已操作 → 拒
            return {"ok": False, "reason": "还没轮到你/本轮已操作"}
        if not skip and not content.strip():                       # 空消息不发
            return {"ok": False, "reason": "不能发空消息"}
        self.players[self.human].submit_msg(None if skip else Message(type=scope, recipient=recipient, content=content))
        return {"ok": True}

    def your_turn(self) -> bool:
        p = self.players.get(self.human)
        return bool(self.mode == "NEGO" and p and getattr(p, "_msg", None) and not p._msg.done())

    async def _maybe_advance(self) -> None:
        if self.pending() or self.round in self._committed:
            return
        self._committed.add(self.round)
        for c, m in self._done.items():
            if m and m.content.strip():
                self.bus.post(self.round, c, m.type, m.recipient, m.content)
        log.info("R%d 齐, 投递推进; 静默=%s", self.round, self.bus.round_silent(self.round))
        self.round += 1
        if self.round > MAX_ROUNDS or self.bus.round_silent(self.round - 1):
            self.mode = "ORDERS"; log.info("转下令")
        else:
            self._start_round()

    def open_private(self, recipients) -> str:
        key = "·".join(sorted({self.human, *[r.upper() for r in recipients]})); self._opened.add(key); return key

    def legal(self) -> list[str]:
        return sorted({o for v in self.eng.legal_orders(self.human).values() for o in v}) if self.human else []

    async def submit(self, human_orders) -> dict:
        if self.human:
            self.eng.submit(self.human, [o for o in human_orders if o in self.eng_legal(self.human)])
        ai = self.ai_players()
        outs = await asyncio.gather(*(p.decide(self.eng) for p in ai))   # AI 走同一 decide 接口
        for p, chosen in zip(ai, outs):
            self.eng.submit(p.country, chosen)
        nxt = self.eng.process()
        while self.eng.phase_type() != "M" and not self.eng.is_done():
            self.eng.auto_resolve(); nxt = self.eng.process()
        log.info("结算 -> %s", nxt)
        self.chronicle.append(generate(self.bus, nxt, self.eng.centers()))
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"; self._committed = set()
        for a in self.ai.values(): a.mem.tick()
        return {"phase": nxt, "end": self.eng.check_end()}

    def eng_legal(self, c):
        return {o for v in self.eng.legal_orders(c).values() for o in v}

    def state(self) -> dict:
        chans = self.bus.channels(self.human, self.round) if self.human else {}
        for k in self._opened: chans.setdefault(k, [])
        return {"human": self.human, "phase": self.eng.phase(), "mode": self.mode, "round": self.round,
                "pending": self.pending(), "human_done": self.human not in self.pending(), "your_turn": self.your_turn(),
                "centers": self.eng.centers(), "channels": chans,
                "legal": self.legal() if self.mode == "ORDERS" else []}


class Msg:
    def __init__(self, scope, to, content): self.scope, self.to, self.content = scope, to, content
