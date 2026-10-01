"""Chronicle: per-phase text + public statements. Public info only; private excluded."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .bus import MessageBus


def generate(bus: MessageBus, phase: str, centers: dict[str, int], since: int = 0,
             adjudication: dict | None = None) -> str:
    """Grounded local chronicle: separate attributed claims from engine facts."""
    public = [m for m in bus.msgs[since:] if m.scope == "broadcast"]   # private excluded; earlier msgs already chronicled
    lines = [f"=== {phase} ==="]
    if public:
        lines.append("公开说法（仅为各国声明，不代表已确认的协议、位置或战果）：")
    for m in public:
        lines.append(f"{m.sender}公开宣称：{m.text}")
    if adjudication:
        lines.append(f"引擎裁决事实：{adjudication['phase']}")
        for unit, flags in adjudication.get("results", {}).items():
            if flags:
                lines.append(f"{unit}: {', '.join(flags)}")
        for power, units in adjudication.get("units_after", {}).items():
            lines.append(f"{power}裁决后位置：{', '.join(units)}")
    lines.append("中心: " + ", ".join(f"{k}={v}" for k, v in sorted(centers.items())))
    return "\n".join(lines)


def book(segments: list[str]) -> str:
    return "\n\n".join(segments)


class Summary(BaseModel):
    text: str = Field("", description="一段叙事")


async def summarize_year(gw, year: str, public: list[str], centers: dict[str, int], lang: str = "zh-Hans") -> str:
    """Optional attributed commentary, never called by the normal turn loop.

    Without board evidence this utility may summarize statements, not certify
    alliances, movement success, treaty breach, or positions.
    """
    p = (f"为《外交》写{year}年史一段(只用{lang}, 1-3句): 公开发言{public[-12:]}; 各国中心{centers}。"
         "只归纳各国公开说法，逐条归属发言者并保留不确定性；这里没有棋盘裁决证据，"
         "不得把声明升级为已成立盟约、已到达位置、成功行动或已证实背叛。不得推断暗盘。")
    out = await gw.achat([{"role": "system", "content": "外交编年史官"}, {"role": "user", "content": p}], Summary, tag="chronicle")
    return f"=== {year} ===\n" + (out.text if out else "(略)")
