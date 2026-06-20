"""操作引擎 OperationEngine — 复用 diplomacy 引擎做地图/合法走子/裁决/存档。

纯规则，不碰 LLM。非法/格式坏命令正常不该出现（LLM 只从合法列表选）；
一旦发生即记 error 日志并让该国 hold，事后修，不用随机走子掩盖。
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
    """对 diplomacy.Game 的薄封装，暴露 demo 验证清单任务1 需要的接口。"""

    def __init__(self, active_powers: Iterable[str] | None = None) -> None:
        self.game = Game()
        all_powers = list(self.game.powers.keys())
        self.active_powers = list(active_powers) if active_powers else all_powers
        # 非激活国 = 中立：不下令即全 hold，不参与谈判。引擎层只需不给它们命令。
        self.dummy_powers = [p for p in all_powers if p not in self.active_powers]

    # --- 状态 ---
    def phase(self) -> str:
        return self.game.get_current_phase()

    def is_done(self) -> bool:
        return self.game.is_game_done

    def centers(self) -> dict[str, int]:
        return {p: len(self.game.powers[p].centers) for p in self.game.powers}

    # --- 合法命令：每个可下令地块 -> 合法命令列表 ---
    def legal_orders(self, power: str) -> dict[str, list[str]]:
        all_orders = self.game.get_all_possible_orders()
        locs = self.game.get_orderable_locations(power)
        return {loc: all_orders.get(loc, []) for loc in locs}

    # --- 提交：逐条对照合法表校验，非法剔除并记录原因 ---
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
        return self.game.phase_type   # M=移动 R=撤退 A=造兵/调整

    def auto_resolve(self) -> None:
        """非主决策相(撤退/造兵)兜底：各国挑首条合法令，无则空，防卡相。"""
        for p in self.game.powers:
            legal = self.legal_orders(p)
            self.game.set_orders(p, [opts[0] for opts in legal.values() if opts])

    def check_end(self, max_year: int = 1910) -> dict | None:
        for p, n in self.centers().items():
            if n >= 18:                                   # 18中心独霸=胜
                return {"winner": p, "centers": n}
        yr = int("".join(filter(str.isdigit, self.phase())) or 0)
        if yr >= max_year:                                # 到最大回合: 所有存活玩家(>0中心)和局
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
