"""玩家统一抽象 — 人/AI 对等：同流程、同动作接口(发言/下令)，仅输入源不同。
AI 内部认知(态度/意图/记忆)是 AIPlayer 私有, 不属核心框架。人类计时以后再加。"""
from __future__ import annotations

import asyncio

from .agent import Agent
from .engine import OperationEngine
from .schemas import Message


class Player:
    country: str
    async def negotiate(self, eng: OperationEngine, inbox: str) -> Message | None: ...
    async def decide(self, eng: OperationEngine) -> list[str]: ...


class AIPlayer(Player):
    """输入源=LLM(需引导输出); 认知态度/意图为私有步骤。"""
    def __init__(self, agent: Agent) -> None:
        self.agent, self.country = agent, agent.country

    async def cognition(self, eng):
        await self.agent.a_update(eng); await self.agent.a_intent(eng)

    async def negotiate(self, eng, inbox):
        return await self.agent.a_negotiate(eng, inbox)

    async def decide(self, eng):
        _, chosen = await self.agent.a_decide_orders(eng); return chosen


class HumanPlayer(Player):
    """输入源=前端: act 阻塞在 future, 由 web 提交/跳过 resolve。"""
    def __init__(self, country: str) -> None:
        self.country = country
        self._msg: asyncio.Future | None = None
        self._orders: asyncio.Future | None = None

    async def negotiate(self, eng, inbox):
        self._msg = asyncio.get_event_loop().create_future()
        return await self._msg
    def submit_msg(self, m: Message | None):
        if self._msg and not self._msg.done(): self._msg.set_result(m)

    async def decide(self, eng):
        self._orders = asyncio.get_event_loop().create_future()
        return await self._orders
    def submit_orders(self, o: list[str]):
        if self._orders and not self._orders.done(): self._orders.set_result(o)
