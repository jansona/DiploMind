"""Unified player abstraction: human/AI are peers in the round flow; only the input source differs.
AIPlayer's input = LLM (attitude/intent are private cognition). HumanPlayer is a seat marker:
its input arrives via the web API (session.say / session.submit_orders), not through this class."""
from __future__ import annotations

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
    """Seat marker for a human power; session routes web input via _hmsgs/_horders."""
    def __init__(self, country: str) -> None:
        self.country = country
