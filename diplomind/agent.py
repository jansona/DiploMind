"""AI agent — 5 async steps: perceive/attitude/intent/negotiate/order."""
from __future__ import annotations

import logging

from .engine import OperationEngine
from .gateway import Gateway
from .memory import Memory
from .personalities import Persona, system_prompt
from .schemas import AttitudeUpdate, Intent, Message, OrderSet

log = logging.getLogger("diplomind")


class Agent:
    def __init__(self, country: str, persona: Persona, gw: Gateway, lang: str = "zh-Hans") -> None:
        self.country, self.persona, self.gw = country, persona, gw
        self.mem = Memory(country)
        self.sys = {"role": "system", "content": system_prompt(country, persona, lang)}

    # 1. perceive (no model): board+inbox+memory -> text
    def perceive(self, eng: OperationEngine, inbox: str = "") -> str:
        g = eng.game
        units = {p: g.powers[p].units for p in eng.active_powers}  # all units: rivals' scale matters for talks
        cen = eng.centers()
        last = eng.last_orders()                                    # everyone's deeds last phase: compare to their words
        return (f"阶段:{eng.phase()} 中心:{cen} 单位:{units}\n上回合各国命令(言行对照):{last}\n"
                f"记忆:{self.mem.summary()}\n收件:\n{inbox or '（无）'}")

    NEGO_TPL = ('像真人谈判：一两句话讲清意图(结盟/交易/威胁/妥协)即可，别长篇大论，口吻自然。\n'
                '关键：单干赢不了——多数进攻要拉盟友互相 support 才能破防；主动结盟、约互保、瓜分弱国，无接壤就先攀邻国关系。\n'
                '对照棋盘+各国上回合命令(言行)+记忆(承诺/恩怨)：守信高就守诺、低就利用；谁言行不一或背刺过你当面点破/施压。'
                '收到私聊优先私聊回发件人，别只群发；按性格选群发或私聊拉人。\n'
                '只输出此 JSON：{"type":"broadcast","recipient":[],"content":"…"}\n'
                'broadcast=群发(recipient 留空)；private=私聊(recipient 填国名)；无话则 content 留空(静默)。')

    def _legal_flat(self, eng: OperationEngine) -> list[str]:
        legal = eng.legal_orders(self.country)
        return sorted({o for v in legal.values() for o in v})

    @staticmethod
    def _norm(o: str) -> str:                                # canonicalize spacing/case for fuzzy legal match
        return " ".join(str(o).upper().replace("-", " - ").split())

    def _match(self, orders: list[str], flat: list[str]) -> list[str]:
        canon = {self._norm(o): o for o in flat}             # near-miss (A PAR-BUR) -> legal (A PAR - BUR)
        return [canon[self._norm(o)] for o in orders if self._norm(o) in canon]

    def _order_prompt(self, eng: OperationEngine, flat: list[str]) -> str:
        n = len(eng.legal_orders(self.country))
        return (self.perceive(eng) + f"\n意图:{self.mem.intent}\n你是 {self.country}，仅指挥自己 {n} 个单位。"
                f"进攻多需配合: 主攻方向用 S 支援自己或盟友, 单兵硬冲常 bounce。"
                f"扩张优先: 抢无主中心是涨中心最快的路, 别全 hold; 多数单位该移动占地, 仅必要才原地。"
                f"从下列合法命令逐字复制，每单位恰好一条，共 {n} 条放入 orders 数组(只放命令字符串)：\n"
                + "\n".join(flat) + f'\n示例:{{"orders":["{flat[0]}"],"reasoning":"一句话"}}')

    def snapshot(self) -> dict:
        return {"country": self.country, "persona": self.persona.name, "mem": self.mem.snapshot()}

    # all steps async (AI concurrent; humans do these mentally)
    async def a_update(self, eng: OperationEngine, inbox: str = "") -> AttitudeUpdate | None:
        prompt = (self.perceive(eng, inbox) + '\n据近况评各国信任分与定性。'
                  'scores 字典 {"国名":-100到100}；attitudes 字典 {"国名":"盟友/敌对/中立等一句话"}。')
        out = await self.gw.achat([self.sys, {"role": "user", "content": prompt}], AttitudeUpdate, tag=f"{self.country}:attitude")
        if out:
            merged = {c: {"trust": t} for c, t in out.scores.items()}
            for c, a in out.attitudes.items():
                merged.setdefault(c, {})["attitude"] = a
            self.mem.apply_attitude(merged)
        return out

    async def a_intent(self, eng: OperationEngine) -> Intent | None:
        prev = f"上回合意图(延续微调):{self.mem.intent}\n" if self.mem.intent else ""
        msgs = [self.sys, {"role": "user", "content": prev + self.perceive(eng)
                + "\n定本回合隐藏意图。务必锁定盟友: 进攻前先找可互保的邻国, 用 support 集火破防; 孤狼难赢, ally 字段尽量填具体国名。"}]
        out = await self.gw.achat(msgs, Intent, tag=f"{self.country}:intent")
        if out:
            self.mem.intent = out.model_dump()
        return out

    async def a_negotiate(self, eng: OperationEngine, inbox: str) -> Message | None:
        ctx = self.perceive(eng, inbox) + f"\n意图:{self.mem.intent}\n" + self.NEGO_TPL
        return await self.gw.achat([self.sys, {"role": "user", "content": ctx}], Message, tag=f"{self.country}:nego", retry=1, temp=0.4)

    def _stab_cue(self, eng: OperationEngine) -> str:
        it = self.mem.intent or {}                          # planned betrayal: strike target at move_turn
        yr = int("".join(filter(str.isdigit, eng.phase())) or 0)
        tgt = it.get("target")
        if tgt and tgt != self.country and it.get("move_turn", 9999) <= yr:
            return f"\n本回合是动手回合: 若已接壤 {tgt}, 优先进攻其中心(背刺), 趁信任反水收益最大。"
        return ""

    async def a_decide_orders(self, eng: OperationEngine) -> tuple[OrderSet | None, list[str]]:
        flat = self._legal_flat(eng)
        prompt = self._order_prompt(eng, flat) + self._stab_cue(eng)
        out = await self.gw.achat([self.sys, {"role": "user", "content": prompt}], OrderSet, tag=f"{self.country}:order", temp=0.2)
        raw = out.orders if out else []
        chosen = self._match(raw, flat)                       # fuzzy match; illegal -> hold
        if raw and not chosen:                                # all dropped = format mismatch, not a hold: flag it
            log.warning("%s 下令%d条全不匹配->全hold, 例:%s", self.country, len(raw), raw[:2])
        yr = int("".join(filter(str.isdigit, eng.phase())) or 0)
        for o in chosen:
            self.mem.record_action(yr, self.country, o)
        return out, chosen
