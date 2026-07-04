"""Chronicle: per-phase text + public statements. Public info only; private excluded."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .bus import MessageBus


def generate(bus: MessageBus, phase: str, centers: dict[str, int], since: int = 0) -> str:
    """One segment per phase: public broadcasts since last entry + center counts."""
    public = [m for m in bus.msgs[since:] if m.scope == "broadcast"]   # private excluded; earlier msgs already chronicled
    lines = [f"=== {phase} ==="]
    for m in public:
        lines.append(f"{m.sender}公开宣称：{m.text}")
    lines.append("中心: " + ", ".join(f"{k}={v}" for k, v in sorted(centers.items())))
    return "\n".join(lines)


def book(segments: list[str]) -> str:
    return "\n\n".join(segments)


class Summary(BaseModel):
    text: str = Field("", description="一段叙事")


async def summarize_year(gw, year: str, public: list[str], centers: dict[str, int], lang: str = "zh-Hans") -> str:
    """AI 每年总结明面: 结盟/敌对/军队动向。复用同 LLM 服务, 非 AI 玩家。仅公开信息。"""
    p = (f"为《外交》写{year}年史一段(只用{lang}, 1-3句): 公开发言{public[-12:]}; 各国中心{centers}。"
         f"概括明面结盟、对敌、军队动向, 客观叙事, 不剧透暗盘。")
    out = await gw.achat([{"role": "system", "content": "外交编年史官"}, {"role": "user", "content": p}], Summary, tag="chronicle")
    return f"=== {year} ===\n" + (out.text if out else "(略)")
