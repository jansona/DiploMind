"""MessageBus — group/@/private channels, synchronous rounds: all sent, delivered at round end.

Each tagged with sender; inbox packed per power. End early if a whole round is silent."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Msg:
    rnd: int
    sender: str
    scope: str          # broadcast / private
    to: list[str]
    text: str
    phase: str = ""      # game phase (S1901M…) so history persists across phases


class MessageBus:
    def __init__(self) -> None:
        self.msgs: list[Msg] = []

    def post(self, rnd: int, sender: str, scope: str, to: list[str], text: str, phase: str = "") -> None:
        if text.strip():
            self.msgs.append(Msg(rnd, sender, scope, to, text, phase))

    def round_silent(self, rnd: int, phase: str = "") -> bool:
        return not any(m.rnd == rnd and m.phase == phase for m in self.msgs)

    def channels(self, power: str, upto_round: int) -> dict[str, list[str]]:
        """Group power-visible msgs by channel; full cross-phase history, labelled phase+round."""
        out: dict[str, list[str]] = {"群聊": []}
        for m in self.msgs:
            who = f"我({power})" if m.sender == power else m.sender
            tag = f"{m.phase[:5]} R{m.rnd}" if m.phase else f"R{m.rnd}"   # 哪相哪轮
            if m.scope == "broadcast":
                out["群聊"].append(f"{tag} {who}: {m.text}")
                continue
            members = sorted({m.sender, *m.to})
            if power not in members:
                continue                                    # private not involving me hidden
            out.setdefault("·".join(members), []).append(f"{tag} {who}: {m.text}")
        return out

    def inbox(self, power: str, upto_round: int, include_self: bool = False, recent: int = 2, phase: str = "") -> str:
        lines = []
        for m in self.msgs:
            if (phase and m.phase != phase) or m.rnd > upto_round or m.rnd <= upto_round - recent:  # current phase, last `recent` rounds
                continue
            who = f"我({power})" if m.sender == power else m.sender
            if m.scope == "broadcast":                       # broadcast visible to all (incl self)
                lines.append(f"R{m.rnd} {who}·群发: {m.text}")
            elif m.sender == power and include_self:          # own private
                lines.append(f"R{m.rnd} 我({power})·私聊@{','.join(m.to)}: {m.text}")
            elif power in m.to:                               # private to me
                lines.append(f"R{m.rnd} {who}·私聊@你: {m.text}")
        return "\n".join(lines)
