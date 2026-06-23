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
        neutral = eng.neutral_centers()
        flat = {o for v in eng.legal_orders(self.country).values() for o in v}
        grab = sorted({o.split(" - ")[1].split("/")[0] for o in flat if " - " in o} & set(neutral))  # mine within reach now
        cue = f"\n可占无主中心:{neutral}; 你本回合能进的:{grab or '无, 先逼近'}; 秋季(F)入即占, 别全 hold" if neutral else ""
        return (f"阶段:{eng.phase()} 中心:{cen} 单位:{units}\n上回合各国命令(言行对照):{last}{cue}\n"
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

    def _resolve(self, raw: list, flat: list[str]) -> list[str]:
        """Map LLM output -> legal orders: number index OR fuzzy string; one per unit. Unset units = engine holds.
        Drops logged with reason. No hold-fill: leaving a unit unordered already means hold (engine default)."""
        canon = {self._norm(o): o for o in flat}
        by_unit: dict[str, str] = {}                         # orderable loc -> chosen legal order
        for o in raw:
            s = str(o).strip()
            hit = flat[int(s)] if s.isdigit() and int(s) < len(flat) else canon.get(self._norm(s))  # index or fuzzy
            if not hit:
                log.warning("%s 丢弃非法令: %r (无匹配)", self.country, o); continue
            loc = hit.split()[1]
            if loc in by_unit: log.warning("%s 丢弃重复令: %r (该单位已下)", self.country, o)
            else: by_unit[loc] = hit
        return list(by_unit.values())

    def _order_prompt(self, eng: OperationEngine, flat: list[str]) -> str:
        n = len(eng.legal_orders(self.country))
        grab = (self.mem.intent or {}).get("grab") or []
        push = "你是侵略者: 每个单位都必须移动占地, 严禁 hold。" if self.persona.name == "侵略者" else "多数单位该移动占地, 仅必要才原地。"
        return (self.perceive(eng) + f"\n意图:{self.mem.intent}\n你是 {self.country}，仅指挥自己 {n} 个单位。"
                f"本回合目标中心:{grab or '自选可占中心'}, 优先派兵进占。进攻多需配合: 主攻方向用 S 支援自己或盟友, 单兵硬冲常 bounce。"
                f"扩张优先: 抢无主中心涨得最快, 别全 hold; {push}"
                f"下列合法命令带编号，每单位恰好挑一条，把所选的{n}个编号(数字)放入 orders 数组：\n"
                + "\n".join(f"{i}: {o}" for i, o in enumerate(flat)) + '\n示例:{"orders":["0"],"reasoning":"一句话"}')

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
                + "\n定本回合隐藏意图。务必锁定盟友(ally填具体国名)与本回合要占的中心(grab填1-2个可占省名)。进攻前找可互保邻国 support 集火, 孤狼难赢。"}]
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
        chosen = self._resolve(out.orders if out else [], flat)  # index/fuzzy; unset units = engine holds
        yr = int("".join(filter(str.isdigit, eng.phase())) or 0)
        for o in chosen:
            self.mem.record_action(yr, self.country, o)
        return out, chosen
