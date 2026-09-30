"""Authenticated multi-room API. Bearer seat secrets never enter public listings."""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .chronicle import book
from .debugpanel import snapshot
from .names import PROVINCES
from .rooms import RoomManager, SHORT_SECS
from .session import Session, spawn
from .engine import OperationEngine
from .config import load as load_config
from .board import board_state
from .security import install_access_log_redaction, private_api_headers

DEBUG = os.getenv("DIPLOMIND_DEBUG", "").lower() in {"1", "true", "yes"}
RM = RoomManager()
PRE = Path(__file__).parent.parent / "conf" / "presets"


@asynccontextmanager
async def lifespan(app):
    ticker = asyncio.create_task(_ticker())
    try:
        yield
    finally:
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)
        for room in list(RM.rooms.values()):
            RM.checkpoint(room)
            if room.session: await room.session.aclose()
        RM.rooms.clear(); RM.tokens.clear()


install_access_log_redaction()
app = FastAPI(title="DiploMind", lifespan=lifespan)
app.middleware("http")(private_api_headers)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static", check_dir=False), name="static")


def room_of(token: str | None):
    return RM.rooms.get(RM.tokens.get(token or "", "")) or (RM.recover(token) if token else None)


def _room(token, *, owner=False, human=False, playing=False, session=False):
    room = room_of(token)
    if not room: raise HTTPException(401, "A valid room token is required")
    if owner and token != room.owner: raise HTTPException(403, "Only the room owner can do that")
    if human and room.seat_of(token) is None: raise HTTPException(403, "Claim a human seat to do that")
    if session and not room.session: raise HTTPException(409, "The room has not started")
    if playing and (room.status != "playing" or room.finished()): raise HTTPException(409, "The game is paused or ended")
    return room


def _result(result):
    if result.get("ok") is False:
        raise HTTPException(result.get("status", 409), result.get("reason", "Action unavailable"))
    return result


@app.get("/api/menu")
async def menu(token: str | None = None):
    pres = {p.stem: json.loads(p.read_text()) for p in PRE.glob("*.json")} if PRE.exists() else {}
    return {"presets": pres, "saves": RM.list_saves(_room(token, owner=True)) if token else []}


@app.get("/api/providers")
async def providers():
    from .gateway import provider_capabilities
    cfg = load_config()
    return {"selected": cfg.api, "model": cfg.model, "providers": provider_capabilities(cli_enabled=cfg.cli_enabled)}


@app.get("/api/rooms")
async def rooms():
    return {"rooms": RM.list()}


class CreateReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=80)
    owner_name: str = Field(default="Host", max_length=40)
    power: str | None = None
    lang: str = "zh-Hans"
    preset: str | None = None
    passcode: str = Field(default="", max_length=128)
    end_rule: str = ""
    game_mode: Literal["classic", "plus"] = "classic"
    max_year: int | None = Field(default=None, ge=1901, le=9999)


class JoinReq(BaseModel):
    code: str
    power: str | None = None
    name: str = Field(default="", max_length=40)
    token: str | None = None
    passcode: str = Field(default="", max_length=128)


class TokReq(BaseModel):
    token: str | None = None


class PauseReq(TokReq):
    status: Literal["paused", "playing"] | None = None


class ActionReq(TokReq):
    turn_id: str
    request_id: str | None = Field(default=None, max_length=128)


class SayReq(ActionReq):
    scope: Literal["broadcast", "private"] = "broadcast"
    recipient: list[str] = Field(default_factory=list, max_length=6)
    content: str = Field(default="", max_length=4000)
    skip: bool = False


class OrdReq(ActionReq):
    orders: list[str] = Field(default_factory=list, max_length=34)


class PrivReq(TokReq):
    recipient: list[str] = Field(default_factory=list, max_length=6)
    turn_id: str | None = None


class SecsReq(TokReq):
    secs: int = Field(default=180, ge=0, le=3600)


class XferReq(TokReq):
    power: str = ""


def _identity(room, token):
    return {"code": room.code, "token": token, "seat": room.seat_of(token), "owner": token == room.owner}


@app.post("/api/room/create")
async def create(r: CreateReq):
    try:
        room = RM.create(r.name, r.owner_name, r.power, r.lang, r.passcode, r.end_rule, r.game_mode, r.max_year)
    except ValueError as exc: raise HTTPException(422, str(exc))
    return _identity(room, room.owner)


@app.post("/api/room/join")
async def join(r: JoinReq):
    if r.token and not room_of(r.token):
        # An unknown supplied credential may join anew, but can never reclaim a live seat.
        pass
    room, tok = RM.join(r.code, r.power, r.name, r.token, r.passcode)
    if not room:
        statuses = {"badpass": 403, "notfound": 404, "invalidpower": 422, "seatunavailable": 409}
        raise HTTPException(statuses.get(tok, 409), tok)
    _bump(room)
    return _identity(room, tok)


