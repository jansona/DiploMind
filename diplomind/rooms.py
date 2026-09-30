"""Room-scoped identities, lifecycle and private, atomic resume checkpoints."""
from __future__ import annotations

import hashlib
import json
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
    def __init__(self, name: str, owner: str, lang: str = "zh-Hans", max_year: int | None = None,
                 passcode: str = "", game_mode: str = "classic") -> None:
        self.code = _code(); self.storage_id = secrets.token_hex(16)
        self.name = name or self.code; self.lang = lang; self.max_year = max_year; self.game_mode = game_mode
        self.passhash = _hash(passcode)
        self.status = "lobby"; self.created = time.time(); self.active = time.time()
        self.seats: dict[str, dict] = {}
        self.owner = secrets.token_urlsafe(32)
        self.timer_on = True; self.secs = DEFAULT_SECS; self.end_rule = "draw"
        self.session: Session | None = None
        self.deadline: float | None = None; self.remaining: float | None = None
        self.clock_turn: str | None = None
        self.short: set[str] = set(); self.seen: dict[str, float] = {}
        self.version = 0

    def claim(self, power: str, name: str, token: str) -> bool:
        if power not in POWERS or not token: return False
        existing = self.seat_of(token)
        if existing and existing != power: return False
        seat = self.seats.get(power)
        if self.status != "lobby":
            # A country name is not an identity. Reconnect only with the existing secret.
            if not seat or seat["kind"] != "human" or not seat["token"] or seat["token"] != token: return False
        elif seat and seat["token"] != token:
            return False
        self.seats[power] = {"name": name or (seat or {}).get("name") or power, "token": token, "kind": "human"}
        self.active = time.time()
        return True

    def humans(self) -> list[str]:
        return sorted(p for p, s in self.seats.items() if s["kind"] == "human")

    def finished(self) -> bool:
        return bool(self.session and self.session.ended())

    def seat_of(self, token: str | None) -> str | None:
        if not token: return None
        return next((p for p, s in self.seats.items() if s["token"] == token), None)

    def touch(self, power: str | None) -> None:
        if power: self.seen[power] = self.active = time.time()

    def dropped(self, grace: int = 25) -> list[str]:
        now = time.time()
        return [p for p in self.humans() if now - self.seen.get(p, 0) > grace]

    def transfer(self, to: str) -> bool:
        if to in self.seats and self.seats[to]["kind"] == "human" and self.seats[to]["token"]:
            self.owner = self.seats[to]["token"]; return True
        return False

    def kick(self, power: str) -> str:
        s = self.seats.get(power)
        if not s or s["kind"] != "human" or s["token"] == self.owner: return ""
        self.seats.pop(power); self.short.discard(power); self.seen.pop(power, None)
        if self.session: self.session.aiify(power)
        return s["token"]

    def set_secs(self, s: int) -> None:
        self.secs = max(0, min(3600, int(s))); self.timer_on = self.secs > 0
        self.deadline = None; self.remaining = None; self.clock_turn = None; self.short.clear()

    def start(self) -> None:
        if self.status != "lobby" or self.session is not None:
            raise ValueError("This room has already started")
        self.session = Session(self.humans(), self.max_year, self.lang, game_mode=self.game_mode)
        self.session.end_rule = self.end_rule
        self.status = "playing"; self.active = time.time()

    def toggle_pause(self) -> None:
        if not self.session or self.status not in {"playing", "paused"} or self.finished():
            raise ValueError("Only an active game can be paused or resumed")
        if self.status == "playing":
            self.remaining = max(0, self.deadline - time.time()) if self.deadline is not None else None
            self.deadline = None; self.status = "paused"; self.session.pause()
        else:
            self.status = "playing"; self.session.resume()
            self.deadline = time.time() + self.remaining if self.remaining is not None else None
            self.remaining = None

    def summary(self) -> dict:
        return {"code": self.code, "name": self.name, "status": self.status, "lang": self.lang,
                "phase": self.session.eng.phase() if self.session else "-", "game_mode": self.game_mode,
                "humans": len(self.humans()), "seats": {p: s["name"] for p, s in self.seats.items()},
                "secs": self.secs, "locked": bool(self.passhash)}

    def metadata(self) -> dict:
        data = {k: getattr(self, k) for k in ("code", "storage_id", "name", "lang", "max_year", "game_mode",
                "passhash", "status", "created", "active", "seats", "owner", "secs", "end_rule")}
        data["remaining"] = max(0, self.deadline - time.time()) if self.deadline is not None else self.remaining
        return data


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}; self.tokens: dict[str, str] = {}

    def _bind(self, room):
        self.rooms[room.code] = room
        self.tokens[room.owner] = room.code
        for seat in room.seats.values():
            if seat["token"]: self.tokens[seat["token"]] = room.code
        if room.session:
            def changed():
                # Async AI completion changes the public readiness view too.
                # Advance the stream revision without sharing seat-specific data.
                room.version += 1
                self.checkpoint(room)
            room.session.on_change = changed

    def create(self, name: str, owner_name: str, power: str | None, lang="zh-Hans", passcode="",
               end_rule="", game_mode="classic", max_year=None) -> Room:
        if power is not None and power not in POWERS: raise ValueError("Invalid power")
        if game_mode not in {"classic", "plus"}: raise ValueError("Invalid game mode")
        if end_rule not in {"", "draw", "topcount"}: raise ValueError("Invalid end rule")
        if game_mode == "classic" and end_rule == "topcount": raise ValueError("Classic does not use top-count scoring")
        r = Room(name, owner_name, lang, max_year, passcode=passcode, game_mode=game_mode)
        while r.code in self.rooms: r.code = _code()
        r.end_rule = end_rule or "draw"
        if power: r.claim(power, owner_name, r.owner)
        self._bind(r); self.checkpoint(r)
        return r

    def join(self, code: str, power: str | None, name: str, token: str | None, passcode="") -> tuple[Room | None, str]:
        code = code.strip().upper()
        r = self.rooms.get(code)
        if not r or r.status == "ended": return None, "notfound"
        if power is not None and power not in POWERS: return None, "invalidpower"
        known = bool(token and self.tokens.get(token) == code)
        if r.passhash and not known and not secrets.compare_digest(_hash(passcode), r.passhash): return None, "badpass"
        tok = token if known else secrets.token_urlsafe(32)
        if power and not r.claim(power, name, tok): return None, "seatunavailable"
        self.tokens[tok] = code
        self.checkpoint(r)
        return r, tok

    def kick(self, code: str, power: str) -> bool:
        r = self.rooms.get(code); tok = r.kick(power) if r else ""
        if tok:
            self.tokens.pop(tok, None); self.checkpoint(r)
        return bool(tok)

    def list(self) -> list[dict]:
        return [r.summary() for r in self.rooms.values() if r.status != "ended"]

    def _directory(self, room):
        return Session.SAVES / "rooms" / room.storage_id

    def checkpoint(self, room):
        if room.session and room.session._settling and room.status != "ended": return
        directory = self._directory(room)
        blob = {"room": room.metadata(), "session": room.session.to_dict() if room.session else None,
                "members": [token for token, code in self.tokens.items() if code == room.code]}
        Session._write_json(directory / "resume.json", blob)

    def save(self, room, name="auto"):
        if not room.session: raise ValueError("Start a game before saving")
        if room.session._settling: raise ValueError("Wait until adjudication completes before saving")
        name = Session._safe_name(name)
        Session._write_json(self._directory(room) / "slots" / f"{name}.json", room.session.to_dict())
        self.checkpoint(room)
        return {"ok": True, "saved": name}

    def list_saves(self, room):
        return sorted(p.stem for p in (self._directory(room) / "slots").glob("*.json"))

    def load(self, room, name="auto"):
        if room.session and room.session._settling: raise ValueError("Wait until adjudication completes before loading")
        blob = json.loads((self._directory(room) / "slots" / f"{Session._safe_name(name)}.json").read_text())
        # A saved game cannot silently reassign or resurrect participants who have since left.
        if set(blob.get("humans", [])) != set(room.humans()):
            raise ValueError("The saved seats differ from the current room; restore is unavailable")
        session = Session.from_dict(blob)
        if room.session: room.session.close()
        room.session = session; room.status = "paused"; session.pause()
        room.game_mode = session.game_mode; room.max_year = session.max_year
        room.clock_turn = None; room.deadline = None; room.remaining = None; room.short.clear()
        self._bind(room); self.checkpoint(room)
        return room

    def recover(self, token: str):
        """Restart recovery uses an existing bearer credential, never a public save name."""
        if not token: return None
        for path in (Session.SAVES / "rooms").glob("*/resume.json"):
            try:
                blob = json.loads(path.read_text()); meta = blob["room"]
                if token not in blob.get("members", []): continue
                if meta["status"] == "ended": return None
                if meta["code"] in self.rooms: return None  # never revive a revoked in-memory credential
                room = Room(meta["name"], "", meta["lang"])
                for key, value in meta.items():
                    if hasattr(room, key): setattr(room, key, value)
                room.timer_on = room.secs > 0
                if blob.get("session"):
                    room.session = Session.from_dict(blob["session"]); room.status = "paused"; room.session.pause()
                    room.clock_turn = room.session.turn_id if room.remaining is not None else None
                self._bind(room)
                for member in blob.get("members", []): self.tokens[member] = room.code
                return room
            except (OSError, ValueError, KeyError):
                continue
        return None

    def end(self, room):
        room.status = "ended"; room.deadline = None
        if room.session: room.session.close()
        self.checkpoint(room)

    def gc(self, idle: int = 7200) -> None:
        now = time.time()
        dead = [c for c, r in self.rooms.items() if r.status == "ended" or
                (now - r.active > idle and (r.status == "lobby" or r.finished()))]
        for code in dead:
            room = self.rooms.pop(code)
            if room.session: room.session.close()
            room.status = "ended"; self.checkpoint(room)
            self.tokens = {tok: c for tok, c in self.tokens.items() if c != code}
