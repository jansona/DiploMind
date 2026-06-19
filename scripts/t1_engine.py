"""任务1 最小测试：3 国小局，跑通 legal_orders -> submit -> process。

三国 = England / France / Germany；其余 4 国中立（不下令=全 hold）。
含一条故意非法命令，验证「非法=剔除+记录」不崩。
"""
from diplomind.engine import OperationEngine

ACTIVE = ["ENGLAND", "FRANCE", "GERMANY"]


def main() -> None:
    eng = OperationEngine(active_powers=ACTIVE)
    print(f"phase={eng.phase()} active={eng.active_powers} dummy={eng.dummy_powers}")

    # 每国从合法表挑首个非 hold 命令，掺一条非法命令验证校验
    for power in ACTIVE:
        legal = eng.legal_orders(power)
        picks = [opts[0] for opts in legal.values() if opts]
        picks.append("A PAR - MOON")  # 非法
        r = eng.submit(power, picks)
        print(f"{power}: ok={r.accepted} rejected={r.rejected}")

    nxt = eng.process()
    print(f"processed -> {nxt}  centers={eng.centers()}  done={eng.is_done()}")
    blob = eng.save()
    print(f"save ok: {len(blob.get('phases', []))} phases recorded")


if __name__ == "__main__":
    main()
