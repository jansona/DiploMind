"""任务4+5：3 国并发谈判(≤5轮,全员静默提前止)→下令→结算，记总耗时/token/失败率。"""
import asyncio
import time

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.gateway import Gateway
from diplomind.orchestrator import Orchestrator
from diplomind.personalities import PERSONAS

ROSTER = {"ENGLAND": "turtle", "FRANCE": "bully", "GERMANY": "schemer"}


async def main() -> None:
    gw = Gateway()
    eng = OperationEngine(active_powers=list(ROSTER))
    agents = {c: Agent(c, PERSONAS[p], gw) for c, p in ROSTER.items()}
    orch = Orchestrator(eng, agents)
    t0 = time.time()
    res = await orch.run_round()
    wall = round(time.time() - t0, 1)
    print(f"谈判轮数={res['nego_rounds']} 结算→{res['phase']}")
    for c, r in res["orders"].items():
        print(f"  {c}: {r['orders']} rej={r['rejected']}")
    print(f"墙钟={wall}s  {gw.log.stats()}")


if __name__ == "__main__":
    asyncio.run(main())
