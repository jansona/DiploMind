"""AI agent — 5 async steps: perceive/attitude/intent/negotiate/order."""
from __future__ import annotations

from .engine import OperationEngine
from .gateway import Gateway
from .memory import Memory
from .personalities import Persona, system_prompt
from .schemas import AttitudeUpdate, Intent, Message, OrderSet


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

    NEGO_TPL = ('发一条外交消息。只输出此 JSON，不要解释、不要 markdown：\n'
                '{"type":"broadcast","recipient":[],"content":"…"}\n'
                'broadcast=群发(recipient 留空)；private=私聊(recipient 填国名如 ["GERMANY"])；'
                '无话可说则 content 填""(本轮静默)。')

    def _legal_flat(self, eng: OperationEngine) -> list[str]:
        legal = eng.legal_orders(self.country)
        return sorted({o for v in legal.values() for o in v})

    def _order_prompt(self, eng: OperationEngine, flat: list[str]) -> str:
        n = len(eng.legal_orders(self.country))
        return (self.perceive(eng) + f"\n意图:{self.mem.intent}\n你是 {self.country}，仅指挥自己 {n} 个单位。"
                f"从下列合法命令逐字复制，每单位恰好一条，共 {n} 条放入 orders 数组(只放命令字符串)：\n"
                + "\n".join(flat) + f'\n示例:{{"orders":["{flat[0]}"],"reasoning":"一句话"}}')

    def snapshot(self) -> dict:
        return {"country": self.country, "persona": self.persona.name, "mem": self.mem.snapshot()}

    # all steps async (AI concurrent; humans do these mentally)
    async def a_update(self, eng: OperationEngine, inbox: str = "") -> AttitudeUpdate | None:
        prompt = self.perceive(eng, inbox) + '\n据近况评各国信任分。scores 为字典: {"国名": -100到100}。'
        out = await self.gw.achat([self.sys, {"role": "user", "content": prompt}], AttitudeUpdate, tag=f"{self.country}:attitude")
        if out:
            self.mem.apply_attitude({c: {"trust": t} for c, t in out.scores.items()})
        return out

    async def a_intent(self, eng: OperationEngine) -> Intent | None:
        prev = f"上回合意图(延续微调):{self.mem.intent}\n" if self.mem.intent else ""
        msgs = [self.sys, {"role": "user", "content": prev + self.perceive(eng) + "\n定本回合隐藏意图。"}]
        out = await self.gw.achat(msgs, Intent, tag=f"{self.country}:intent")
        if out:
            self.mem.intent = out.model_dump()
        return out

    async def a_negotiate(self, eng: OperationEngine, inbox: str) -> Message | None:
        ctx = self.perceive(eng, inbox) + f"\n意图:{self.mem.intent}\n" + self.NEGO_TPL
        return await self.gw.achat([self.sys, {"role": "user", "content": ctx}], Message, tag=f"{self.country}:nego", retry=1, temp=0.4)

    async def a_decide_orders(self, eng: OperationEngine) -> tuple[OrderSet | None, list[str]]:
        flat = self._legal_flat(eng)
        prompt = self._order_prompt(eng, flat)
        out = await self.gw.achat([self.sys, {"role": "user", "content": prompt}], OrderSet, tag=f"{self.country}:order", temp=0.2)
        chosen = [o for o in (out.orders if out else []) if o in set(flat)]   # drop illegal = hold
        yr = int("".join(filter(str.isdigit, eng.phase())) or 0)
        for o in chosen:
            self.mem.record_action(yr, self.country, o)
        return out, chosen
