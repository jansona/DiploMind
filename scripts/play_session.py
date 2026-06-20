"""全AI跑Session到指定年, 验背叛/记仇涌现。用法: uv run python -m scripts.play_session [年=1903]"""
import asyncio, sys
from diplomind.session import Session, POWERS

YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 1903


async def main():
    s = Session(None, max_year=YEAR)
    for _ in range(40):
        await s.begin_phase()
        for _ in range(8):
            await asyncio.sleep(0.3)
            if s.mode == "ORDERS": break
        r = await s.submit([])
        print("结算", r["phase"], "中心", s.eng.centers())
        if r.get("end"): print("结局", r["end"]); break
    bet = [(c, a.actor, a.action) for c, ag in s.ai.items() for a in ag.mem.actions if a.betray]
    print("背叛:", bet or "无")
    print("关系:", {c: {k: v.trust for k, v in ag.mem.relations.items() if v.trust} for c, ag in s.ai.items()})

asyncio.run(main())
