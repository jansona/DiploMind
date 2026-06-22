"""Unified player abstraction: human/AI are peers, same flow and action interface (speak/order); only input differs.
AI cognition (attitude/intent/memory) is private to AIPlayer."""
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
    """Input = LLM; attitude/intent are private steps."""
    def __init__(self, agent: Agent) -> None:
        self.agent, self.country = agent, agent.country

    async def cognition(self, eng):
        await self.agent.a_update(eng); await self.agent.a_intent(eng)

    async def negotiate(self, eng, inbox):
        return await self.agent.a_negotiate(eng, inbox)

    async def decide(self, eng):
        _, chosen = await self.agent.a_decide_orders(eng); return chosen


class HumanPlayer(Player):
    """Input = frontend: act blocks on a future, resolved by web submit/skip."""
    def __init__(self, country: str) -> None:
        self.country = country
        self._msg: asyncio.Future | None = None
        self._orders: asyncio.Future | None = None

    async def negotiate(self, eng, inbox):
        self._msg = asyncio.get_running_loop().create_future()
        return await self._msg
    def submit_msg(self, m: Message | None):
        if self._msg and not self._msg.done(): self._msg.set_result(m)

    async def decide(self, eng):
        self._orders = asyncio.get_running_loop().create_future()
        return await self._orders
    def submit_orders(self, o: list[str]):
        if self._orders and not self._orders.done(): self._orders.set_result(o)
