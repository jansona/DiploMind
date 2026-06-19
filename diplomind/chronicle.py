"""编年史 Chronicle — 纯文本按年简述+公开发言。仅收公开信息(群发+落子)，私聊不进，不剧透暗盘。"""
from __future__ import annotations

from .bus import MessageBus


def generate(bus: MessageBus, phase: str, centers: dict[str, int]) -> str:
    """按相生成一段：公开广播 + 中心数。分段防超上下文。"""
    public = [m for m in bus.msgs if m.scope == "broadcast"]   # 私聊不入史
    lines = [f"=== {phase} ==="]
    for m in public:
        lines.append(f"{m.sender}公开宣称：{m.text}")
    lines.append("中心: " + ", ".join(f"{k}={v}" for k, v in sorted(centers.items())))
    return "\n".join(lines)


def book(segments: list[str]) -> str:
    return "\n\n".join(segments)
