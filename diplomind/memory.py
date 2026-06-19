"""记忆库 Memory（每国一份）。事实代码压、态度模型评。demo 精简版：关系分+近况摘要。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Memory:
    country: str
    relations: dict[str, int] = field(default_factory=dict)   # 国->信任分(模型评，demo 默认0)
    diary: list[str] = field(default_factory=list)            # 每回合自述
    intent: dict | None = None                                # 当前隐藏意图

    def summary(self) -> str:
        rel = ", ".join(f"{k}:{v}" for k, v in self.relations.items()) or "无"
        last = self.diary[-1] if self.diary else "无"
        return f"关系分[{rel}] 上回合盘算[{last}]"
