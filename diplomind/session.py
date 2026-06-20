"""人机对局会话 — 全员对等轮次同步。人/AI 共用 Player.negotiate/decide 接口,
仅输入源不同(前端 future vs LLM)。后端控流程:发言/跳过/等齐/推进/下令/结算。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from pathlib import Path

from .agent import Agent
from .bus import MessageBus
from .config import load as load_config
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
MAX_ROUNDS = 3


class Session:
    def __init__(self, human: str | None = "__cfg__", max_year: int = 1910,
                 lang: str | None = None, personas: dict | None = None, cfg=None) -> None:
        cfg = cfg or load_config()
        self.human = cfg.human if human == "__cfg__" else human          # configurable; null=all-AI
        self.max_year = max_year; self.lang = lang or cfg.lang
        self.rounds = cfg.rounds                          # negotiation rounds from config
        self.gw = Gateway(model=cfg.model, base_url=cfg.base_url, api_key=cfg.api_key,
                          api=cfg.api, concurrency=cfg.concurrency, timeout=cfg.timeout)
        self.eng = OperationEngine(POWERS)
        keys = list(PERSONAS); random.shuffle(keys)                     # random by default; personas can fix per power
        chosen = {c: (personas or {}).get(c, keys[i]) for i, c in enumerate(POWERS)}
        self.persona_of = {c: PERSONAS[chosen[c]].name for c in POWERS if c != self.human}  # human has no persona
        self.players = {c: (HumanPlayer(c) if c == human else
                            AIPlayer(Agent(c, PERSONAS[chosen[c]], self.gw, self.lang)))
                        for c in POWERS}
        self.ai = {c: p.agent for c, p in self.players.items() if isinstance(p, AIPlayer)}
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"
        self.chronicle: list[str] = []; self._opened: set[str] = set()
        self._done: dict[str, object] = {}; self._committed: set[int] = set(); self._cog = False

    async def begin_phase(self) -> None:
        self._cog = False
        self._start_round()                          # start round now: human can act; AI cognition parallel

    def ai_players(self):
        return [p for p in self.players.values() if isinstance(p, AIPlayer)]

    def _start_round(self) -> None:
        self._done = {}                                  # per-round submissions
        ib = {c: self.bus.inbox(c, self.round - 1) for c in self.ai}
        for c, p in self.ai.items():
            asyncio.ensure_future(self._run(c, p, ib[c]))   # AIs draft in parallel

    async def _run(self, c, agent, inbox):
        if not self._cog: await agent.a_update(self.eng); await agent.a_intent(self.eng)  # private cognition, parallel to human
        self._done[c] = await agent.a_negotiate(self.eng, inbox)
        await self._maybe_advance()

    def pending(self) -> list[str]:
        return [c for c in self.players if c not in self._done]   # who hasn't acted

    async def human_say(self, scope, recipient, content, skip=False) -> dict:
        if self.mode != "NEGO" or self.human in self._done:        # already acted -> reject
            return {"ok": False, "reason": "本轮已发言/跳过, 等其他玩家"}
        if not skip and not content.strip():
            return {"ok": False, "reason": "不能发空消息"}
        self._done[self.human] = None if skip else Message(type=scope, recipient=recipient, content=content)
        await self._maybe_advance()
        return {"ok": True}

    def your_turn(self) -> bool:                          # can speak this round (independent of AI)
        return self.mode == "NEGO" and self.human is not None and self.human not in self._done

    async def _maybe_advance(self) -> None:
        if self.pending() or self.round in self._committed:
            return
        self._committed.add(self.round)
        for c, m in self._done.items():
            if m and m.content.strip():
                self.bus.post(self.round, c, m.type, m.recipient, m.content)
        log.info("R%d 齐, 投递推进; 静默=%s", self.round, self.bus.round_silent(self.round))
        self.round += 1; self._cog = True            # cognition once per phase
        if self.round > self.rounds or self.bus.round_silent(self.round - 1):
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
        if self.eng.phase_type() == "M":                 # movement: AI LLM orders; retreat/build: AI auto
            ai = self.ai_players()
            outs = await asyncio.gather(*(p.decide(self.eng) for p in ai))
            for p, chosen in zip(ai, outs):
                self.eng.submit(p.country, chosen)
        else:
            self.eng.auto_resolve(except_=self.human)    # retreat/build: AI auto, human chose
        before = {c: set(self.eng.game.powers[c].centers) for c in POWERS}
        nxt = self.eng.process()
        self._detect_betrayal(before)                # capturing ally center=betrayal
        # retreat/build: AI auto; stop for human if legal, else next movement
        while self.eng.phase_type() != "M" and not self.eng.is_done():
            if self.human and self.legal():
                self.mode = "ORDERS"; return {"phase": nxt, "build": True, "end": None}
            self.eng.auto_resolve(); nxt = self.eng.process()
        log.info("结算 -> %s", nxt)
        self.chronicle.append(generate(self.bus, nxt, self.eng.centers()))
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"; self._committed = set()
        for a in self.ai.values(): a.mem.tick()
        return {"phase": nxt, "end": self.eng.check_end(self.max_year)}

    def eng_legal(self, c):
        return {o for v in self.eng.legal_orders(c).values() for o in v}

    def _detect_betrayal(self, before: dict) -> None:
        """center captured=attack; if attacker was ally(trust>20)->betrayal+trust crash."""
        yr = int("".join(filter(str.isdigit, self.eng.phase())) or 0)
        for victim in POWERS:
            lost = before[victim] - set(self.eng.game.powers[victim].centers)
            for cen in lost:
                taker = next((c for c in POWERS if cen in self.eng.game.powers[c].centers), None)
                if not taker or taker == victim or taker not in self.ai:
                    continue
                vm = self.ai[victim].mem if victim in self.ai else None
                ally = vm and vm.relation(taker).trust > 20
                if vm:
                    vm.record_action(yr, taker, f"夺{cen}", betray=bool(ally))
                    if ally: vm.apply_attitude({taker: {"trust": -80, "attitude": "叛徒"}})  # hold grudge

    SAVE = Path("logs") / "save.json"

    def save(self) -> dict:                              # save: board+chronicle+memories
        blob = {"human": self.human, "max_year": self.max_year, "lang": self.lang, "board": self.eng.save(),
                "chronicle": self.chronicle, "persona": self.persona_of,
                "mem": {c: a.mem.snapshot() for c, a in self.ai.items()}}
        self.SAVE.write_text(json.dumps(blob, ensure_ascii=False)); return {"saved": str(self.SAVE)}

    @classmethod
    def load(cls) -> "Session":
        b = json.loads(cls.SAVE.read_text())
        s = cls(b["human"], b["max_year"], b.get("lang", "zh-Hans")); s.eng.load(b["board"]); s.chronicle = b["chronicle"]
        s.persona_of = b["persona"]
        return s

    def state(self) -> dict:
        chans = self.bus.channels(self.human, self.round) if self.human else {}
        for k in self._opened: chans.setdefault(k, [])
        return {"human": self.human, "phase": self.eng.phase(), "mode": self.mode, "round": self.round,
                "pending": self.pending(), "human_done": self.human in self._done, "your_turn": self.your_turn(),
                "staged": (self._done[self.human].content if self._done.get(self.human) else "") if self.human in self._done else "",
                "centers": self.eng.centers(), "channels": chans, "lang": self.lang,  # persona hidden; debug only
                "phase_type": self.eng.phase_type(),
                # ORDERS phase: who still owes orders (human until submit; 6 AI decide on submit)
                "order_pending": ([self.human] if self.human else []) + sorted(self.ai) if self.mode == "ORDERS" else [],
                "legal": self.legal() if self.mode == "ORDERS" else []}


class Msg:
    def __init__(self, scope, to, content): self.scope, self.to, self.content = scope, to, content
