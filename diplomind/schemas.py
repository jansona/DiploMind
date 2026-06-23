"""LLM structured-output schemas. Orders must come from the engine legal list; illegal=hold.
Lenient fields with defaults: small models emit null/missing; defaults avoid retries."""
from typing import Optional

from pydantic import BaseModel, Field, field_validator


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


class OrderSet(BaseModel):
    """Orders: each verbatim from the legal list."""
    orders: list[str] = Field(default_factory=list, description="从合法表逐字挑选的命令")
    reasoning: str = Field("", description="一句话理由")


class Message(BaseModel):
    """One negotiation message; slim 3 fields."""
    type: str = Field("broadcast", description="broadcast 或 private")
    recipient: list[str] = Field(default_factory=list, description="private 收件国列表，broadcast 留空")
    content: str = Field("", description="内容，可真可假，留空=本轮静默")

    @field_validator("type", mode="before")
    @classmethod
    def _t(cls, v):
        return "private" if str(v).lower().startswith("priv") else "broadcast"

    @field_validator("recipient", mode="before")
    @classmethod
    def _r(cls, v):
        if v is None or v == "":
            return []
        return [v] if isinstance(v, str) else [str(x) for x in v]
