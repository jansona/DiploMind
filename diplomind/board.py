"""Public board data for both the interactive 3D board and accessible 2D view.

Geometry comes from the installed diplomacy package, the same map used by the
adjudicator. No orders, credentials, private messages or AI plans cross this
boundary. SVG path coordinates retain their documented layer translation.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from xml.etree import ElementTree as ET

import diplomacy

from .engine import OperationEngine
from .names import PROVINCES

_NS = {"svg": "http://www.w3.org/2000/svg", "jdip": "svg.dtd"}
POWER_COLORS = {
    "AUSTRIA": "#c45757", "ENGLAND": "#9c83cc", "FRANCE": "#4e91cb",
    "GERMANY": "#838a97", "ITALY": "#65a780", "RUSSIA": "#d6cead",
    "TURKEY": "#d9af50",
}


def _location(value: str, aliases: dict[str, str]) -> str:
    value = value.removeprefix("_").upper().replace("-", "/")
    return aliases.get(value, value)


@lru_cache(maxsize=1)
def _geometry() -> dict:
    """Parse trusted package data once, never client-supplied SVG/XML."""
    engine = OperationEngine()
    game_map = engine.game.map
    path = Path(diplomacy.__file__).parent / "maps" / "svg" / "standard.svg"
    root = ET.parse(path).getroot()
    _, _, width, height = (float(x) for x in root.attrib["viewBox"].split())
    layer = root.find('svg:g[@id="MapLayer"]', _NS)
    if layer is None:
        raise RuntimeError("The Diplomacy standard SVG has no MapLayer")
    transform = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", layer.attrib.get("transform", ""))]
    if len(transform) != 2:
        raise RuntimeError("Unsupported Diplomacy SVG transform")
    aliases = game_map.aliases
    coordinates: dict[str, dict] = {}
    for province in root.findall("jdip:PROVINCE_DATA/jdip:PROVINCE", _NS):
        loc = _location(province.attrib["name"], aliases)
        unit = province.find("jdip:UNIT", _NS)
        dislodged = province.find("jdip:DISLODGED_UNIT", _NS)
        if unit is not None:
            coordinates[loc] = {"x": float(unit.attrib["x"]) + 20, "y": float(unit.attrib["y"]) + 20}
        if dislodged is not None and loc in coordinates:
            coordinates[loc]["dislodged_x"] = float(dislodged.attrib["x"]) + 20
            coordinates[loc]["dislodged_y"] = float(dislodged.attrib["y"]) + 20
    supply = {}
    for marker in root.findall('svg:g[@id="SupplyCenterLayer"]/*', _NS):
        loc = marker.attrib.get("id", "").removeprefix("sc_")
        if loc:
            supply[loc] = {"x": float(marker.attrib["x"]) + 10, "y": float(marker.attrib["y"]) + 10}
    types = {loc.upper(): terrain for loc, terrain in game_map.loc_type.items()}
    provinces = []
    for node in layer:
        loc = _location(node.attrib.get("id", ""), aliases)
        if loc not in types or "/" in loc:
            continue
        paths = [p.attrib["d"] for p in node.iter() if "d" in p.attrib]
        if not paths:
            continue
        pos = coordinates.get(loc, {"x": 710, "y": 935})  # Switzerland has no unit slot.
        names = PROVINCES.get(loc, (loc, loc))
        provinces.append({"id": loc, "name": names[0], "name_zh": names[1],
                          "type": types[loc], "paths": paths, "path_transform": transform,
                          "x": pos["x"], "y": pos["y"], "center": loc in game_map.scs,
                          "center_position": supply.get(loc),
                          "adjacent": sorted({p.upper().split("/")[0] for p in game_map.loc_abut.get(loc, [])})})
    return {"width": width, "height": height, "provinces": provinces,
            "locations": coordinates, "colors": POWER_COLORS,
            "attribution": "Standard map geometry: diplomacy / jDip (GPL); adjudication: diplomacy (AGPLv3)"}


def board_state(engine: OperationEngine) -> dict:
    """Return a fresh public snapshot. Do not mutate cached geometry."""
    geometry = _geometry()
    centers = {power: list(p.centers) for power, p in engine.game.powers.items()}
    owners = {loc: power for power, locations in centers.items() for loc in locations}
    influence = {loc.upper().split("/")[0]: power for power, p in engine.game.powers.items()
                 for loc in p.influence}
    provinces = [{**province, "owner": owners.get(province["id"]),
                  "influence": influence.get(province["id"])} for province in geometry["provinces"]]
    units = []
    for power, state in engine.game.powers.items():
        for raw, dislodged in [(u, False) for u in state.units] + [(u, True) for u in state.retreats]:
            unit_type, loc = raw.lstrip("*").split()[:2]
            pos = geometry["locations"].get(loc, geometry["locations"].get(loc.split("/")[0]))
            if pos is None:
                continue
            units.append({"power": power, "type": unit_type, "location": loc,
                          "x": pos.get("dislodged_x", pos["x"]) if dislodged else pos["x"],
                          "y": pos.get("dislodged_y", pos["y"]) if dislodged else pos["y"],
                          "dislodged": dislodged})
    return {**geometry, "phase": engine.phase(), "provinces": provinces,
            "units": units, "centers": centers}
