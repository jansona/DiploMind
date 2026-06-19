"""LLM 结构化输出 schema。命令一律从引擎合法表挑，非法即 hold。
字段宽松带默认：小模型常吐 null/缺字段，default 兜底避免无谓重试。"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Intent(BaseModel):
    """隐藏意图：私有短文，只喂自己，永不外发。"""
    goal: str = Field("", description="本回合真目标，一句话")
    ally: str = Field("", description="想拉拢谁")
    target: str = Field("", description="想坑谁")
    move_turn: int = Field(0, description="预计第几回合动手")

    @field_validator("goal", "ally", "target", mode="before")
    @classmethod
    def _str(cls, v):  # 小模型常吐 null/列表，统一压成字符串
        if v is None:
            return ""
        return ", ".join(map(str, v)) if isinstance(v, list) else str(v)

    @field_validator("move_turn", mode="before")
    @classmethod
    def _int(cls, v):
        return v if isinstance(v, int) else 0


class OrderSet(BaseModel):
    """下令：每条必须原样取自给定合法命令表。"""
    orders: list[str] = Field(default_factory=list, description="从合法表逐字挑选的命令")
    reasoning: str = Field("", description="一句话理由")


class Message(BaseModel):
    """谈判一条发言。精简三字段，压格式失败。"""
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