@app.post("/api/room/start")
async def start(r: TokReq):
    room = _room(r.token, owner=True)
    try: room.start()
    except ValueError as exc: raise HTTPException(409, str(exc))
    RM._bind(room)
    await room.session.begin_phase(); _bump(room)
    return {"ok": True}


@app.post("/api/room/pause")
async def pause(r: PauseReq):
    room = _room(r.token, owner=True, session=True)
    if r.status == room.status and room.status in {"paused", "playing"}:
        return {"status": room.status}
    try: room.toggle_pause()
    except ValueError as exc: raise HTTPException(409, str(exc))
    if room.status == "playing":
        await room.session.begin_phase()
        await room.session._maybe_advance()
    _bump(room)
    return {"status": room.status}


@app.post("/api/room/end")
async def end(r: TokReq):
    room = _room(r.token, owner=True)
    RM.end(room); _bump(room)
    return {"ok": True}


@app.post("/api/room/secs")
async def secs(r: SecsReq):
    room = _room(r.token, owner=True)
    room.set_secs(r.secs); _bump(room)
    return {"secs": room.secs, "timer_on": room.timer_on}


@app.post("/api/room/transfer")
async def transfer(r: XferReq):
    room = _room(r.token, owner=True)
    if not room.transfer(r.power): raise HTTPException(409, "Choose a seated human")
    _bump(room)
    return {"ok": True}


@app.post("/api/room/kick")
async def kick(r: XferReq):
    room = _room(r.token, owner=True)
    if room.session and room.session._settling: raise HTTPException(409, "Wait for adjudication")
    if not RM.kick(room.code, r.power): raise HTTPException(409, "That seat cannot be removed")
    _bump(room)
    return {"ok": True}


def _clock_state(room):
    """Small time/presence payload; never includes messages or sealed orders."""
    return {"secs_left": (max(0, int(room.deadline - time.time())) if room.deadline is not None else
                          int(room.remaining) if room.remaining is not None else None),
            "short": sorted(room.short), "dropped": room.dropped()}


def _stream_revision(room):
    s = room.session
    # During adjudication callbacks deliberately skip checkpoints. These cheap
    # fields still expose resolving/readiness and phase transitions immediately.
    return (room.version, id(s), s.turn_id if s else None,
            s._settling if s else False, tuple(s._ai_orders) if s else ())


def _state(token: str | None = None):
    if not token: return {"mode": "MENU", "phase": "-", "debug": False}
    room = _room(token); seat = room.seat_of(token); room.touch(seat)
    s = room.session.state(seat) if room.session else {"mode": "LOBBY", "phase": "-", "human": seat, "humans": room.humans()}
    s.update({"debug": DEBUG and token == room.owner, "room": room.code, "rname": room.name,
              "status": room.status, "owner": token == room.owner, "game_mode": room.game_mode,
              **_clock_state(room), "timer_on": room.timer_on, "secs": room.secs,
              "seats": room.humans(), "seat_names": {p: x["name"] for p, x in room.seats.items()}, "version": room.version})
    return s


@app.get("/api/state")
async def state(token: str | None = None):
    return _state(token)

@app.post("/api/say")
async def say(r: SayReq):
    room = _room(r.token, human=True, playing=True, session=True); seat = room.seat_of(r.token)
    result = _result(await room.session.say(seat, r.scope, r.recipient, r.content, r.skip, r.turn_id, r.request_id))
    room.short.discard(seat); _bump(room)
    return {**result, "state": _state(r.token)}


@app.post("/api/open")
async def open_private(r: PrivReq):
    room = _room(r.token, human=True, playing=True, session=True)
    if r.turn_id and r.turn_id != room.session.turn_id: raise HTTPException(409, "This turn has changed")
    try: channel = room.session.open_private(room.seat_of(r.token), r.recipient)
    except ValueError as exc: raise HTTPException(422, str(exc))
    _bump(room)
    return {"channel": channel}


async def _submit_orders(room, seat, orders, turn_id=None, request_id=None):
    result = await room.session.submit_orders(seat, orders, turn_id, request_id)
    if result.get("phase") and not result.get("build") and not result.get("end"):
        await room.session.begin_phase()
    _bump(room)
    return result


@app.post("/api/orders")
async def orders(r: OrdReq):
    room = _room(r.token, human=True, playing=True, session=True); seat = room.seat_of(r.token)
    result = _result(await _submit_orders(room, seat, r.orders, r.turn_id, r.request_id))
    room.short.discard(seat)
    return {**result, "state": _state(r.token)}


