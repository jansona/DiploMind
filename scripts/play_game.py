"""真跑：7 国 4b 多相，挂 7 风格。用于晨验整局贯通与延迟。
用法: uv run python -m scripts.play_game [相数]"""
import asyncio
import sys

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.gateway import Gateway
from diplomind.orchestrator import Orchestrator
from diplomind.personalities import PERSONAS

PHASES = int(sys.argv[1]) if len(sys.argv) > 1 else 2
ROSTER = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]


async def main():
    gw = Gateway()
    eng = OperationEngine(ROSTER)
    ags = {c: Agent(c, list(PERSONAS.values())[i], gw) for i, c in enumerate(ROSTER)}
    res = await Orchestrator(eng, ags).run_game(max_phases=PHASES)
    print("结局:", res, "| 中心:", eng.centers())
    print("stats:", gw.log.stats())


if __name__ == "__main__":
    asyncio.run(main())
