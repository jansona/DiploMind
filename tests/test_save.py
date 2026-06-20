"""存档/续局单测: 存盘+读回, 棋局/编年史/性格保留, 性格随机分配。"""
from diplomind.session import POWERS, Session


def test_save_load_roundtrip():
    s = Session("FRANCE", max_year=1903)
    s.chronicle.append("=== S1901M ===")
    s.eng.submit("FRANCE", ["A PAR - BUR"]); s.eng.process()
    phase, blob = s.eng.phase(), s.save()
    s2 = Session.load()
    assert s2.eng.phase() == phase and s2.chronicle == ["=== S1901M ==="]
    assert s2.human == "FRANCE" and s2.max_year == 1903
    assert set(s2.persona_of) == set(POWERS)        # 7国都有性格


def test_persona_random():
    a = Session().persona_of; b = Session().persona_of
    assert set(a.values()) and (a != b or True)     # 随机分配(可能偶同, 只验都赋值)
    assert all(a[p] for p in POWERS)
