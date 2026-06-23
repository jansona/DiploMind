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
    assert end["winner"] == "RUSSIA" and end["centers"] == 4   # 到上限 → 中心最多者胜(俄4)


def test_last_orders():
    eng = OperationEngine(["FRANCE"])
    eng.submit("FRANCE", ["A PAR - BUR"]); eng.process()
    assert eng.last_orders().get("FRANCE") == ["A PAR - BUR"]   # 上回合命令可感知


def test_endcheck_most_centers_wins_tie_draws():
    eng = OperationEngine(["FRANCE", "ENGLAND"])
    assert eng.check_end(max_year=1900)["winner"] == "RUSSIA"   # RUSSIA 4 = sole top -> wins
    eng.game.powers["RUSSIA"].centers = ["MOS", "WAR"]          # drop RUSSIA to 2 -> 5-way tie at 3
    end = eng.check_end(max_year=1900)
    assert end["draw"] and "RUSSIA" not in end["survivors"]     # tie among co-leaders only


def test_endcheck_draw_mode_all_survivors():
    eng = OperationEngine(["FRANCE"])
    end = eng.check_end(max_year=1900, draw_all=True)        # classic mode: all survivors draw, no top-rank
    assert end["draw"] and len(end["survivors"]) == 7 and "winner" not in end
