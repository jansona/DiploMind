"""房间注册 — 一服多局。每房 = 1 owner + 座位认领(国↔昵称↔token) + Session。
status: lobby(配座)→playing→paused/ended。token→(room,power) 路由身份; 同 token 重连夺座。
计时仅人类: 默认 180s/轮, 超时本轮 hold/skip, 次轮缩 30s, 有响应恢复。"""
from __future__ import annotations

import hashlib
import secrets
import string
import time

from .session import POWERS, Session


def _hash(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest() if p else ""

CODE = string.ascii_uppercase + string.digits
DEFAULT_SECS = 180
SHORT_SECS = 30


def _code() -> str:
    return "".join(secrets.choice(CODE) for _ in range(4))


class Room:
    def __init__(self, name: str, owner: str, lang: str = "zh-Hans", max_year: int = 1910, passcode: str = "") -> None:
        self.code = _code(); self.name = name or self.code; self.lang = lang; self.max_year = max_year
        self.passhash = _hash(passcode)          # ""=open; else sha256, checked on join
        self.status = "lobby"; self.created = time.time(); self.active = time.time()
        self.seats: dict[str, dict] = {}        # power -> {name, token, kind: human/ai}
        self.owner = secrets.token_hex(8)        # owner_token
        self.timer_on = True; self.secs = DEFAULT_SECS
        self.session: Session | None = None
        self.deadline: float | None = None       # round timeout epoch
        self.short: set[str] = set()              # powers on 30s penalty until they respond

    def claim(self, power: str, name: str, token: str) -> bool:
        if self.status != "lobby" or power not in POWERS: return False
        if power in self.seats and self.seats[power]["token"] != token: return False  # taken by other
        self.seats[power] = {"name": name or power, "token": token, "kind": "human"}; self.active = time.time()
        return True

    def humans(self) -> list[str]:
        return sorted(p for p, s in self.seats.items() if s["kind"] == "human")

    def seat_of(self, token: str) -> str | None:
        return next((p for p, s in self.seats.items() if s["token"] == token), None)

    def start(self) -> None:
        self.session = Session(self.humans(), self.max_year, self.lang)   # AI fills open seats
        self.status = "playing"; self.active = time.time()

    def summary(self) -> dict:
        return {"code": self.code, "name": self.name, "status": self.status, "lang": self.lang,
                "phase": self.session.eng.phase() if self.session else "-",
                "humans": len(self.humans()), "seats": {p: s["name"] for p, s in self.seats.items()},
                "secs": self.secs, "locked": bool(self.passhash)}


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}; self.tokens: dict[str, str] = {}   # token -> code

    def create(self, name: str, owner_name: str, power: str | None, lang="zh-Hans", passcode="") -> Room:
        r = Room(name, owner_name, lang, passcode=passcode); self.rooms[r.code] = r; self.tokens[r.owner] = r.code
        if power: r.claim(power, owner_name, r.owner)
        return r

    def join(self, code: str, power: str | None, name: str, token: str | None, passcode="") -> tuple[Room | None, str]:
        r = self.rooms.get(code)
        if not r: return None, "notfound"
        known = token and self.tokens.get(token) == code            # owner/returning seat: passcode not re-asked
        if r.passhash and not known and _hash(passcode) != r.passhash:
            return None, "badpass"
        tok = token if known else secrets.token_hex(8)
        self.tokens[tok] = code
        if power: r.claim(power, name, tok)
        return r, tok

    def list(self) -> list[dict]:
        return [r.summary() for r in self.rooms.values() if r.status != "ended"]

    def gc(self, idle: int = 3600) -> None:                # reap ended/abandoned rooms
        now = time.time()
        for c in [c for c, r in self.rooms.items() if r.status == "ended" or now - r.active > idle]:
            del self.rooms[c]
