"""P4 编排器单测：静默提前止、多相不崩。用假网关免 LLM。"""
import asyncio

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.orchestrator import Orchestrator
from diplomind.personalities import PERSONAS
from diplomind.schemas import AttitudeUpdate, Intent, Message, OrderSet


class SilentGW:
    def chat(self, m, s, tag="", retry=2, temp=None): return self._mk(s)
    async def achat(self, m, s, tag="", retry=2, temp=None): return self._mk(s)
    def _mk(self, s):
        if s is Intent: return Intent(goal="守")
        if s is AttitudeUpdate: return AttitudeUpdate()
        if s is Message: return Message(content="")        # 全员静默
        if s is OrderSet: return OrderSet(orders=[])
        return None


def _orch():
    eng = OperationEngine(["ENGLAND", "FRANCE", "GERMANY"])
    ags = {c: Agent(c, PERSONAS["turtle"], SilentGW()) for c in eng.active_powers}
    return Orchestrator(eng, ags), eng


def test_silence_early_stop():
    orch, _ = _orch()
    assert asyncio.run(orch.negotiate()) == 1          # 首轮全静默→提前止

def test_multi_phase_no_crash():
    orch, eng = _orch()
    res = asyncio.run(orch.run_game(max_phases=3))
    assert res["phases"] == 3 and not eng.is_done()     # 3相跑通不崩
