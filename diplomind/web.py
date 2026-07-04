"""Web 前端 — 一服多局: 大厅建/进房, 房主开局/暂停/结束, seat-token 认领座位, AI 补满。
2-7 真人轮次同步, SSE 推送, 谈判轮计时仅人类(超时落子)。地图 SVG。"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

DEBUG = bool(os.getenv("DIPLOMIND_DEBUG"))     # off: hide trust/internals; on: show

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from .chronicle import book
from .debugpanel import snapshot
from .names import PROVINCES
from .rooms import RoomManager, SHORT_SECS
from .session import Session, spawn


@asynccontextmanager
async def lifespan(app):
    spawn(_ticker()); yield

app = FastAPI(title="DiploMind", lifespan=lifespan)
RM = RoomManager()
PRE = Path(__file__).parent.parent / "conf" / "presets"


def room_of(token: str | None):
    return RM.rooms.get(RM.tokens.get(token or "", ""))


@app.get("/api/menu")        # main menu: presets + saves; no auto game (start screen)
def menu():
    pres = {p.stem: json.loads(p.read_text()) for p in PRE.glob("*.json")} if PRE.exists() else {}
    return {"presets": pres, "saves": Session.list_saves()}


@app.get("/api/rooms")       # lobby: live rooms count + summaries
def rooms():
    return {"rooms": RM.list()}


class CreateReq(BaseModel):
    name: str = ""; owner_name: str = "Host"; power: str | None = None; lang: str = "zh-Hans"; preset: str | None = None; passcode: str = ""; end_rule: str = ""
class JoinReq(BaseModel):
    code: str; power: str | None = None; name: str = ""; token: str | None = None; passcode: str = ""
class TokReq(BaseModel):
    token: str | None = None
class SayReq(BaseModel):
    token: str | None = None; scope: str = "broadcast"; recipient: list[str] = []; content: str = ""; skip: bool = False
class OrdReq(BaseModel):
    token: str | None = None; orders: list[str] = []
class PrivReq(BaseModel):
    token: str | None = None; recipient: list[str] = []


@app.post("/api/room/create")
def create(r: CreateReq):
    room = RM.create(r.name, r.owner_name, r.power, r.lang, r.passcode, r.end_rule)
    return {"code": room.code, "token": room.owner, "seat": room.seat_of(room.owner), "owner": True}

@app.post("/api/room/join")
def join(r: JoinReq):
    room, tok = RM.join(r.code, r.power, r.name, r.token, r.passcode)
    if not room: raise HTTPException(403 if tok == "badpass" else 404, "口令错误" if tok == "badpass" else "房间不存在")
    return {"code": room.code, "token": tok, "seat": room.seat_of(tok), "owner": tok == room.owner}

@app.post("/api/room/start")
async def start(r: TokReq):
    room = room_of(r.token)
    if not room or r.token != room.owner: raise HTTPException(403, "仅房主可开局")
    room.start(); spawn(room.session.begin_phase()); _bump(room); return {"ok": True}

@app.post("/api/room/pause")
def pause(r: TokReq):
    room = room_of(r.token)
    if room and r.token == room.owner: room.status = "paused" if room.status == "playing" else "playing"; _bump(room)
    return {"status": room.status if room else "?"}

@app.post("/api/room/end")
def end(r: TokReq):
    room = room_of(r.token)
    if room and r.token == room.owner: room.status = "ended"; _bump(room)
    return {"ok": True}

class SecsReq(BaseModel):
    token: str | None = None; secs: int = 180
class XferReq(BaseModel):
    token: str | None = None; power: str = ""

@app.post("/api/room/secs")      # owner sets round clock seconds; 0 = no clock
def secs(r: SecsReq):
    room = room_of(r.token)
    if room and r.token == room.owner: room.set_secs(r.secs); _bump(room)
    return {"secs": room.secs, "timer_on": room.timer_on} if room else {}

@app.post("/api/room/transfer")  # owner hands ownership to another seated human
def transfer(r: XferReq):
    room = room_of(r.token)
    if room and r.token == room.owner and room.transfer(r.power): _bump(room)
    return {"ok": True}

@app.post("/api/room/kick")      # owner kicks a human seat -> AI takes over (blank persona memory)
def kick(r: XferReq):
    room = room_of(r.token)
    if room and r.token == room.owner: RM.kick(room.code, r.power); _bump(room)
    return {"ok": True}

@app.get("/api/state")
def state(token: str | None = None):
    room = room_of(token)
    if not room or not room.session:
        return {"mode": "MENU", "phase": "-", "debug": DEBUG}
    seat = room.seat_of(token); room.touch(seat)             # client ping -> alive
    s = room.session.state(seat); s["debug"] = DEBUG
    s["room"] = room.code; s["rname"] = room.name; s["status"] = room.status; s["owner"] = token == room.owner
    s["secs_left"] = max(0, int(room.deadline - time.time())) if room.deadline and room.timer_on else None
    s["timer_on"] = room.timer_on; s["secs"] = room.secs
    s["short"] = sorted(room.short); s["dropped"] = room.dropped()   # 30s-penalty / disconnected seats
    s["seats"] = room.humans()
    return s

@app.post("/api/say")
async def say(r: SayReq):
    room = room_of(r.token)
    if not room or room.status != "playing": return {"ok": False, "reason": "未在对局中"}
    room.short.discard(room.seat_of(r.token))            # responded -> off penalty
    res = await room.session.say(room.seat_of(r.token), r.scope, r.recipient, r.content, r.skip); _bump(room)
    return {**res, "state": state(r.token)}

@app.post("/api/open")
def open_private(r: PrivReq):
    room = room_of(r.token)
    return {"channel": room.session.open_private(room.seat_of(r.token), r.recipient) if room and room.session else ""}

@app.post("/api/orders")
async def orders(r: OrdReq):
    room = room_of(r.token)
    if not room or room.status != "playing": return {"ok": False, "reason": "未在对局中"}
    room.short.discard(room.seat_of(r.token))
    res = await room.session.submit_orders(room.seat_of(r.token), r.orders)
    if res.get("phase") and not res.get("build") and not res.get("end"):   # fresh phase & game still on: next round
        spawn(room.session.begin_phase())
    _bump(room); return res

@app.post("/api/save")
def save(token: str | None = None, name: str = "auto"):
    room = room_of(token)
    return room.session.save(name) if room and room.session else {"ok": False}

@app.post("/api/load")       # owner reopens a save: humans rejoin by seat (room code re-bound to saved seats)
async def load(token: str | None = None, name: str = "auto"):
    try:
        sess = Session.load(name)
    except FileNotFoundError:
        raise HTTPException(404, f"存档不存在: {name}")
    room = RM.create(name, "Host", None, sess.lang); room.session = sess; room.status = "playing"
    for i, p in enumerate(sess.humans):              # loader takes the primary seat; others reclaim by power on join
        room.seats[p] = {"name": p, "token": room.owner if i == 0 else "", "kind": "human"}
    spawn(sess.begin_phase()); return {"code": room.code, "token": room.owner, "seat": room.seat_of(room.owner)}

@app.get("/api/chronicle")
def chron(token: str | None = None):
    room = room_of(token); return {"text": book(room.session.chronicle) if room and room.session else ""}

@app.get("/api/snapshot")
def snap(token: str | None = None):
    room = room_of(token)
    if not room or not room.session or not DEBUG: return {}
    g = room.session; return {**snapshot(g.ai, g.bus, g.eng), "persona": g.persona_of, "lang": g.lang}

import re as _re
from pathlib import Path as _P
_LABELS = ""
for _p in _P(__import__("diplomacy").__file__).parent.glob("maps/svg/standard.svg"):
    _m = _re.search(r'<g[^>]*id="BriefLabelLayer".*?</g>', _p.read_text(), _re.S)
    _LABELS = _m.group(0) if _m else ""

@app.get("/api/map", response_class=HTMLResponse)
def gmap(token: str | None = None):
    room = room_of(token)
    if not room or not room.session: return "<svg/>"
    svg = room.session.eng.game.render()
    return svg.replace("</svg>", _LABELS + "</svg>") if _LABELS else svg

_I18N = _P(__file__).parent / "i18n"
@app.get("/api/i18n/{lang}")
def i18n(lang: str):
    f = _I18N / f"{lang}.json"
    return json.loads(f.read_text()) if f.exists() else json.loads((_I18N / "en.json").read_text())

@app.get("/api/guide")
def guide():
    cmds = {"H": "Hold 原地", "-": "Move 移动 A PAR-BUR", "S": "Support 支援 A PAR S A MAR-BUR",
            "C": "Convoy 海运 F ENG C A LON-BRE", "B": "Build 造兵 A PAR B", "D": "Disband 拆兵"}
    return {"locs": [f"{a} = {en} / {zh}" for a, (en, zh) in sorted(PROVINCES.items())], "cmds": cmds}

# --- SSE push: bump a version on change, stream state to clients (no 2s poll) ---
def _bump(room):
    room.version = getattr(room, "version", 0) + 1; room.active = time.time()

@app.get("/api/stream/{code}")
async def stream(code: str, token: str | None = None):
    async def gen():
        last = ""
        for _ in range(7200):                            # ~1h cap; client reconnects
            cur = json.dumps(state(token))               # also touches seat (heartbeat); push on any diff
            if cur != last:
                last = cur; yield f"data: {cur}\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")

# --- timer ticker: humans-only round clock; timeout = skip/hold, then 30s penalty until response ---
async def _ticker():
    seen: dict[str, tuple] = {}; n = 0
    while True:
        await asyncio.sleep(1); n += 1
        if n % 60 == 0: RM.gc()                              # reap ended/idle rooms each minute
        for room in list(RM.rooms.values()):
            s = room.session
            if not s or room.status != "playing" or not room.timer_on or not room.humans():
                room.deadline = None; continue
            cur = (s.mode, s.round, s.eng.phase())
            if seen.get(room.code) != cur:               # new round/phase -> reset clock
                seen[room.code] = cur; pen = bool(room.short)
                room.deadline = time.time() + (SHORT_SECS if pen else room.secs)
            if room.deadline and time.time() >= room.deadline:
                room.deadline = None
                for p in room.humans():                  # whoever didn't act in time
                    if s.mode == "NEGO" and s.your_turn(p): room.short.add(p); spawn(s.say(p, "broadcast", [], "", True))
                    elif s.mode == "ORDERS" and p not in s._horders: room.short.add(p); spawn(s.submit_orders(p, []))
                _bump(room)

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX


INDEX = (Path(__file__).parent / "ui.html").read_text()
