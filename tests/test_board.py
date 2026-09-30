"""The renderer's data must faithfully follow the rules engine."""
from diplomind.board import board_state
from diplomind.engine import OperationEngine


def test_board_has_all_standard_provinces_and_exact_armies():
    eng = OperationEngine()
    board = board_state(eng)
    provinces = {p["id"]: p for p in board["provinces"]}
    expected = {loc.upper().split("/")[0] for loc in eng.game.map.loc_type}
    assert set(provinces) == expected
    assert len(provinces) == 76  # 75 playable provinces plus Switzerland.
    assert len(board["units"]) == 22
    assert sum(p["center"] for p in provinces.values()) == 34
    assert provinces["MAO"]["type"] == "WATER"
    assert provinces["PAR"]["path_transform"] == [-195.0, -170.0]
    assert provinces["PAR"]["owner"] == "FRANCE"
    assert board["locations"]["STP/SC"] != board["locations"]["STP/NC"]
    assert {u["location"] for u in board["units"] if u["power"] == "FRANCE"} == {"PAR", "MAR", "BRE"}


def test_board_updates_after_moves_and_does_not_mutate_prior_snapshot():
    eng = OperationEngine()
    before = board_state(eng)
    eng.submit("FRANCE", ["A PAR - BUR", "A MAR - SPA", "F BRE - MAO"])
    eng.process()
    after = board_state(eng)
    assert {u["location"] for u in after["units"] if u["power"] == "FRANCE"} == {"BUR", "SPA", "MAO"}
    assert {u["location"] for u in before["units"] if u["power"] == "FRANCE"} == {"PAR", "MAR", "BRE"}
    assert before["phase"] != after["phase"]
    assert "orders" not in str(after.keys())


def test_board_reports_public_dislodged_units():
    eng = OperationEngine()
    eng.game.clear_units()
    eng.game.set_units("FRANCE", ["A PAR", "A GAS"])
    eng.game.set_units("GERMANY", ["A BUR"])
    eng.submit("FRANCE", ["A PAR - BUR", "A GAS S A PAR - BUR"])
    eng.submit("GERMANY", ["A BUR H"])
    eng.process()
    assert any(u["power"] == "GERMANY" and u["dislodged"] for u in board_state(eng)["units"])
