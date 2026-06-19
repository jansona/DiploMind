"""消息总线 MessageBus — 三态通道(大群/@/私聊)，轮次同步：本轮全发完，轮末统一投递。

每条带来源标签；为某国打包 inbox。提前结束=某轮全员静默(无消息)。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Msg:
    rnd: int
    sender: str
    scope: str          # broadcast / private
    to: list[str]
    text: str


class MessageBus:
    def __init__(self) -> None:
        self.msgs: list[Msg] = []

    def post(self, rnd: int, sender: str, scope: str, to: list[str], text: str) -> None:
        if text.strip():
            self.msgs.append(Msg(rnd, sender, scope, to, text))

    def round_silent(self, rnd: int) -> bool:
        return not any(m.rnd == rnd for m in self.msgs)

    def inbox(self, power: str, upto_round: int) -> str:
        lines = []
        for m in self.msgs:
            if m.rnd > upto_round or m.sender == power:
                continue
            if m.scope == "broadcast":
                lines.append(f"[{m.sender}·群发] {m.text}")
            elif power in m.to:
                lines.append(f"[{m.sender}·私聊@你] {m.text}")
        return "\n".join(lines)
