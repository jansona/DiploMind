"""人机对局会话 — 全员对等轮次同步。人/AI 共用 Player.negotiate/decide 接口,
仅输入源不同(前端 vs LLM)。后端控流程:发言/跳过/等齐/推进/下令/结算。
多座位: 0/1/多人, 各座位独立发言计数与下令; 满座等齐才推进。单人 API(human_say/submit)= 主座位糖衣。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
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


def spawn(coro):                                         # fire-and-forget but surface crashes, don't fail silently
    t = asyncio.ensure_future(coro)
    t.add_done_callback(lambda f: f.cancelled() or f.exception() and log.error("后台任务异常: %s", f.exception()))
    return t


class Session:
    def __init__(self, human: str | None = "__cfg__", max_year: int | None = None,
                 lang: str | None = None, personas: dict | None = None, cfg=None) -> None:
        cfg = cfg or load_config()
        h = cfg.human if human == "__cfg__" else human
        self.humans = [h] if isinstance(h, str) else list(h or [])       # 0/1/many humans, any power
        self.human = self.humans[0] if self.humans else None             # primary (single-player UI compat)
        self.max_year = min(1910, max_year or cfg.max_year); self.lang = lang or cfg.lang
        self.end_rule = cfg.end_rule                      # topcount=most centers wins; draw=all survivors draw
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
        self.chronicle: list[str] = []; self._chron_idx = 0   # bus msgs already covered by past chronicle entries
        self._opened: dict[str, set] = {}                 # opener-only pre-opened tabs (recipient sees on first msg)
        self.history: list[dict] = [{"phase": self.eng.phase(), **self.eng.centers()}]  # center counts per phase, for chart
        self._done: dict[str, object] = {}; self._hmsgs: dict = {}; self._committed: set[int] = set(); self._cog = False
        self._horders: dict[str, list[str]] = {}; self._settling = False   # per-human submitted orders; settle once
        self._ai_task = None; self._ai_squad: list = []    # AI orders drafted concurrently w/ humans during ORDERS

    async def begin_phase(self) -> None:
        self._cog = False
        self._start_round()                          # start round now: human can act; AI cognition parallel

    def ai_players(self):
        return [p for p in self.players.values() if isinstance(p, AIPlayer)]

    def _end(self):
        return self.eng.check_end(self.max_year, draw_all=self.end_rule == "draw")

    def ended(self) -> bool:                     # game decided: solo win / year-cap ruling
        return bool(self._end())

    def close(self) -> None:                     # release gateway httpx clients (room reaped)
        self.gw.close()

    def aiify(self, power: str) -> bool:
        """Kick/abandon: a human seat becomes AI using its pre-assigned persona + blank memory."""
        if power not in self.humans:
            return False
        self.humans.remove(power); self.human = self.humans[0] if self.humans else None
        agent = Agent(power, PERSONAS[self.persona_key[power]], self.gw, self.lang)
        self.players[power] = AIPlayer(agent); self.ai[power] = agent; self.persona_of[power] = agent.persona.name
        self._done.setdefault(power, None); self._horders.pop(power, None)   # unblock current round
        try:
            asyncio.get_running_loop()
        except RuntimeError:                                                 # no loop (sync test): advance lazily
            return True
        if self.mode == "NEGO":
            spawn(self._maybe_advance())                                     # AI takes over next round
        elif self.mode == "ORDERS" and all(p in self._horders for p in self.humans):
            spawn(self._settle_continue())                                   # kicked seat was the last holdout
        return True

    async def _settle_continue(self) -> None:            # settle + roll into next phase (same rule as web /api/orders)
        res = await self.settle()
        if res.get("phase") and not res.get("build") and not res.get("end"):
            await self.begin_phase()

    def _start_round(self) -> None:
        self._done = {}; self._hmsgs = {}                # per-round submissions (human up to 3 msgs)
        ib = {c: self.bus.inbox(c, self.round - 1, phase=self.eng.phase()) for c in self.ai}
        for c, p in self.ai.items():
            spawn(self._run(c, p, ib[c]))   # AIs draft in parallel

    async def _run(self, c, agent, inbox):
        if not self._cog: await agent.a_update(self.eng); await agent.a_intent(self.eng)  # private cognition, parallel to human
        self._done[c] = await agent.a_negotiate(self.eng, inbox)
        await self._maybe_advance()

    def pending(self) -> list[str]:
        return [c for c in self.players if c not in self._done]   # who hasn't acted

    MSGS_PER_ROUND = 3                                    # each player can send up to 3 msgs/round (multi-channel)

    async def say(self, power, scope, recipient, content, skip=False) -> dict:
        """One seat speaks/skips. power must be a human seat. Done after skip or 3 msgs."""
        if power not in self.humans:
            return {"ok": False, "reason": "非人类座位"}
        if self.mode != "NEGO" or power in self._done:            # already acted -> reject
            return {"ok": False, "reason": "本轮已发言/跳过, 等其他玩家"}
        if not skip and not content.strip():
            return {"ok": False, "reason": "不能发空消息"}
        if not skip:
            self._hmsgs.setdefault(power, []).append(Message(type=scope, recipient=recipient, content=content))
        if skip or len(self._hmsgs.get(power, [])) >= self.MSGS_PER_ROUND:
            self._done[power] = self._hmsgs.get(power) or None   # done after skip or 3 msgs
            await self._maybe_advance()
        return {"ok": True, "sent": len(self._hmsgs.get(power, []))}

    async def human_say(self, scope, recipient, content, skip=False) -> dict:   # primary-seat shim
        return await self.say(self.human, scope, recipient, content, skip)

    def your_turn(self, power=None) -> bool:               # can speak (<3 msgs, not done) this round
        power = power or self.human
        return self.mode == "NEGO" and power in self.humans and power not in self._done

    async def _maybe_advance(self) -> None:
        if self.mode != "NEGO":                  # ORDERS/settling: a late aiify must not re-commit stale _done
            return
        if self.pending() or self.round in self._committed:
            return
        self._committed.add(self.round)
        ph = self.eng.phase()
        for c, v in self._done.items():
            for m in (v if isinstance(v, list) else [v]):   # human may stage up to 3, AI one
                if m and m.content.strip():
                    self.bus.post(self.round, c, m.type, m.recipient, m.content, ph)
        log.info("R%d 齐, 投递推进; 静默=%s", self.round, self.bus.round_silent(self.round, ph))
        self.round += 1; self._cog = True            # cognition once per phase
        if self.round > self.rounds or self.bus.round_silent(self.round - 1, ph):
            self.mode = "ORDERS"; self._horders = {}; log.info("转下令")
            if self.eng.phase_type() == "M":              # AI draft orders concurrently while humans pick
                self._ai_squad = self.ai_players()        # snapshot: a mid-phase aiify must not shift the zip below
                self._ai_task = spawn(asyncio.gather(*(p.decide(self.eng) for p in self._ai_squad)))
            if not self.humans:                           # all-AI spectate: auto-settle + next phase
                spawn(self._auto_spectate())
        else:
            self._start_round()

    async def _auto_spectate(self) -> None:
        await self.settle()
        if not self.eng.is_done() and not self._end():
            await self.begin_phase()

    def open_private(self, power, recipients) -> str:
        key = "·".join(sorted({power, *[r.upper() for r in recipients]}))
        self._opened.setdefault(power, set()).add(key); return key       # only opener sees empty tab; others on first msg

    def legal(self, power=None) -> list[str]:
        power = power or self.human
        return sorted({o for v in self.eng.legal_orders(power).values() for o in v}) if power else []

    async def submit_orders(self, power, orders) -> dict:
        """One human seat hands in orders. Settle once all humans submitted (or no humans)."""
        if self.mode != "ORDERS" or power not in self.humans:
            return {"ok": False, "reason": "非下令阶段/非人类座位"}
        self._horders[power] = [o for o in orders if o in self.eng_legal(power)]
        if all(p in self._horders for p in self.humans):
            return await self.settle()
        return {"ok": True, "waiting": sorted(p for p in self.humans if p not in self._horders)}

    async def submit(self, human_orders=None) -> dict:    # primary-seat shim: submit + settle
        if self.human and human_orders is not None:
            self._horders[self.human] = [o for o in human_orders if o in self.eng_legal(self.human)]
        return await self.settle()

    async def settle(self) -> dict:
        if self._settling:
            return {"ok": False, "reason": "结算中"}
        self._settling = True
        try:
            for p, o in self._horders.items():
                self.eng.submit(p, o)                     # humans' submitted orders (already legal-filtered)
            if self.eng.phase_type() == "M":              # movement: AI orders drafted in parallel since ORDERS began
                ai = self._ai_squad if self._ai_task else self.ai_players()   # seats aiified after the draft just hold
                outs = await (self._ai_task or asyncio.gather(*(p.decide(self.eng) for p in ai)))
                for p, chosen in zip(ai, outs):
                    self.eng.submit(p.country, chosen)
                self._ai_task = None; self._ai_squad = []
            else:
                self.eng.auto_resolve(except_=set(self.humans))   # retreat/build: AI auto, humans chose
            before = {c: set(self.eng.game.powers[c].centers) for c in POWERS}
            nxt = self.eng.process()
            self._detect_betrayal(before)                # capturing ally center=betrayal
            while self.eng.phase_type() != "M" and not self.eng.is_done():   # retreat/build: AI auto; stop for human
                if self.humans and any(self.legal(p) for p in self.humans):
                    self.mode = "ORDERS"; self._horders = {}; return {"phase": nxt, "build": True, "end": None}
                self.eng.auto_resolve(); nxt = self.eng.process()
            log.info("结算 -> %s", nxt)
            self.history.append({"phase": nxt, **self.eng.centers()})   # snapshot centers each phase for the chart
            pub = [f"{m.sender}: {m.text}" for m in self.bus.msgs[self._chron_idx:] if m.scope == "broadcast"]
            try:                                          # AI yearly summary (alliances/enmities/troops), same LLM
                self.chronicle.append(await summarize_year(self.gw, nxt[:5], pub, self.eng.centers(), self.lang))
            except Exception as e:                        # LLM/parse fail -> local fallback, but log why
                log.warning("年度总结失败, 回退本地: %s", e)
                self.chronicle.append(generate(self.bus, nxt, self.eng.centers(), since=self._chron_idx))
            self._chron_idx = len(self.bus.msgs)          # this phase's msgs covered; next entry starts fresh
            self.round = 1; self.mode = "NEGO"; self._committed = set(); self._horders = {}   # keep bus: cross-phase chat history
            for a in self.ai.values(): a.mem.tick()
            return {"phase": nxt, "end": self._end()}
        finally:
            self._settling = False

    def eng_legal(self, c):
        return {o for v in self.eng.legal_orders(c).values() for o in v}

    def _detect_betrayal(self, before: dict) -> None:
        """center captured=attack; if attacker was ally(trust>20)->betrayal+trust crash."""
        yr = int("".join(filter(str.isdigit, self.eng.phase())) or 0)
        for victim in POWERS:
            lost = before[victim] - set(self.eng.game.powers[victim].centers)
            for cen in lost:
                taker = next((c for c in POWERS if cen in self.eng.game.powers[c].centers), None)
                if not taker or taker == victim:                  # any taker (incl. human) holds a grudge for AI victim
                    continue
                vm = self.ai[victim].mem if victim in self.ai else None
                ally = vm and vm.relation(taker).trust > 20
                if vm:
                    vm.record_action(yr, taker, f"夺{cen}", betray=bool(ally))
                    if ally: vm.apply_attitude({taker: {"trust": -80, "attitude": "叛徒"}})  # hold grudge

    SAVES = Path("logs") / "saves"

    @staticmethod
    def _safe_name(name: str) -> str:                    # basename + whitelist: block ../ path traversal
        stem = Path(name or "auto").name
        stem = re.sub(r"[^\w.-]", "_", stem)[:64].strip(".") or "auto"
        return stem

    @classmethod
    def list_saves(cls) -> list[str]:
        return sorted(p.stem for p in cls.SAVES.glob("*.json")) if cls.SAVES.exists() else []

    def save(self, name: str = "auto") -> dict:          # save slot: board+chronicle+memories
        name = self._safe_name(name)
        self.SAVES.mkdir(parents=True, exist_ok=True)
        blob = {"human": self.human, "humans": self.humans, "max_year": self.max_year, "lang": self.lang, "end_rule": self.end_rule,
                "board": self.eng.save(), "chronicle": self.chronicle, "persona_key": self.persona_key,
                "round": self.round, "mode": self.mode, "msgs": [vars(m) for m in self.bus.msgs],   # chat history
                "history": self.history, "mem": {c: a.mem.snapshot() for c, a in self.ai.items()}}
        (self.SAVES / f"{name}.json").write_text(json.dumps(blob, ensure_ascii=False)); return {"saved": name}

    @classmethod
    def load(cls, name: str = "auto") -> "Session":
        f = cls.SAVES / f"{cls._safe_name(name)}.json"
        if not f.exists():
            raise FileNotFoundError(f"save not found: {name}")
        b = json.loads(f.read_text())
        s = cls(b.get("humans", b["human"]), b["max_year"], b.get("lang", "zh-Hans"), personas=b.get("persona_key"))
        s.eng.load(b["board"]); s.chronicle = b["chronicle"]; s.history = b.get("history") or s.history
        s.end_rule = b.get("end_rule", s.end_rule)
        s.round = b.get("round", 1); s.mode = b.get("mode", "NEGO")
        for m in b.get("msgs", []):                      # restore chat history
            s.bus.post(m["rnd"], m["sender"], m["scope"], m["to"], m["text"], m.get("phase", ""))
        s._chron_idx = len(s.bus.msgs)                   # restored chronicle already covers restored msgs
        for c, snap in (b.get("mem") or {}).items():     # restore AI memory (relations/actions/diary)
            if c in s.ai:
                s.ai[c].mem.restore(snap)
        return s

    def state(self, power=None) -> dict:
        power = power if power is not None else self.human
        chans = self.bus.channels(power, self.round)        # spectate(power=None): privates auto-hidden, 群聊 visible
        for k in self._opened.get(power, set()): chans.setdefault(k, [])   # opener-only empty tab; recipient gets it on first msg
        hmsgs = self._hmsgs.get(power, [])
        return {"human": power, "humans": self.humans, "phase": self.eng.phase(), "mode": self.mode, "round": self.round,
                "pending": self.pending(), "human_done": power in self._done, "your_turn": self.your_turn(power),
                "sent": len(hmsgs), "staged": "已发%d/3" % len(hmsgs),
                "msgs_left": max(0, self.MSGS_PER_ROUND - len(hmsgs)),  # remaining this round
                "staged_msgs": [m.content for m in hmsgs],  # this round's pending msgs (delivered at round end)
                "centers": self.eng.centers(), "channels": chans, "lang": self.lang,  # persona hidden; debug only
                "phase_type": self.eng.phase_type(),
                # ORDERS phase: who still owes orders (humans until submit; 6 AI decide on submit)
                "order_pending": (sorted(p for p in self.humans if p not in self._horders) + sorted(self.ai))
                                 if self.mode == "ORDERS" else [],
                "legal": self.legal(power) if self.mode == "ORDERS" else [],
                "units": len(self.eng.legal_orders(power)) if power and self.mode == "ORDERS" else 0,  # auto-settle when all set
                "end": self._end(), "history": self.history}  # winner/draw + center chart data


class Msg:
    def __init__(self, scope, to, content): self.scope, self.to, self.content = scope, to, content
