"""P3 引擎补全单测：整年跑通、非法剔除、存档续、判胜负、3-7 中立。"""
from diplomind.engine import OperationEngine


def test_full_year_cycles():
    eng = OperationEngine(["ENGLAND", "FRANCE", "GERMANY"])
    seen = []
    for _ in range(6):                       # 一年=S(M)→F(M,R)→W(A) 多相
        eng.auto_resolve()
        seen.append(eng.process())
        if eng.is_done():
            break
    assert any(p.startswith("S1902") for p in seen)   # 推进到次年


def test_illegal_held_and_save_load():
    eng = OperationEngine(["FRANCE"])
    r = eng.submit("FRANCE", ["A PAR - BUR", "A PAR - MOON"])
    assert r.accepted == ["A PAR - BUR"] and r.rejected
    blob = eng.save()
    eng2 = OperationEngine(); eng2.load(blob)
    assert eng2.phase() == eng.phase()


def test_auto_resolve_except_skips_human():
    eng = OperationEngine(["ENGLAND", "FRANCE", "GERMANY"])
    eng.auto_resolve(except_="FRANCE")                 # 人(法)不被兜底, 其余下令
    assert not eng.game.get_orders("FRANCE") and eng.game.get_orders("ENGLAND")


def test_neutral_and_endcheck():
    eng = OperationEngine(["FRANCE"])
    assert len(eng.dummy_powers) == 6                 # 1 活 6 中立
    end = eng.check_end(max_year=1900)
    assert end["draw"] and end["survivors"]           # 到上限 → 存活玩家和局
