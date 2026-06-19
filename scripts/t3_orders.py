"""任务3：1 国精简五步(感知→意图→下令)，命令从合法表出，实测格式失败率。

跑 N 次，统计 illegal 命令占比 + JSON 失败率。"""
import sys

from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.gateway import Gateway
from diplomind.personalities import PERSONAS

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def main() -> None:
    gw = Gateway()
    legal_total = illegal_total = 0
    for i in range(N):
        eng = OperationEngine(active_powers=["ENGLAND", "FRANCE", "GERMANY"])
        ag = Agent("FRANCE", PERSONAS["bully"], gw)
        it = ag.intent(eng)
        out, chosen = ag.decide_orders(eng)
        proposed = out.orders if out else []
        illegal = [o for o in proposed if o not in chosen]
        legal_total += len(chosen); illegal_total += len(illegal)
        print(f"#{i} intent={it.goal if it else None!r} orders={chosen} illegal={illegal}")
    print(f"\nillegal {illegal_total}/{legal_total+illegal_total} | {gw.log.stats()}")


if __name__ == "__main__":
    main()
