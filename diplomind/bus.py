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

    def channels(self, power: str, upto_round: int) -> dict[str, list[str]]:
        """按频道分组该国可见消息：'群聊' + 各私聊国家组合(键=排序成员)。每条带轮次。"""
        out: dict[str, list[str]] = {"群聊": []}
        for m in self.msgs:
            if m.rnd > upto_round:
                continue
            who = f"我({power})" if m.sender == power else m.sender
            if m.scope == "broadcast":
                out["群聊"].append(f"R{m.rnd} {who}: {m.text}")
                continue
            members = sorted({m.sender, *m.to})
            if power not in members:
                continue                                    # 与我无关的私聊不可见
            out.setdefault("·".join(members), []).append(f"R{m.rnd} {who}: {m.text}")
        return out

    def inbox(self, power: str, upto_round: int, include_self: bool = False) -> str:
        lines = []
        for m in self.msgs:
            if m.rnd > upto_round:
                continue
            who = f"我({power})" if m.sender == power else m.sender
            if m.scope == "broadcast":                       # 群聊全员可见(含自己)
                lines.append(f"R{m.rnd} {who}·群发: {m.text}")
            elif m.sender == power and include_self:          # 自己发的私聊
                lines.append(f"R{m.rnd} 我({power})·私聊@{','.join(m.to)}: {m.text}")
            elif power in m.to:                               # 发给我的私聊
                lines.append(f"R{m.rnd} {who}·私聊@你: {m.text}")
        return "\n".join(lines)
