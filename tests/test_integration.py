"""P6 联调：7 国意图→谈判→记忆→下令→结算全流程贯通(假网关,免 LLM)。"""
import asyncio

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.orchestrator import Orchestrator
from diplomind.personalities import PERSONAS
from diplomind.schemas import AttitudeUpdate, Attitude, Intent, Message, OrderSet


class StubGW:
    def chat(self, m, s, tag="", retry=2, temp=None): return self._mk(s)
    async def achat(self, m, s, tag="", retry=2, temp=None): return self._mk(s)
    def _mk(self, s):
        if s is Intent: return Intent(goal="扩张", target="GERMANY")
        if s is AttitudeUpdate: return AttitudeUpdate(scores=[Attitude(country="GERMANY", trust=-30)])
        if s is Message: return Message(content="缔盟?")
        if s is OrderSet: return OrderSet(orders=[])
        return None


def test_seven_powers_pipeline():
    powers = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]
    eng = OperationEngine(powers)
    ags = {c: Agent(c, list(PERSONAS.values())[i], StubGW()) for i, c in enumerate(powers)}
    orch = Orchestrator(eng, ags)
    res = asyncio.run(orch.run_game(max_phases=4))
    assert res["phases"] == 4
    assert all(a.mem.relation("GERMANY").trust == -30 for a in ags.values())  # 记忆串通
    assert all("country" in a.snapshot() for a in ags.values())
