"""OperationEngine — reuses the diplomacy engine for map/legal moves/adjudication/save.

Pure rules, no LLM. Illegal orders shouldn't normally occur (the LLM only picks
from the legal list); if one does, log it and hold that power — don't mask with
random moves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from diplomacy import Game


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

    # --- state ---
    def phase(self) -> str:
        return self.game.get_current_phase()

    def is_done(self) -> bool:
        return self.game.is_game_done

    def centers(self) -> dict[str, int]:
        return {p: len(self.game.powers[p].centers) for p in self.game.powers}

    # --- legal orders: per orderable location -> list of legal orders ---
    def legal_orders(self, power: str) -> dict[str, list[str]]:
        all_orders = self.game.get_all_possible_orders()
        locs = self.game.get_orderable_locations(power)
        return {loc: all_orders.get(loc, []) for loc in locs}

    # --- submit: validate each against legal list, drop illegal and record reason ---
    def submit(self, power: str, orders: list[str]) -> SubmitResult:
        legal = {o for opts in self.legal_orders(power).values() for o in opts}
        res = SubmitResult(power=power)
        for o in orders:
            if o in legal:
                res.accepted.append(o)
            else:
                res.rejected.append((o, "not in legal_orders"))
        self.game.set_orders(power, res.accepted)
        return res

    def phase_type(self) -> str:
        return self.game.phase_type   # M=Movement R=Retreat A=Adjustment(build)

    def auto_resolve(self, except_: str | None = None) -> None:
        """Fallback for retreat/build phases: each power takes the first legal order. except_ skips (human chose)."""
        for p in self.game.powers:
            if p == except_:
                continue
            legal = self.legal_orders(p)
            self.game.set_orders(p, [opts[0] for opts in legal.values() if opts])

    def check_end(self, max_year: int = 1910) -> dict | None:
        for p, n in self.centers().items():
            if n >= 18:                                   # 18 centers = solo win
                return {"winner": p, "centers": n}
        yr = int("".join(filter(str.isdigit, self.phase())) or 0)
        if yr >= max_year:                                # max year: all survivors (>0 centers) draw
            survivors = sorted([p for p, n in self.centers().items() if n > 0])
            return {"draw": True, "survivors": survivors, "centers": self.centers()}
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
