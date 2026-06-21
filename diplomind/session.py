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
from .chronicle import generate, summarize_year
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
        h = cfg.human if human == "__cfg__" else human
        self.humans = [h] if isinstance(h, str) else list(h or [])       # 0/1/many humans, any power
        self.human = self.humans[0] if self.humans else None             # primary (single-player UI compat)
        self.max_year = max_year; self.lang = lang or cfg.lang
        self.rounds = cfg.rounds                          # negotiation rounds from config
        self.gw = Gateway(model=cfg.model, base_url=cfg.base_url, api_key=cfg.api_key,
                          api=cfg.api, concurrency=cfg.concurrency, timeout=cfg.timeout)
        self.eng = OperationEngine(POWERS)
        keys = list(PERSONAS); random.shuffle(keys)                     # random by default; personas can fix per power
        self.persona_key = {c: (personas or {}).get(c, keys[i]) for i, c in enumerate(POWERS)}
        self.persona_of = {c: PERSONAS[self.persona_key[c]].name for c in POWERS if c not in self.humans}
        self.players = {c: (HumanPlayer(c) if c in self.humans else      # humans not built as AI
                            AIPlayer(Agent(c, PERSONAS[self.persona_key[c]], self.gw, self.lang)))
                        for c in POWERS}
        self.ai = {c: p.agent for c, p in self.players.items() if isinstance(p, AIPlayer)}
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"
        self.chronicle: list[str] = []; self._opened: set[str] = set()
        self._done: dict[str, object] = {}; self._hmsgs: dict = {}; self._committed: set[int] = set(); self._cog = False

    async def begin_phase(self) -> None:
        self._cog = False
        self._start_round()                          # start round now: human can act; AI cognition parallel

    def ai_players(self):
        return [p for p in self.players.values() if isinstance(p, AIPlayer)]

    def _start_round(self) -> None:
        self._done = {}; self._hmsgs = {}                # per-round submissions (human up to 3 msgs)
        ib = {c: self.bus.inbox(c, self.round - 1) for c in self.ai}
        for c, p in self.ai.items():
            asyncio.ensure_future(self._run(c, p, ib[c]))   # AIs draft in parallel

    async def _run(self, c, agent, inbox):
        if not self._cog: await agent.a_update(self.eng); await agent.a_intent(self.eng)  # private cognition, parallel to human
        self._done[c] = await agent.a_negotiate(self.eng, inbox)
        await self._maybe_advance()

    def pending(self) -> list[str]:
        return [c for c in self.players if c not in self._done]   # who hasn't acted

    MSGS_PER_ROUND = 3                                    # each player can send up to 3 msgs/round (multi-channel)

    async def human_say(self, scope, recipient, content, skip=False) -> dict:
        if self.mode != "NEGO" or self.human in self._done:        # already acted -> reject
            return {"ok": False, "reason": "本轮已发言/跳过, 等其他玩家"}
        if not skip and not content.strip():
            return {"ok": False, "reason": "不能发空消息"}
        if not skip:
            self._hmsgs.setdefault(self.human, []).append(Message(type=scope, recipient=recipient, content=content))
        if skip or len(self._hmsgs.get(self.human, [])) >= self.MSGS_PER_ROUND:
            self._done[self.human] = self._hmsgs.get(self.human) or None   # done after skip or 3 msgs
            await self._maybe_advance()
        return {"ok": True, "sent": len(self._hmsgs.get(self.human, []))}

    def your_turn(self) -> bool:                          # can speak (<3 msgs, not done) this round
        return self.mode == "NEGO" and self.human is not None and self.human not in self._done

    async def _maybe_advance(self) -> None:
        if self.pending() or self.round in self._committed:
            return
        self._committed.add(self.round)
        for c, v in self._done.items():
            for m in (v if isinstance(v, list) else [v]):   # human may stage up to 3, AI one
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
        pub = [f"{m.sender}: {m.text}" for m in self.bus.msgs if m.scope == "broadcast"]
        try:                                              # AI yearly summary (alliances/enmities/troops), same LLM
            self.chronicle.append(await summarize_year(self.gw, nxt[:5], pub, self.eng.centers(), self.lang))
        except Exception:
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

    SAVES = Path("logs") / "saves"

    @classmethod
    def list_saves(cls) -> list[str]:
        return sorted(p.stem for p in cls.SAVES.glob("*.json")) if cls.SAVES.exists() else []

    def save(self, name: str = "auto") -> dict:          # save slot: board+chronicle+memories
        self.SAVES.mkdir(parents=True, exist_ok=True)
        blob = {"human": self.human, "max_year": self.max_year, "lang": self.lang, "board": self.eng.save(),
                "chronicle": self.chronicle, "persona_key": self.persona_key, "round": self.round, "mode": self.mode,
                "msgs": [vars(m) for m in self.bus.msgs],   # chat history (incl private)
                "mem": {c: a.mem.snapshot() for c, a in self.ai.items()}}
        (self.SAVES / f"{name}.json").write_text(json.dumps(blob, ensure_ascii=False)); return {"saved": name}

    @classmethod
    def load(cls, name: str = "auto") -> "Session":
        b = json.loads((cls.SAVES / f"{name}.json").read_text())
        s = cls(b["human"], b["max_year"], b.get("lang", "zh-Hans"), personas=b.get("persona_key"))  # same personas
        s.eng.load(b["board"]); s.chronicle = b["chronicle"]
        s.round = b.get("round", 1); s.mode = b.get("mode", "NEGO")
        for m in b.get("msgs", []):                      # restore chat history
            s.bus.post(m["rnd"], m["sender"], m["scope"], m["to"], m["text"])
        for c, snap in (b.get("mem") or {}).items():     # restore AI memory (relations/actions/diary)
            if c in s.ai:
                s.ai[c].mem.restore(snap)
        return s

    def state(self) -> dict:
        chans = self.bus.channels(self.human, self.round) if self.human else {}
        for k in self._opened: chans.setdefault(k, [])
        return {"human": self.human, "phase": self.eng.phase(), "mode": self.mode, "round": self.round,
                "pending": self.pending(), "human_done": self.human in self._done, "your_turn": self.your_turn(),
                "sent": len(self._hmsgs.get(self.human, [])), "staged": "已发%d/3" % len(self._hmsgs.get(self.human, [])),
                "centers": self.eng.centers(), "channels": chans, "lang": self.lang,  # persona hidden; debug only
                "phase_type": self.eng.phase_type(),
                # ORDERS phase: who still owes orders (human until submit; 6 AI decide on submit)
                "order_pending": ([self.human] if self.human else []) + sorted(self.ai) if self.mode == "ORDERS" else [],
                "legal": self.legal() if self.mode == "ORDERS" else []}


class Msg:
    def __init__(self, scope, to, content): self.scope, self.to, self.content = scope, to, content
