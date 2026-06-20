"""真跑：7 国 4b 打到指定年, 不限相数(打完整年)。
用法: uv run python -m scripts.play_game [结束年=1904]"""
import asyncio
import sys

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.gateway import Gateway
from diplomind.orchestrator import Orchestrator
from diplomind.personalities import PERSONAS

MAXYEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 1904
ROSTER = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]


async def main():
    gw = Gateway()
    eng = OperationEngine(ROSTER)
    ags = {c: Agent(c, list(PERSONAS.values())[i], gw) for i, c in enumerate(ROSTER)}
    res = await Orchestrator(eng, ags).run_game(max_phases=999, max_year=MAXYEAR)  # 只靠年份收
    print("结局:", res, "| 中心:", eng.centers())
    print("stats:", gw.log.stats())


if __name__ == "__main__":
    asyncio.run(main())
