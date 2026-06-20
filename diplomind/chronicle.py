"""Chronicle: per-phase text + public statements. Public info only; private excluded."""
from __future__ import annotations

from .bus import MessageBus


def generate(bus: MessageBus, phase: str, centers: dict[str, int]) -> str:
    """One segment per phase: public broadcasts + center counts."""
    public = [m for m in bus.msgs if m.scope == "broadcast"]   # private excluded
    lines = [f"=== {phase} ==="]
    for m in public:
        lines.append(f"{m.sender}公开宣称：{m.text}")
    lines.append("中心: " + ", ".join(f"{k}={v}" for k, v in sorted(centers.items())))
    return "\n".join(lines)


def book(segments: list[str]) -> str:
    return "\n\n".join(segments)
