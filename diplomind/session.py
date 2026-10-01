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
import secrets
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
_PRIMARY = object()
POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]


def spawn(coro):                                         # fire-and-forget but surface crashes, don't fail silently
    t = asyncio.ensure_future(coro)
    t.add_done_callback(lambda f: f.cancelled() or f.exception() and log.error("后台任务异常: %s", f.exception()))
    return t


class Session:
    def __init__(self, human: str | None = "__cfg__", max_year: int | None = None,
                 lang: str | None = None, personas: dict | None = None, cfg=None, game_mode: str | None = None) -> None:
        cfg = cfg or load_config()
        h = cfg.human if human == "__cfg__" else human
        self.humans = [h] if isinstance(h, str) else list(h or [])       # 0/1/many humans, any power
        self.human = self.humans[0] if self.humans else None             # primary (single-player UI compat)
        self.max_year = max_year if max_year is not None else cfg.max_year; self.lang = lang or cfg.lang
        self.game_mode = game_mode or cfg.game_mode
        if self.game_mode not in {"classic", "plus"}: raise ValueError("Invalid game mode")
        self.end_rule = cfg.end_rule                      # topcount=most centers wins; draw=all survivors draw
        self.rounds = cfg.rounds                          # negotiation rounds from config
        self.order_preflight_review = getattr(cfg, "order_preflight_review", False)
        self.gw = Gateway.from_config(cfg)
        self.eng = OperationEngine(POWERS)
        keys = list(PERSONAS); random.shuffle(keys)                     # random by default; personas can fix per power
        self.persona_key = {c: (personas or {}).get(c, keys[i]) for i, c in enumerate(POWERS)}
        self.persona_of = {c: PERSONAS[self.persona_key[c]].name for c in POWERS if c not in self.humans}
        self.players = {c: (HumanPlayer(c) if c in self.humans else      # humans not built as AI
                            AIPlayer(Agent(c, PERSONAS[self.persona_key[c]], self.gw, self.lang),
                                     preflight_review=self.order_preflight_review))
                        for c in POWERS}
        self.ai = {c: p.agent for c, p in self.players.items() if isinstance(p, AIPlayer)}
        for agent in self.ai.values(): agent.game_mode = self.game_mode
        self.bus = MessageBus(); self.round = 1; self.mode = "NEGO"
        self.chronicle: list[str] = []; self._chron_idx = 0   # bus msgs already covered by past chronicle entries
        self._opened: dict[str, set] = {}                 # opener-only pre-opened tabs (recipient sees on first msg)
        self.history: list[dict] = [{"phase": self.eng.phase(), **self.eng.centers()}]  # center counts per phase, for chart
        self._done: dict[str, object] = {}; self._hmsgs: dict = {}; self._committed: set[int] = set(); self._cog = False
        self._horders: dict[str, list[str]] = {}; self._settling = False   # per-human submitted orders; settle once
        self._closed = False; self._paused = False; self._running = asyncio.Event(); self._running.set()
        self._tasks: set[asyncio.Task] = set(); self._phase_started: str | None = None
        self._epoch = secrets.token_hex(8); self._requests: dict[str, dict] = {}; self.on_change = None
        self._settlement_task = None; self._ai_orders: dict[str, list[str]] = {}
        self._ai_task = None; self._ai_squad: list = []    # AI orders drafted concurrently w/ humans during ORDERS

    def _spawn(self, coro):
        task = spawn(coro); self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _changed(self):
        if self.on_change and not self._closed and not self._settling:
            self.on_change()

    @property
    def turn_id(self) -> str:
        return f"{self._epoch}:{self.eng.phase()}:{self.mode}:{self.round}"

    def _guard(self, turn_id=None, request_id=None, power=None):
        if self._closed or self._paused or self.ended():
            return {"ok": False, "reason": "Game is paused or ended", "status": 409}
        key = f"{power}:{request_id}" if request_id else None
        if key and key in self._requests:
            return {**self._requests[key], "duplicate": True}
        if turn_id is not None and turn_id != self.turn_id:
            return {"ok": False, "reason": "This turn has changed; refresh before acting", "status": 409}
        return None

    def _remember(self, power, request_id, result):
        if request_id:
            self._requests[f"{power}:{request_id}"] = dict(result)
            if len(self._requests) > 1000: self._requests.pop(next(iter(self._requests)))
        return result

    def pause(self):
        self._paused = True; self._running.clear()

    def resume(self):
        if not self._closed:
            self._paused = False; self._running.set()

    async def begin_phase(self) -> None:
        if self._closed or self.ended(): return
        if self._phase_started == self.eng.phase(): return
        self._phase_started = self.eng.phase()
        if self.eng.phase_type() != "M": self.mode = "ORDERS"
        if self.mode == "ORDERS":
            for power in self.humans:
                if not self.legal(power): self._horders.setdefault(power, [])
            self._draft_orders()
            if all(p in self._horders for p in self.humans): self._spawn(self._settle_continue())
        else:
            self._start_round(reset=False)
            await self._maybe_advance()

    def _transcript(self, power):
        return self.bus.inbox(power, self.round - 1, include_self=True,
                              recent=self.rounds + 1, phase=self.eng.phase())

    def _observe_messages(self):
        phase = self.eng.phase()
        records = [vars(message) for message in self.bus.msgs if message.phase == phase]
        for agent in self.ai.values(): agent.observe_messages(phase, records)

    def _draft_orders(self):
        if self.eng.phase_type() != "M" or self._ai_task is not None: return
        self._observe_messages()
        self._ai_squad = self.ai_players()
        for player in self._ai_squad:
            player.agent.observe_diplomacy(self.eng.phase(), self._transcript(player.country))
        self._ai_task = self._spawn(asyncio.gather(*(
            self._decide_one(p) for p in self._ai_squad)))

    async def _decide_one(self, player):
        if player.country in self._ai_orders: return self._ai_orders[player.country]
        await self._running.wait()
        if self._closed: return []
        try:
            orders = await player.decide(self.eng, inbox=self._transcript(player.country))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("AI order generation failed for %s; using holds", player.country)
            orders = []
        self._ai_orders[player.country] = orders
        self._changed()
        return orders

    def ai_players(self):
        return [p for p in self.players.values() if isinstance(p, AIPlayer)]

    def _end(self):
        return self.eng.check_end(self.max_year, draw_all=self.game_mode == "classic" or self.end_rule != "topcount")

    def ended(self) -> bool:                     # game decided: solo win / year-cap ruling
        return bool(self._end())

    def close(self) -> None:                     # release gateway httpx clients (room reaped)
        self._closed = True; self._running.set()
        for task in list(self._tasks): task.cancel()
        close = getattr(self.gw, "close", None)
        if close: close()

    async def aclose(self):
        self._closed = True; self._running.set()
        for task in list(self._tasks): task.cancel()
        if self._tasks: await asyncio.gather(*list(self._tasks), return_exceptions=True)
        close = getattr(self.gw, "aclose", None)
        if close: await close()
        elif getattr(self.gw, "close", None): self.gw.close()

    def aiify(self, power: str) -> bool:
        """Kick/abandon: a human seat becomes AI using its pre-assigned persona + blank memory."""
        if power not in self.humans:
            return False
        self.humans.remove(power); self.human = self.humans[0] if self.humans else None
        agent = Agent(power, PERSONAS[self.persona_key[power]], self.gw, self.lang)
        agent.game_mode = self.game_mode
        self.players[power] = AIPlayer(agent, preflight_review=self.order_preflight_review); self.ai[power] = agent; self.persona_of[power] = agent.persona.name
        self._done.setdefault(power, None); self._horders.pop(power, None)   # unblock current round
        try:
            asyncio.get_running_loop()
        except RuntimeError:                                                 # no loop (sync test): advance lazily
            return True
        if self.mode == "NEGO":
            self._spawn(self._maybe_advance())                                     # AI takes over next round
        elif self.mode == "ORDERS" and all(p in self._horders for p in self.humans):
            self._spawn(self._settle_continue())                                   # kicked seat was the last holdout
        return True

    async def _settle_continue(self) -> None:            # settle + roll into next phase (same rule as web /api/orders)
        res = await self.settle()
        if res.get("phase") and not res.get("build") and not res.get("end"):
            await self.begin_phase()
        return res

    def _start_round(self, reset=True) -> None:
        if reset: self._done = {}; self._hmsgs = {}
        for power in self.players:
            if self.eng.game.powers[power].is_eliminated(): self._done.setdefault(power, None)
        context = (self.eng.phase(), self.round)
        for c, agent in self.ai.items():
            if c not in self._done:
                self._spawn(self._run(c, agent, self._transcript(c), context))

    async def _run(self, c, agent, inbox, context):
        try:
            await self._running.wait()
            if self._closed: return
            if not self._cog:
                await agent.a_update(self.eng, inbox)
                await self._running.wait()
                if self._closed: return
                await agent.a_intent(self.eng)
            await self._running.wait()
            if self._closed: return
            out = await agent.a_negotiate(self.eng, inbox)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("AI negotiation failed for %s; this round skips", c)
            out = None
        await self._running.wait()
        if self._closed or context != (self.eng.phase(), self.round) or self.mode != "NEGO": return
        self._done[c] = out
        self._changed()
        await self._maybe_advance()

    def pending(self) -> list[str]:
        return [c for c in self.players if c not in self._done]   # who hasn't acted

    MSGS_PER_ROUND = 3                                    # each player can send up to 3 msgs/round (multi-channel)

    async def say(self, power, scope, recipient, content, skip=False, turn_id=None, request_id=None) -> dict:
        """One seat speaks/skips. power must be a human seat. Done after skip or 3 msgs."""
        if power not in self.humans:
            return {"ok": False, "reason": "A human seat is required", "status": 403}
        guard = self._guard(turn_id, request_id, power)
        if guard: return guard
        if scope not in {"broadcast", "private"} or any(p not in POWERS or p == power for p in recipient):
            return {"ok": False, "reason": "Invalid channel recipients", "status": 422}
        if scope == "private" and not recipient:
            return {"ok": False, "reason": "Choose a private recipient", "status": 422}
        if self.mode != "NEGO" or power in self._done:            # already acted -> reject
            return {"ok": False, "reason": "This round is already submitted", "status": 409}
        if not skip and not content.strip():
            return {"ok": False, "reason": "不能发空消息"}
        if not skip:
            self._hmsgs.setdefault(power, []).append(Message(type=scope, recipient=recipient, content=content))
        if skip or len(self._hmsgs.get(power, [])) >= self.MSGS_PER_ROUND:
            self._done[power] = self._hmsgs.get(power) or None   # done after skip or 3 msgs
            await self._maybe_advance()
        result = self._remember(power, request_id, {"ok": True, "sent": len(self._hmsgs.get(power, []))})
        self._changed()
        return result

    async def human_say(self, scope, recipient, content, skip=False) -> dict:   # primary-seat shim
        return await self.say(self.human, scope, recipient, content, skip)

    def your_turn(self, power=_PRIMARY) -> bool:               # can speak (<3 msgs, not done) this round
        power = self.human if power is _PRIMARY else power
        return not self._closed and not self._paused and not self.ended() and self.mode == "NEGO" and power in self.humans and power not in self._done

    async def _maybe_advance(self) -> None:
        if self._paused or self._closed or self.ended(): return
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
        self._observe_messages()
        log.info("R%d 齐, 投递推进; 静默=%s", self.round, self.bus.round_silent(self.round, ph))
        self.round += 1; self._cog = True            # cognition once per phase
        if self.round > self.rounds or self.bus.round_silent(self.round - 1, ph):
            self.mode = "ORDERS"; self._horders = {p: [] for p in self.humans if not self.legal(p)}; log.info("转下令")
            self._draft_orders()
            if all(p in self._horders for p in self.humans):
                self._spawn(self._auto_spectate())
        else:
            self._start_round()
        self._changed()

    async def _auto_spectate(self) -> None:
        await self.settle()
        if not self.eng.is_done() and not self._end():
            await self.begin_phase()

    def open_private(self, power, recipients) -> str:
        if power not in self.humans or not recipients or any(r not in POWERS or r == power for r in recipients):
            raise ValueError("A seated human and valid other recipients are required")
        key = "·".join(sorted({power, *recipients}))
        self._opened.setdefault(power, set()).add(key); return key       # only opener sees empty tab; others on first msg

    def legal(self, power=_PRIMARY) -> list[str]:
        power = self.human if power is _PRIMARY else power
        return sorted({o for v in self.eng.legal_orders(power).values() for o in v}) if power else []

    async def submit_orders(self, power, orders, turn_id=None, request_id=None) -> dict:
        if power not in self.humans:
            return {"ok": False, "reason": "A human seat is required", "status": 403}
        guard = self._guard(turn_id, request_id, power)
        if guard: return guard
        if self.mode != "ORDERS" or power in self._horders or self._settling:
            return {"ok": False, "reason": "Orders already submitted or phase has changed", "status": 409}
        illegal = [o for o in orders if o not in self.eng_legal(power)]
        keys = [o.split()[1].split("/")[0] if len(o.split()) > 1 else o for o in orders]
        excessive = (self.eng.phase_type() == "A" and
                     len(orders) > abs(self.eng.game.get_state()["builds"][power]["count"]))
        if illegal or len(keys) != len(set(keys)) or excessive:
            return {"ok": False, "reason": "Illegal, duplicate, or excessive adjustment orders", "rejected": illegal, "status": 422}
        self._horders[power] = list(orders)
        self._remember(power, request_id, {"ok": True, "submitted": True})
        self._changed()
        if all(p in self._horders for p in self.humans):
            self._settlement_task = self._spawn(self._settle_continue())
            result = await asyncio.shield(self._settlement_task)
        else:
            result = {"ok": True, "waiting": sorted(p for p in self.humans if p not in self._horders)}
        self._remember(power, request_id, result)
        return result

    def cancel_orders(self, power, turn_id=None):
        guard = self._guard(turn_id, power=power)
        if guard: return guard
        if power not in self.humans: return {"ok": False, "reason": "A human seat is required", "status": 403}
        if self.mode != "ORDERS" or self._settling or power not in self._horders:
            return {"ok": False, "reason": "Orders cannot be withdrawn now", "status": 409}
        self._horders.pop(power); self._changed()
        return {"ok": True}

    async def submit(self, human_orders=None) -> dict:    # primary-seat shim: submit + settle
        if self.human and human_orders is not None:
            self._horders[self.human] = [o for o in human_orders if o in self.eng_legal(self.human)]
        return await self.settle()

    async def settle(self) -> dict:
        if self._closed or self.ended(): return {"ok": False, "reason": "Game has ended", "status": 409}
        if self._settling:
            return {"ok": False, "reason": "结算中"}
        self._settling = True
        try:
            await self._running.wait()
            if self._closed: return {"ok": False, "reason": "Game ended", "status": 409}
            for p, o in self._horders.items():
                self.eng.submit(p, o)                     # humans' submitted orders (already legal-filtered)
            if self.eng.phase_type() == "M":              # movement: AI orders drafted in parallel since ORDERS began
                self._draft_orders()
                ai = self._ai_squad if self._ai_task else self.ai_players()   # seats aiified after the draft just hold
                outs = await (self._ai_task or asyncio.gather(*(p.decide(self.eng) for p in ai)))
                await self._running.wait()
                if self._closed: return {"ok": False, "reason": "Game ended", "status": 409}
                for p, chosen in zip(ai, outs):
                    self.eng.submit(p.country, chosen)
                self._ai_task = None; self._ai_squad = []; self._ai_orders = {}
            else:
                self.eng.auto_resolve(except_=set(self.humans))   # retreat/build: AI auto, humans chose
            nxt = self._process()
            # A capture is public fact; intent/betrayal is a private assessment.
            while self.eng.phase_type() != "M" and not self.eng.is_done():   # retreat/build: AI auto; stop for human
                if self.humans and any(self.legal(p) for p in self.humans):
                    self.mode = "ORDERS"; self._horders = {p: [] for p in self.humans if not self.legal(p)}; return {"phase": nxt, "build": True, "end": None}
                self.eng.auto_resolve(); nxt = self._process()
            log.info("结算 -> %s", nxt)
            self.history.append({"phase": nxt, **self.eng.centers()})   # snapshot centers each phase for the chart
            # No extra model request on the adjudication critical path. Player
            # claims stay attributed, and published engine results supply facts.
            self.chronicle.append(generate(self.bus, nxt, self.eng.centers(),
                since=self._chron_idx, adjudication=self.eng.last_adjudication()))
            self._chron_idx = len(self.bus.msgs)          # this phase's msgs covered; next entry starts fresh
            self.round = 1; self.mode = "NEGO"; self._cog = False; self._phase_started = None; self._committed = set(); self._horders = {}; self._done = {}; self._hmsgs = {}   # keep bus: cross-phase chat history
            for a in self.ai.values(): a.mem.tick()
            return {"ok": True, "phase": nxt, "end": self._end()}
        finally:
            self._settling = False
            self._changed()

    def eng_legal(self, c):
        return {o for v in self.eng.legal_orders(c).values() for o in v}

    def _process(self):
        before = {c: set(self.eng.game.powers[c].centers) for c in POWERS}
        previous_phase = self.eng.phase()
        next_phase = self.eng.process()
        self._detect_betrayal(before, previous_phase)
        return next_phase

    def _detect_betrayal(self, before: dict, previous_phase=None) -> None:
        """Record public center transfers, without inventing intent or consent.

        An agreed handover and a hostile capture look identical to the engine.
        The existing persona-aware cognition step assesses trust from this fact
        and the power's own visible agreement evidence; no universal -80 penalty.
        """
        yr = int("".join(filter(str.isdigit, previous_phase or self.eng.phase())) or 0)
        for victim in POWERS:
            lost = before[victim] - set(self.eng.game.powers[victim].centers)
            for cen in lost:
                taker = next((c for c in POWERS if cen in self.eng.game.powers[c].centers), None)
                if not taker or taker == victim:                  # any taker (incl. human) holds a grudge for AI victim
                    continue
                vm = self.ai[victim].mem if victim in self.ai else None
                if vm:
                    vm.record_action(yr, taker,
                        f"Supply center {cen} transferred from {victim} to {taker}; betrayal/consent not assessed",
                        betray=False, source="public_result")

    SAVES = Path(os.getenv("DIPLOMIND_DATA_DIR", "logs")) / "saves"

    @staticmethod
    def _safe_name(name: str) -> str:                    # basename + whitelist: block ../ path traversal
        stem = Path(name or "auto").name
        stem = re.sub(r"[^\w.-]", "_", stem)[:64].strip(".") or "auto"
        return stem

    @classmethod
    def list_saves(cls) -> list[str]:
        return sorted(p.stem for p in cls.SAVES.glob("*.json")) if cls.SAVES.exists() else []

    def to_dict(self) -> dict:
        def messages(value):
            if value is None: return None
            return [m.model_dump() for m in (value if isinstance(value, list) else [value])]
        return {"version": 2, "human": self.human, "humans": self.humans, "max_year": self.max_year,
                "lang": self.lang, "end_rule": self.end_rule, "game_mode": self.game_mode, "rounds": self.rounds,
                "board": self.eng.save(), "chronicle": self.chronicle, "persona_key": self.persona_key,
                "round": self.round, "mode": self.mode, "msgs": [vars(m) for m in self.bus.msgs],
                "history": self.history, "mem": {c: {**a.mem.snapshot(), "intent": a.mem.intent} for c, a in self.ai.items()},
                "done": {p: messages(v) for p, v in self._done.items()},
                "hmsgs": {p: messages(v) for p, v in self._hmsgs.items()}, "horders": self._horders,
                "ai_orders": self._ai_orders, "committed": sorted(self._committed), "cog": self._cog, "chron_idx": self._chron_idx,
                "opened": {p: sorted(v) for p, v in self._opened.items()}}

    def save(self, name: str = "auto") -> dict:
        """Legacy local-only save helper. Web access is exclusively RoomManager-scoped."""
        name = self._safe_name(name); self.SAVES.mkdir(parents=True, exist_ok=True)
        self._write_json(self.SAVES / f"{name}.json", self.to_dict())
        return {"saved": name}

    @staticmethod
    def _write_json(path, blob):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_suffix(f".{secrets.token_hex(6)}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as out:
                json.dump(blob, out, ensure_ascii=False)
                out.flush(); os.fsync(out.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists(): tmp.unlink()

    @classmethod
    def from_dict(cls, b: dict) -> "Session":
        s = cls(b.get("humans", b.get("human")), b.get("max_year"), b.get("lang", "zh-Hans"),
                personas=b.get("persona_key"), game_mode=b.get("game_mode", "classic"))
        s.max_year = b.get("max_year")
        s.eng.load(b["board"]); s.chronicle = b.get("chronicle", []); s.history = b.get("history") or s.history
        s.end_rule = b.get("end_rule", s.end_rule); s.rounds = b.get("rounds", s.rounds)
        s.round = b.get("round", 1); s.mode = b.get("mode", "NEGO")
        for m in b.get("msgs", []):
            s.bus.post(m["rnd"], m["sender"], m["scope"], m["to"], m["text"], m.get("phase", ""))
        s._chron_idx = b.get("chron_idx", len(s.bus.msgs))
        for c, snap in (b.get("mem") or {}).items():
            if c in s.ai:
                s.ai[c].mem.restore(snap); s.ai[c].mem.intent = snap.get("intent")
        s._done = {p: [Message(**m) for m in v] if v else None for p, v in b.get("done", {}).items()}
        s._hmsgs = {p: [Message(**m) for m in v] if v else [] for p, v in b.get("hmsgs", {}).items()}
        s._horders = {p: list(v) for p, v in b.get("horders", {}).items() if p in s.humans}
        s._ai_orders = {p: list(v) for p, v in b.get("ai_orders", {}).items() if p in s.ai}
        s._committed = set(b.get("committed", [])); s._cog = b.get("cog", False)
        s._opened = {p: set(v) for p, v in b.get("opened", {}).items()}
        return s

    @classmethod
    def load(cls, name: str = "auto") -> "Session":
        return cls.from_dict(json.loads((cls.SAVES / f"{cls._safe_name(name)}.json").read_text()))

    def state(self, power=_PRIMARY) -> dict:
        power = self.human if power is _PRIMARY else power
        chans = self.bus.channels(power)                    # spectate(power=None): privates auto-hidden, 群聊 visible
        for k in self._opened.get(power, set()): chans.setdefault(k, [])   # opener-only empty tab; recipient gets it on first msg
        hmsgs = self._hmsgs.get(power, [])
        adjustment = self.eng.game.get_state()["builds"][power]["count"] if power in self.humans and self.eng.phase_type() == "A" else 0
        return {"adjustment_count": adjustment, "turn_id": self.turn_id, "game_mode": self.game_mode, "max_year": self.max_year, "order_submitted": power in self._horders,
                "submitted_orders": self._horders.get(power, []), "settling": self._settling, "human": power, "humans": self.humans, "phase": self.eng.phase(), "mode": self.mode, "round": self.round,
                "pending": self.pending(), "human_done": power in self._done, "your_turn": self.your_turn(power),
                "sent": len(hmsgs), "staged": "已发%d/3" % len(hmsgs),
                "msgs_left": max(0, self.MSGS_PER_ROUND - len(hmsgs)),  # remaining this round
                "staged_msgs": [m.content for m in hmsgs],  # this round's pending msgs (delivered at round end)
                "centers": self.eng.centers(), "channels": chans, "lang": self.lang,  # persona hidden; debug only
                "phase_type": self.eng.phase_type(),
                # ORDERS phase: who still owes orders (humans until submit; 6 AI decide on submit)
                "order_pending": (sorted(p for p in self.humans if p not in self._horders) + (sorted(p for p in self.ai if p not in self._ai_orders) if self.eng.phase_type() == "M" else []))
                                 if self.mode == "ORDERS" else [],
                "legal": self.legal(power) if power in self.humans and self.mode == "ORDERS" else [],
                "units": (abs(adjustment) if self.eng.phase_type() == "A" else len(self.eng.legal_orders(power))) if power and self.mode == "ORDERS" else 0,  # auto-settle when all set
                "end": self._end(), "history": self.history}  # winner/draw + center chart data


class Msg:
    def __init__(self, scope, to, content): self.scope, self.to, self.content = scope, to, content
