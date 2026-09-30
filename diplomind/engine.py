"""OperationEngine — reuses the diplomacy engine for map/legal moves/adjudication/save.

Pure rules, no LLM. Illegal orders shouldn't normally occur (the LLM only picks
from the legal list); if one does, log it and hold that power — don't mask with
random moves.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from diplomacy import Game

log = logging.getLogger("diplomind")


@dataclass
class SubmitResult:
    power: str
    accepted: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (order, reason)

    @property
    def has_error(self) -> bool:
        return bool(self.rejected)


class OperationEngine:
    """Thin wrapper over diplomacy.Game exposing the interfaces we need."""

    def __init__(self, active_powers: Iterable[str] | None = None) -> None:
        self.game = Game()
        all_powers = list(self.game.powers.keys())
        self.active_powers = list(active_powers) if active_powers else all_powers
        # inactive powers = neutral: hold (no orders), no negotiation; engine just gives them nothing
        self.dummy_powers = [p for p in all_powers if p not in self.active_powers]
        self._possible: tuple[str, dict] | None = None   # (phase, all_possible_orders) — board only moves on process/load

    # --- state ---
    def phase(self) -> str:
        return self.game.get_current_phase()

    def is_done(self) -> bool:
        return self.game.is_game_done

    def centers(self) -> dict[str, int]:
        return {p: len(self.game.powers[p].centers) for p in self.game.powers}

    def neutral_centers(self) -> list[str]:
        owned = {c for pw in self.game.powers.values() for c in pw.centers}
        return sorted(s for s in self.game.map.scs if s not in owned)   # supply centers nobody holds

    # --- legal orders: per orderable location -> list of legal orders ---
    def _all_possible(self) -> dict:                 # cached per phase: SSE/state polls this many times a second
        ph = self.game.get_current_phase()
        if self._possible is None or self._possible[0] != ph:
            self._possible = (ph, self.game.get_all_possible_orders())
        return self._possible[1]

    def legal_orders(self, power: str) -> dict[str, list[str]]:
        all_orders = self._all_possible()
        locs = self.game.get_orderable_locations(power)
        return {loc: all_orders.get(loc, []) for loc in locs}

    # --- submit: validate each against legal list, drop illegal and record reason ---
    def submit(self, power: str, orders: list[str]) -> SubmitResult:
        legal = {o for opts in self.legal_orders(power).values() for o in opts}
        res = SubmitResult(power=power)
        seen = set()
        for o in orders:
            source = o.split()[1].split("/")[0] if len(o.split()) > 1 else o
            if o in legal and source in seen:
                res.rejected.append((o, "duplicate unit or build location"))
            elif o in legal:
                res.accepted.append(o); seen.add(source)
            else:
                res.rejected.append((o, "not in legal_orders"))
        if res.rejected:                                  # illegal=hold, but log so it's debuggable
            log.warning("非法令丢弃 %s -> hold: %s", power, [o for o, _ in res.rejected])
        self.game.set_orders(power, res.accepted)
        return res

    def last_orders(self) -> dict[str, list[str]]:
        """Most recent processed phase's orders per power — words vs deeds for AI perception."""
        oh = self.game.order_history
        last = list(oh.values())[-1] if oh else {}
        return {p: list(v) for p, v in last.items() if v}

    def last_adjudication(self) -> dict | None:
        recent = self.recent_adjudications(limit=1)
        return recent[-1] if recent else None

    def recent_adjudications(self, limit: int = 6) -> list[dict]:
        """Public, processed evidence only; never inspect the pending order buffer.

        Orders describe attempts. Result flags and the resulting public positions
        describe what actually happened (an empty flag list is not a location).
        Dislodged units retain the engine's leading ``*`` marker in board states.
        """
        history = self.game.result_history
        phases = list(history.keys())
        current = self.game.get_state()
        recent = []
        for index in range(max(0, len(phases) - max(0, limit)), len(phases)):
            phase = phases[index]
            before = self.game.state_history.get(phase, {})
            after = self.game.state_history[phases[index + 1]] if index + 1 < len(phases) else current
            recent.append({"phase": str(phase), "source": "public_result",
                           "orders": {p: list(orders) for p, orders in self.game.order_history.get(phase, {}).items()},
                           "results": {unit: [str(flag) for flag in flags] for unit, flags in history[phase].items()},
                           "units_before": {p: list(units) for p, units in before.get("units", {}).items()},
                           "units_after": {p: list(units) for p, units in after["units"].items()}})
        return recent

    def phase_type(self) -> str:
        return self.game.phase_type   # M=Movement R=Retreat A=Adjustment(build)

    def auto_resolve(self, except_=None) -> None:
        """Deterministic legal fallback. All adjudication remains in diplomacy.Game."""
        skip = {except_} if isinstance(except_, str) else set(except_ or ())
        for power in self.game.powers:
            if power in skip: continue
            legal = self.legal_orders(power); chosen = []; occupied = set()
            if self.phase_type() == "A":
                count = self.game.get_state()["builds"][power]["count"]
                flat = sorted({order for opts in legal.values() for order in opts})
                suffix = " B" if count > 0 else " D"
                for order in flat:
                    if not order.endswith(suffix): continue
                    loc = order.split()[1].split("/")[0]
                    if loc in occupied: continue
                    if len(chosen) >= abs(count): break
                    chosen.append(order); occupied.add(loc)
            elif self.phase_type() == "R":
                for loc, opts in sorted(legal.items()):
                    retreats = [o for o in sorted(opts) if " R " in o and o.rsplit(" ", 1)[1].split("/")[0] not in occupied]
                    if retreats:
                        chosen.append(retreats[0]); occupied.add(retreats[0].rsplit(" ", 1)[1].split("/")[0])
                    else:
                        chosen.extend(sorted(o for o in opts if o.endswith(" D"))[:1])
            else:
                chosen = [o for opts in legal.values() for o in sorted(opts) if o.endswith(" H")]
            self.game.set_orders(power, chosen)

    def check_end(self, max_year: int | None = None, draw_all: bool = True) -> dict | None:
        for p, n in self.centers().items():
            if n >= 18:                                   # 18 centers = solo win (both modes)
                return {"winner": p, "centers": n}
        yr = int("".join(filter(str.isdigit, self.phase())) or 0)
        if max_year is not None and yr > max_year:
            cen = self.centers()
            if draw_all:                                  # classic: all survivors draw, no ranking
                return {"draw": True, "capped": True, "survivors": sorted(p for p, n in cen.items() if n > 0), "centers": cen}
            top = max(cen.values())                       # optional Plus leaderboard: never a false solo victory
            leaders = sorted(p for p, n in cen.items() if n == top and n > 0)
            return {"leader": leaders[0], "capped": True, "draw": True, "survivors": sorted(p for p, n in cen.items() if n > 0), "centers": cen} if len(leaders) == 1 else {"draw": True, "capped": True, "survivors": sorted(p for p, n in cen.items() if n > 0), "centers": cen}
        if self.is_done():
            return {"draw": True, "survivors": sorted(p for p, n in self.centers().items() if n > 0), "centers": self.centers()}
        return None

    def process(self) -> str:
        self.game.process()
        return self.game.get_current_phase()

    def save(self) -> dict:
        from diplomacy.utils.export import to_saved_game_format
        return to_saved_game_format(self.game)

    def load(self, saved: dict) -> None:
        from diplomacy.utils.export import from_saved_game_format
        self.game = from_saved_game_format(saved)
        self._possible = None                        # new board, same phase string possible: drop cache