@app.post("/api/orders/cancel")
async def cancel_orders(r: ActionReq):
    room = _room(r.token, human=True, playing=True, session=True)
    result = _result(room.session.cancel_orders(room.seat_of(r.token), r.turn_id)); _bump(room)
    return result


@app.get("/api/saves")
async def saves(token: str | None = None):
    return {"saves": RM.list_saves(_room(token, owner=True))}


@app.post("/api/save")
async def save(token: str | None = None, name: str = "auto"):
    room = _room(token, owner=True, session=True)
    try: return RM.save(room, name)
    except ValueError as exc: raise HTTPException(409, str(exc))


@app.post("/api/load")
async def load(token: str | None = None, name: str = "auto"):
    room = _room(token, owner=True)
    try: RM.load(room, name)
    except FileNotFoundError: raise HTTPException(404, "No such save in this room")
    except ValueError as exc: raise HTTPException(409, str(exc))
    _bump(room)
    return {**_identity(room, token), "status": room.status}


@app.get("/api/chronicle")
async def chron(token: str | None = None):
    room = _room(token, session=True)
    return {"text": book(room.session.chronicle)}


@app.get("/api/snapshot")
async def snap(token: str | None = None):
    room = _room(token, owner=True, session=True)
    if not DEBUG: return {}
    g = room.session
    return {**snapshot(g.ai, g.bus, g.eng), "persona": g.persona_of, "lang": g.lang}


@app.get("/api/board")
async def board(token: str | None = None):
    room = _room(token) if token else None
    # Board snapshots contain JSON-native public data already; avoid FastAPI's
    # recursive model encoder walking every SVG coordinate/path a second time.
    return JSONResponse(board_state(room.session.eng if room and room.session else OperationEngine()))

import re as _re
from pathlib import Path as _P
_LABELS = ""
for _p in _P(__import__("diplomacy").__file__).parent.glob("maps/svg/standard.svg"):
    _m = _re.search(r'<g[^>]*id="BriefLabelLayer".*?</g>', _p.read_text(), _re.S)
    _LABELS = _m.group(0) if _m else ""

@app.get("/api/map", response_class=HTMLResponse)
async def gmap(token: str | None = None):
    room = _room(token, session=True)
    # Pending engine orders may already be staged while AI settlement is awaited.
    # The public legacy SVG must never reveal them to other seats or observers.
    svg = room.session.eng.game.render(incl_orders=False)
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

# Server-sent updates use the exact room-token pair; revoked tokens terminate the stream.
def _bump(room):
    room.version += 1; room.active = time.time(); RM.checkpoint(room)


@app.get("/api/stream/{code}")
async def stream(code: str, token: str | None = None):
    room = _room(token)
    if code.upper() != room.code: raise HTTPException(403, "Token belongs to another room")
    async def gen():
        last_revision = None
        last_clock = None
        for _ in range(7200):
            if RM.tokens.get(token) != room.code or RM.rooms.get(room.code) is not room: return
            # An open stream remains an active seat, even when no game data changes.
            room.touch(room.seat_of(token))
            revision = _stream_revision(room)
            clock = _clock_state(room)
            if revision != last_revision:
                # Always rebuild through the authenticated seat filter. No full
                # snapshot is shared across clients or retained after reconnect.
                current = _state(token)
                last_revision = revision
                last_clock = clock
                yield f"data: {json.dumps(current)}\n\n"
            elif clock != last_clock:
                last_clock = clock
                payload = {**clock, "room": room.code, "version": room.version,
                           "turn_id": room.session.turn_id if room.session else None}
                yield f"event: clock\ndata: {json.dumps(payload)}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _ticker():
    n = 0
    while True:
        await asyncio.sleep(1); n += 1
        if n % 60 == 0: RM.gc()
        for room in list(RM.rooms.values()):
            s = room.session
            if not s or room.status != "playing" or not room.timer_on or not room.humans() or s.ended(): continue
            if s._settling: continue
            if room.clock_turn != s.turn_id or room.deadline is None:
                room.clock_turn = s.turn_id
                room.deadline = time.time() + (SHORT_SECS if room.short else room.secs)
            if time.time() < room.deadline: continue
            room.deadline = None
            turn = s.turn_id
            for power in list(room.humans()):
                if s.mode == "NEGO" and s.your_turn(power):
                    room.short.add(power)
                    s._spawn(s.say(power, "broadcast", [], "", True, turn))
                elif s.mode == "ORDERS" and power not in s._horders:
                    room.short.add(power)
                    s._spawn(_submit_orders(room, power, [], turn))
            _bump(room)


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX


INDEX = (Path(__file__).parent / "ui.html").read_text()
