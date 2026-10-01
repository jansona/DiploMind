"""LLM structured-output schemas. Orders must come from the engine legal list; illegal=hold.
Lenient fields with defaults: small models emit null/missing; defaults avoid retries."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Intent(BaseModel):
    """Hidden intent: private, fed only to self."""
    goal: str = Field("", description="本回合真目标，一句话")
    ally: str = Field("", description="想拉拢谁")
    target: str = Field("", description="想坑谁")
    grab: list[str] = Field(default_factory=list, description="本回合要占的中心(1-2个省名,无主或敌方皆可)")
    move_turn: int = Field(0, description="预计第几回合动手")

    @field_validator("grab", mode="before")
    @classmethod
    def _g(cls, v):
        return [str(v)] if isinstance(v, str) and v else ([str(x) for x in v] if isinstance(v, list) else [])

    @field_validator("goal", "ally", "target", mode="before")
    @classmethod
    def _str(cls, v):  # coerce null/list to string
        if v is None:
            return ""
        return ", ".join(map(str, v)) if isinstance(v, list) else str(v)

    @field_validator("move_turn", mode="before")
    @classmethod
    def _int(cls, v):
        return v if isinstance(v, int) else 0


class AttitudeUpdate(BaseModel):
    """Accept {country: score} or {country: {trust, attitude}}; also list/null, normalized."""
    scores: dict[str, int] = Field(default_factory=dict, description='如 {"GERMANY": -50}')
    attitudes: dict[str, str] = Field(default_factory=dict, description='如 {"GERMANY": "盟友"}，一句话定性')

    @field_validator("scores", mode="before")
    @classmethod
    def _norm(cls, v):
        if isinstance(v, list):                                  # [{"country":x,"trust":n}] → {x:n}
            v = {d.get("country", ""): d.get("trust", d.get("trust_score", 0)) for d in v if isinstance(d, dict)}
        if not isinstance(v, dict):
            return {}
        out = {}
        for k, n in v.items():
            n = n.get("trust", 0) if isinstance(n, dict) else n  # {国:{trust,attitude}} → 取分
            try:
                out[k] = int(n)
            except (TypeError, ValueError):
                out[k] = 0                                       # null/坏 → 0
        return out

    @field_validator("attitudes", mode="before")
    @classmethod
    def _att(cls, v):
        if not isinstance(v, dict):
            return {}
        return {k: str(a) for k, a in v.items() if a is not None}


class UnitPlan(BaseModel):
    """A compact intended action, independently checked against final orders."""
    unit: str = Field("", max_length=16, description="己方单位，如 A PAR 或 F SPA/SC；WAIVE 写 WAIVE")
    order: str = Field("", max_length=100, description="该单位最终选择的完整合法命令或合法编号")

    @field_validator("unit", "order", mode="before")
    @classmethod
    def _text(cls, value):
        return str(value) if isinstance(value, (str, int)) else ""


class OrderSet(BaseModel):
    """Brief decision first, inspectable unit plan, executable orders last."""
    reasoning: str = Field("", description="先用一句话说明最终决定及承诺/风险取舍，不要长篇推演或在命令后改口")
    intentional_self_standoffs: list[str] = Field(
        default_factory=list, description="仅当有意让己方多单位争同一省时列出该省缩写，并在 reasoning 解释；否则留空")
    unit_plan: list[UnitPlan] = Field(default_factory=list, max_length=64,
        description="逐个列出每个将下令单位的 unit 和最终 order；必须与最后 orders 一致")
    orders: list[str] = Field(default_factory=list, description="最后输出；从合法表逐字挑选，与 unit_plan 完全一致的最终命令")

    @field_validator("unit_plan", mode="before")
    @classmethod
    def _plan(cls, value):
        return [] if value is None else value

    @field_validator("intentional_self_standoffs", mode="before")
    @classmethod
    def _standoffs(cls, value):
        if isinstance(value, str):
            value = [value]
        return [str(v).upper().strip().split("/")[0] for v in value] if isinstance(value, list) else []


class Message(BaseModel):
    """One negotiation message; slim 3 fields."""
    type: Literal["broadcast", "private"] = Field("broadcast", description="broadcast 或 private")
    recipient: list[Literal["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]] = Field(
        default_factory=list, max_length=6, description="private 必须列出至少一个其他国家；broadcast 必须留空")
    content: str = Field("", description="内容，可真可假，留空=本轮静默")

    @field_validator("type", mode="before")
    @classmethod
    def _t(cls, v):
        value = str(v).strip().lower()
        if value not in {"private", "broadcast"}:
            raise ValueError("invalid_message_scope")
        return value

    @field_validator("recipient", mode="before")
    @classmethod
    def _r(cls, v):
        if v is None or v == "":
            return []
        values = [v] if isinstance(v, str) else v
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise ValueError("invalid_message_recipient")
        values = [x.strip().upper() for x in values]
        powers = {"AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"}
        if len(values) > 6 or any(x not in powers for x in values):
            raise ValueError("invalid_message_recipient")
        return sorted(set(values))

    @model_validator(mode="after")
    def _no_blackhole(self):
        # Ambiguous/invalid audiences fail closed; never broaden private intent.
        if ((self.type == "private" and not self.recipient)
                or (self.type == "broadcast" and self.recipient)):
            raise ValueError("invalid_message_audience")
        return self
