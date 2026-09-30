"""Executable classic-rule scenarios; AI and renderers never adjudicate moves."""
from diplomind.engine import OperationEngine


def position(**units):
    engine = OperationEngine()
    engine.game.clear_units()
    for power, army in units.items():
        engine.game.set_units(power, army)
    return engine


def test_equal_attacks_bounce_and_support_breaks_tie():
    eng = position(FRANCE=["A PAR", "A PIC"], GERMANY=["A MUN"])
    eng.submit("FRANCE", ["A PAR - BUR", "A PIC H"])
    eng.submit("GERMANY", ["A MUN - BUR"])
    eng.process()
    assert "A PAR" in eng.game.powers["FRANCE"].units
    assert "A MUN" in eng.game.powers["GERMANY"].units
    eng.submit("FRANCE", ["A PAR - BUR", "A PIC S A PAR - BUR"])
    eng.submit("GERMANY", ["A MUN - BUR"])
    eng.process()
    assert "A BUR" in eng.game.powers["FRANCE"].units
    assert "A MUN" in eng.game.powers["GERMANY"].units


def test_attack_cuts_support_even_without_dislodging_supporter():
    eng = position(FRANCE=["A PAR", "A PIC"], GERMANY=["A BUR", "A BEL"])
    eng.submit("FRANCE", ["A PAR - BUR", "A PIC S A PAR - BUR"])
    eng.submit("GERMANY", ["A BUR H", "A BEL - PIC"])
    eng.process()
    assert sorted(eng.game.powers["FRANCE"].units) == ["A PAR", "A PIC"]
    assert "A BUR" in eng.game.powers["GERMANY"].units


def test_army_crosses_water_only_with_valid_convoy():
    eng = position(ENGLAND=["A LON", "F ENG"])
    assert "A LON - BEL VIA" in eng.legal_orders("ENGLAND")["LON"]
    eng.submit("ENGLAND", ["A LON - BEL VIA", "F ENG C A LON - BEL"])
    eng.process()
    assert "A BEL" in eng.game.powers["ENGLAND"].units
    assert "BEL" not in eng.game.powers["ENGLAND"].centers  # Spring occupation is not ownership.
    eng.submit("ENGLAND", ["A BEL H", "F ENG H"])
    eng.process()
    assert "BEL" in eng.game.powers["ENGLAND"].centers


def test_coast_specific_fleet_cannot_cross_wrong_coast():
    eng = position(RUSSIA=["F STP/SC"])
    legal = set(eng.legal_orders("RUSSIA")["STP"])
    assert "F STP/SC - BOT" in legal
    assert "F STP/SC - BAR" not in legal
    assert eng.submit("RUSSIA", ["F STP/SC - BAR"]).has_error


def test_dislodged_army_cannot_retreat_to_attack_origin():
    eng = position(FRANCE=["A PAR", "A PIC"], GERMANY=["A BUR"])
    eng.submit("FRANCE", ["A PAR - BUR", "A PIC S A PAR - BUR"])
    eng.submit("GERMANY", ["A BUR H"])
    assert eng.process().endswith("R")
    legal = set(eng.legal_orders("GERMANY")["BUR"])
    assert "A BUR R PAR" not in legal
    assert "A BUR D" in legal
    assert "A BUR R MUN" in legal
    eng.submit("GERMANY", ["A BUR R MUN"])
    eng.process()
    assert "A MUN" in eng.game.powers["GERMANY"].units


def test_builds_require_owned_vacant_home_center():
    eng = position(FRANCE=["A PAR", "F BRE"])
    eng.game.set_current_phase("W1901A")
    eng.game.set_centers("FRANCE", ["PAR", "MAR", "BRE", "SPA"])
    eng._possible = None
    legal = {order for values in eng.legal_orders("FRANCE").values() for order in values}
    assert "A MAR B" in legal and "F MAR B" in legal
    assert "A PAR B" not in legal and "A SPA B" not in legal
