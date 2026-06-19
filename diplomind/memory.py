"""记忆库 Memory（每国一份）。事实代码压、态度模型评。

- 关系表：信任分/态度，由 LLM 读事件评（apply_attitude 写回，非代码加减）。
- 承诺账本：剩余倒计时/永久，每回合 tick 减，到 0 失效；代码记。
- 行动记录：背叛戳，代码记。
- diary + 滚动摘要：旧回合压短，只出摘要+近3回合，防 KV 膨胀。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

RECENT = 3  # 摘要保留近 N 回合细节


@dataclass
class Commitment:
    to: str
    content: str
    round: int
    remaining: int | None  # None=永久
    fulfilled: bool = False

    @property
    def expired(self) -> bool:
        return self.remaining is not None and self.remaining <= 0


@dataclass
class Action:
    round: int
    actor: str
    action: str
    betray: bool = False


@dataclass
class Relation:
    trust: int = 0          # -100..100，模型评
    attitude: str = "中立"   # 模型给的一句话定性


@dataclass
class Memory:
    country: str
    relations: dict[str, Relation] = field(default_factory=dict)
    ledger: list[Commitment] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    diary: list[str] = field(default_factory=list)
    intent: dict | None = None   # 当前隐藏意图，只喂自己
    _summary: str = ""       # 旧回合压缩后的滚动摘要

    # --- 事实代码压 ---
    def add_commitment(self, to: str, content: str, rnd: int, turns: int | None) -> None:
        self.ledger.append(Commitment(to, content, rnd, turns))

    def record_action(self, rnd: int, actor: str, action: str, betray: bool = False) -> None:
        self.actions.append(Action(rnd, actor, action, betray))

    def tick(self) -> None:
        """回合推进：承诺剩余减 1，到 0 失效。"""
        for c in self.ledger:
            if c.remaining is not None and not c.fulfilled:
                c.remaining -= 1

    def active_commitments(self, power: str | None = None) -> list[Commitment]:
        cs = [c for c in self.ledger if not c.expired and not c.fulfilled]
        return [c for c in cs if c.to == power] if power else cs

    # --- 态度模型评：外部喂分，代码只写回 ---
    def apply_attitude(self, scores: dict[str, dict]) -> None:
        for ctry, v in scores.items():
            r = self.relations.setdefault(ctry, Relation())
            if "trust" in v:
                r.trust = max(-100, min(100, int(v["trust"])))
            if "attitude" in v:
                r.attitude = str(v["attitude"])

    def relation(self, power: str) -> Relation:
        return self.relations.setdefault(power, Relation())

    # --- diary + 滚动摘要 ---
    def add_diary(self, rnd_label: str, text: str) -> None:
        self.diary.append(f"[{rnd_label}] {text}")
        if len(self.diary) > RECENT:                 # 旧的压进摘要，控上下文
            old = self.diary[:-RECENT]
            self._summary = (self._summary + " " + " ".join(old)).strip()[-600:]
            self.diary = self.diary[-RECENT:]

    def summary(self) -> str:
        rel = ", ".join(f"{k}:{v.trust}/{v.attitude}" for k, v in self.relations.items()) or "无"
        com = ", ".join(f"{c.to}:{c.content}({c.remaining if c.remaining is not None else '永久'})"
                        for c in self.active_commitments()) or "无"
        return (f"关系[{rel}] 承诺[{com}] 摘要[{self._summary or '无'}] 近况[" +
                " | ".join(self.diary[-RECENT:]) + "]")

    def snapshot(self) -> dict:
        return {"country": self.country,
                "relations": {k: asdict(v) for k, v in self.relations.items()},
                "ledger": [asdict(c) for c in self.ledger],
                "actions": [asdict(a) for a in self.actions],
                "diary": self.diary, "summary": self._summary}
