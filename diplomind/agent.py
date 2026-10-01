"""AI agent — 5 async steps: perceive/attitude/intent/negotiate/order."""
from __future__ import annotations

import logging

from .providers.mock import CONTEXT_PREFIX
from .context_budget import compact_context, encoded, PROMPT_BUDGETS, GROUNDING_RULES
from .personalities import PERSONAS, behavioral_profile

from .order_diagnostics import safe_order_candidate
from .engine import OperationEngine
from .gateway import Gateway
from .memory import Memory
from .personalities import Persona, system_prompt
from .schemas import AttitudeUpdate, Intent, Message, OrderSet

log = logging.getLogger("diplomind")


class Agent:
    def __init__(self, country: str, persona: Persona, gw: Gateway, lang: str = "zh-Hans") -> None:
        self.country, self.persona, self.gw = country, persona, gw
        self.lang = lang
        self.game_mode = "classic"
        self.persona_key = next((k for k, p in PERSONAS.items() if p == persona), "opportunist")
        self.mem = Memory(country)
        self.mem.profile = behavioral_profile(country, self.persona_key)
        self.sys = {"role": "system", "content": system_prompt(country, persona, lang) + "\n" + GROUNDING_RULES}
        self.context_stats: dict[str, dict] = {}
        self.decision_health = {"status": "ready", "plan_mismatches": 0, "rejected_units": 0, "last_error": None}
        self._selected_evidence_ids: dict[str, list[str]] = {}

    def observe_diplomacy(self, phase: str, transcript: str) -> None:
        """Receive only this power's visibility-filtered, delivered diplomatic record.

        Session calls this after the final negotiation round is committed. An
        inbox for another phase is never silently reused in the current decision.
        """
        self.mem.observe_diplomacy(phase, transcript)

    def observe_messages(self, phase: str, records: list[dict]) -> None:
        self.mem.observe_messages(phase, records)

    def _context(self, eng: OperationEngine, inbox: str | None = None, *, stage: str = "order", flat: list[str] | None = None) -> dict:
        if inbox is not None:
            self.observe_diplomacy(eng.phase(), inbox)
        diplomacy = self.mem.diplomacy if self.mem.diplomacy_phase == eng.phase() else ""
        adjudications = eng.recent_adjudications()
        for result in adjudications:
            self.mem.observe_adjudication(result)
        raw = {"country": self.country, "phase": eng.phase(), "lang": self.lang,
               "persona": self.persona_key, "behavioral_profile": dict(self.mem.profile), "game_mode": self.game_mode,
               "units": eng.game.get_state()["units"],
               "last_adjudication": adjudications[-1] if adjudications else None,
               "recent_own_adjudications": list(self.mem.own_adjudications),
               "own_order_diagnostics": list(self.mem.order_diagnostics),
               "centers": {p: list(v.centers) for p, v in eng.game.powers.items()},
               "center_counts": eng.centers(), "supply_centers": sorted(eng.game.map.scs),
               "neutral_centers": eng.neutral_centers(), "legal": flat if flat is not None else self._legal_flat(eng),
               "intent": self.mem.intent or {}, "diplomacy": diplomacy,
               "commitments": [{"id": f"ledger:{i}", "to": c.to, "content": c.content, "recorded_round": c.round,
                                "remaining": c.remaining, "status": "recorded_unresolved", "source": "own_ledger"}
                               for i, c in enumerate(self.mem.ledger) if not c.expired and not c.fulfilled],
               "visible_evidence": list(self.mem.evidence),
               "action_evidence": [{"actor": a.actor, "action": a.action, "source": a.source, "betray": a.betray, "round": a.round}
                                   for a in self.mem.actions[-20:]],
               "relations": {p: {"trust": v.trust, "attitude": v.attitude, "source": "model_assessment",
                                  "assessment_phase": v.assessment_phase, "evaluated_evidence_ids": v.evaluated_evidence_ids[-4:]}
                             for p, v in self.mem.relations.items()}}
        context, stats = compact_context(raw, stage, self.mem.evidence_retention)
        self.context_stats[stage] = stats
        self._selected_evidence_ids[stage] = [e["id"] for e in context["visible_evidence"]]
        return context

    def perceive(self, eng: OperationEngine, inbox: str | None = None, *, stage: str = "order", flat: list[str] | None = None) -> str:
        context = self._context(eng, inbox, stage=stage, flat=flat)
        # JSON escaping contains untrusted dialogue inside a single data record.
        # Stable grounding/profile definitions live in the system role, never at
        # the tail of a long conversation. The short reminder is intentionally shared.
        return (CONTEXT_PREFIX + encoded(context) + "\n"
                "可以策略性说谎，但对话/旧计划不能当作事实。以当前 units/centers 为准。"
                "复核 acknowledged=false 的己方警告及最近 bounce；未证实提议不是已接受的约定。")

    def _record_prompt(self, stage: str, prompt: str) -> str:
        byte_count = len((self.sys["content"] + "\n" + prompt).encode("utf-8"))
        if byte_count > PROMPT_BUDGETS[stage]:
            raise ValueError("Prompt exceeds safe stage byte budget")
        self.context_stats[stage].update({"prompt_bytes": byte_count,
            "estimated_tokens_bytes_div_4": (byte_count + 3) // 4})
        return prompt

    PLAN = ('扩张盘算(按你的风格定力度): 1)定未来1-2年要拿哪2-3个中心——无主先占, 侵略性强就盯邻国弱者的中心; '
            '2)想入侵路线: 哪些单位往目标推进; 3)谁能合攻: 拉接壤盟友帮 support 或夹击; 4)自家部队互保: 主攻1个、邻兵 support 它破防。')

    NEGO_TPL = ('像真人谈判：一两句话讲清意图(结盟/交易/威胁/妥协)即可，别长篇大论，口吻自然。\n'
                '谈判要有具体筹码：边界安排、中心分配、互保或准确支援命令；根据自身利益选择结盟、暂时中立或施压。不要假设盟友已同意。\n'
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

    _safe_order_candidate = staticmethod(safe_order_candidate)

    def _resolve(self, raw: list, flat: list[str], diagnostics: list[dict] | None = None) -> list[str]:
        """Map LLM output -> legal orders: number index OR fuzzy string; one per unit. Unset units = engine holds.
        Drops logged with reason. No hold-fill: leaving a unit unordered already means hold (engine default)."""
        canon = {self._norm(o): o for o in flat}
        by_unit: dict[str, str] = {}                         # orderable loc -> chosen legal order
        for index, o in enumerate(raw):
            s = str(o).strip()
            index_value = int(s) if s.isascii() and s.isdigit() and len(s) <= 6 else None
            hit = flat[index_value] if index_value is not None and index_value < len(flat) else canon.get(self._norm(s))  # index or fuzzy
            if not hit:
                if diagnostics is not None:
                    diagnostics.append({"code": "unrecognized_order", "input_index": index, "orders": [],
                                        "message": "No legal match; this order was dropped, not executed.",
                                        **self._safe_order_candidate(o)})
                log.warning("%s 丢弃非法令 (无匹配)", self.country); continue
            loc = hit.split()[1].split("/")[0] if len(hit.split()) > 1 else "WAIVE"
            if loc in by_unit:
                if diagnostics is not None:
                    diagnostics.append({"code": "duplicate_order", "orders": [by_unit[loc], hit],
                                        "message": "Only the first legal order for this unit was kept."})
                log.warning("%s 丢弃重复令 (该单位已下)", self.country)
            else: by_unit[loc] = hit
        return list(by_unit.values())

    def _check_unit_plan(self, out: OrderSet | None, chosen: list[str], flat: list[str], diagnostics: list[dict]) -> list[str]:
        """Reject structural contradictions, never interpret free-form rationale.

        Missing plan is the backward-compatible legacy format. A present plan
        must label each chosen unit correctly and agree with its final action.
        No corrected move is substituted and no model repair call is made.
        """
        plan = getattr(out, "unit_plan", []) if out else []
        self.decision_health.update(status="ready", last_error=None)
        if not plan: return chosen
        canon = {self._norm(o): o for o in flat}
        unit = lambda order: " ".join(order.split()[:2]) if order != "WAIVE" else "WAIVE"
        location = lambda label: label.split()[1].split("/")[0] if len(label.split()) > 1 else "WAIVE"
        legal_units = {unit(o) for o in flat}
        final = {unit(o): o for o in chosen}
        planned: dict[str, str] = {}
        bad: set[str] = set()
        invalid_rows = []
        evidence: dict[str, set[str]] = {}
        for row_index, row in enumerate(plan):
            label = " ".join(row.unit.upper().split())
            raw = row.order.strip()
            index_value = int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 6 else None
            hit = flat[index_value] if index_value is not None and index_value < len(flat) else canon.get(self._norm(raw))
            actual = unit(hit) if hit else None
            if hit and actual: evidence.setdefault(actual, set()).add(hit)
            if label not in legal_units or actual != label:
                if label in legal_units: bad.add(label)
                if actual in legal_units: bad.add(actual)
                if label not in legal_units and actual not in legal_units: invalid_rows.append(row_index)
                continue
            if label in planned and planned[label] != hit: bad.add(label)
            planned[label] = hit
        for label in set(final) | set(planned):
            if final.get(label) != planned.get(label): bad.add(label)
        for label in sorted(bad):
            orders = set(evidence.get(label, set()))
            if label in final: orders.add(final[label])
            diagnostics.append({"code": "structured_plan_mismatch", "location": location(label),
                "orders": sorted(orders)[:4], "acknowledged": False,
                "message": "Structured unit plan and final orders disagree or label the wrong unit; affected unit rejected to engine default."})
        if invalid_rows:
            diagnostics.append({"code": "structured_plan_mismatch", "orders": [], "input_index": invalid_rows[0],
                "acknowledged": False, "message": "Structured plan contains an unknown unit and action; invalid row rejected without inferring a replacement."})
        if bad or invalid_rows:
            self.decision_health.update(status="degraded", last_error="structured_plan_mismatch")
            self.decision_health["plan_mismatches"] += 1
            self.decision_health["rejected_units"] += len(bad)
            health = getattr(self.gw, "health", None)
            if isinstance(health, dict):
                health.update(status="degraded", last_error="structured_plan_mismatch")
                health["fallbacks"] = health.get("fallbacks", 0) + 1
                health["decision_rejections"] = health.get("decision_rejections", 0) + len(bad)
        return [o for o in chosen if unit(o) not in bad]

    def _diagnose_orders(self, eng: OperationEngine, chosen: list[str], intentional: list[str]) -> list[dict]:
        """Explain local coordination risks without changing any legal order.

        No search, model retry, or access to another power's pending orders. A
        same-target warning is not a prediction: supports can alter the outcome.
        """
        province = lambda loc: loc.upper().split("/")[0]
        by_loc = {province(o.split()[1]): o.split() for o in chosen if len(o.split()) >= 3}
        destinations: dict[str, list[str]] = {}
        diagnostics = []
        for order in chosen:
            parts = order.split()
            if len(parts) >= 4 and parts[2] in ("-", "R"):
                destinations.setdefault(province(parts[3]), []).append(order)
        acknowledged = {province(loc) for loc in intentional}
        for destination, orders in destinations.items():
            if len(orders) > 1:
                diagnostics.append({"code": "own_destination_collision", "destination": destination,
                                    "orders": orders, "acknowledged": destination in acknowledged,
                                    "message": "Multiple own units target one province; possible friendly standoff. "
                                               "Check coordination/supports or explicitly retain an intentional self-standoff."})
        if eng.phase_type() == "M":
            own = {province(u.split()[1]): u.split()[0] for u in eng.game.powers[self.country].units}
            own_canonical = {province(u.split()[1]): u.lstrip("*").split()[:2] for u in eng.game.powers[self.country].units}
            for order in chosen:
                parts = order.split()
                if len(parts) >= 4 and parts[2] == "-" and province(parts[3]) in own:
                    occupant = by_loc.get(province(parts[3]), [*own_canonical[province(parts[3])], "H"])
                    if occupant[2] != "-":
                        diagnostics.append({"code": "own_nonvacating_destination", "destination": province(parts[3]),
                            "orders": [order, " ".join(occupant)], "acknowledged": province(parts[3]) in acknowledged,
                            "message": "Move targets an own unit not ordered to vacate; check coordination or explain the intentional block."})
                if len(parts) < 5 or parts[2] != "S" or own.get(province(parts[4])) != parts[3]:
                    continue  # Other powers' orders are unknown, not a diagnosed mismatch.
                target = by_loc.get(province(parts[4]), [parts[3], parts[4], "H"])
                support_move = len(parts) >= 7 and parts[5] == "-"
                matches = (target[2] == "-" and province(target[3]) == province(parts[6])) if support_move else target[2] != "-"
                if not matches:
                    diagnostics.append({"code": "own_support_mismatch", "orders": [order, " ".join(target)],
                                        "message": "Support does not match the supported own unit's chosen order (or implicit hold)."})
            diagnostics.extend(self._convoy_diagnostics(eng, chosen))
        if eng.phase_type() in ("M", "R"):
            for loc in sorted({province(loc) for loc in eng.legal_orders(self.country)} - set(by_loc)):
                diagnostics.append({"code": "missing_order", "location": loc, "orders": [],
                                    "message": "No selected order: engine defaults to hold." if eng.phase_type() == "M"
                                               else "No selected retreat: engine defaults to disband."})
        return diagnostics

    def _convoy_diagnostics(self, eng: OperationEngine, chosen: list[str]) -> list[dict]:
        """Check possible convoy paths from public units and our own sealed plan.

        Foreign fleet orders remain unknown; their presence is only a possible
        route, never evidence of an accepted convoy promise or a prediction.
        """
        board = eng.game.map
        orders = {o.split()[1].split("/")[0]: o.split() for o in chosen if len(o.split()) >= 3}
        sea_fleets = {u.split()[1]: power for power, state in eng.game.powers.items()
                      for u in state.units if u.startswith("F ") and board.area_type(u.split()[1]) == "WATER"}
        result = []
        for order in chosen:
            parts = order.split()
            if len(parts) < 4 or parts[0] != "A" or parts[2] != "-": continue
            origin, destination = parts[1], parts[3]
            if "VIA" not in parts and board.abuts("A", origin, "-", destination): continue
            own = {sea for sea, power in sea_fleets.items() if power == self.country
                   and orders.get(sea) == ["F", sea, "C", "A", origin, "-", destination]}
            foreign = {sea for sea, power in sea_fleets.items() if power != self.country}
            def coastal_contact(sea, province):
                return any(board.abuts("F", sea, "-", coast) for coast in board.find_coasts(province))
            def route(seas):
                frontier = [sea for sea in seas if coastal_contact(sea, origin)]
                seen = set(frontier)
                while frontier:
                    sea = frontier.pop()
                    if coastal_contact(sea, destination): return True
                    adjacent = {other for other in seas - seen if board.abuts("F", sea, "-", other)}
                    seen.update(adjacent); frontier.extend(adjacent)
                return False
            if route(own): continue
            possible = route(own | foreign)
            result.append({"code": "convoy_requires_foreign_cooperation" if possible else "no_planned_convoy_path",
                "orders": [order], "acknowledged": False,
                "message": "Convoy route requires unknown foreign fleet orders; verify an explicit agreement, which still may be broken."
                    if possible else "No sea-fleet convoy path remains under our chosen fleet orders and the public board; coordinate fleets or reconsider the army order."})
        return result

    def _order_prompt(self, eng: OperationEngine, flat: list[str]) -> str:
        n = len(eng.legal_orders(self.country))
        grab = (self.mem.intent or {}).get("grab") or []
        example_unit = " ".join(flat[0].split()[:2]) if flat else ""
        example = {"reasoning": "一句话最终决定", "intentional_self_standoffs": [],
                   "unit_plan": [{"unit": example_unit, "order": "0"}] if flat else [],
                   "orders": ["0"] if flat else []}
        return (self.perceive(eng, stage="order", flat=flat) + f"\n你是 {self.country}，仅指挥自己的单位。"
                f"本回合目标中心:{grab or '根据局势选择'}, 以长期独胜和生存为目标。"
                "性格决定风险偏好，不是硬性进攻配额。必要时 hold、防御支援、退让都合理。"
                "比较至少两个可行方案：争取中心、守住受威胁本土、兑现关键支援；"
                "避免己方互撞，检查支援与目标命令一致，不要虚构盟友已承诺的行动。"
                "逐条复核 own_order_diagnostics 中尚未承认的碰撞警告及最近实际 bounce 后的位置。"
                "若确实有意自撞，在 intentional_self_standoffs 列出目标省缩写并在 reasoning 解释；默认空列表。"
                "对最后一轮收件也要逐条考虑：优先兑现有利且可信的约定，背叛前权衡收益、报复与安全。"
                f"legal 是本阶段完整合法表；默认字符串数组下标从0开始且稳定。每单位至多一条(通常共{n}条)，优先逐字返回原命令，也可返回编号。"
                "若 legal_encoding=prefix_groups，每组[start_id,prefix,suffixes]表示 prefix+' '+suffix；编号=start_id+suffix下标，所有合法命令均保留。"
                "先完成简短的一句话决定，再给每个下令单位 unit_plan，最后才输出 orders。"
                "最终复核 unit_plan 的单位、命令与 orders 一致；发现改变主意，先改计划，再填最终 orders，不要在命令后补写相反决定。"
                + "\n格式示例(仅演示合法编号，不代表应选此行动):" + encoded(example))

    def snapshot(self) -> dict:
        return {"country": self.country, "persona": self.persona.name, "mem": self.mem.snapshot(),
                "decision_health": dict(self.decision_health)}

    # all steps async (AI concurrent; humans do these mentally)
    async def a_update(self, eng: OperationEngine, inbox: str | None = None) -> AttitudeUpdate | None:
        prompt = (self.perceive(eng, inbox, stage="attitude") + '\n据近况评各国信任分与定性。'
                  '只根据你可见的证据更新信任；把第三方指控标作未核实，对照公开行动再下结论。'
                  'scores 字典 {"国名":-100到100}；attitudes 字典 {"国名":"盟友/敌对/中立等一句话"}。')
        prompt = self._record_prompt("attitude", prompt)
        out = await self.gw.achat([self.sys, {"role": "user", "content": prompt}], AttitudeUpdate, tag=f"{self.country}:attitude")
        if out:
            merged = {c: {"trust": t} for c, t in out.scores.items() if c in eng.game.powers and c != self.country}
            for c, a in out.attitudes.items():
                if c in eng.game.powers and c != self.country:
                    merged.setdefault(c, {})["attitude"] = a[:300]
            self.mem.apply_attitude(merged, eng.phase(), self._selected_evidence_ids.get("attitude", []))
        return out

    async def a_intent(self, eng: OperationEngine) -> Intent | None:
        prompt = (self.perceive(eng, stage="intent") + "\n" + self.PLAN
                  + " 延续微调 context.intent；定意图: ally填优先合作对象(可空), target填正考虑施压的对手(可空), grab填本回合争取的1-2个省名(必要时可空防守)。")
        msgs = [self.sys, {"role": "user", "content": self._record_prompt("intent", prompt)}]
        out = await self.gw.achat(msgs, Intent, tag=f"{self.country}:intent")
        if out:
            self.mem.intent = out.model_dump()
        return out

    async def a_negotiate(self, eng: OperationEngine, inbox: str) -> Message | None:
        ctx = self._record_prompt("nego", self.perceive(eng, inbox, stage="nego") + "\n" + self.NEGO_TPL)
        out = await self.gw.achat([self.sys, {"role": "user", "content": ctx}], Message, tag=f"{self.country}:nego", retry=1, temp=0.4)
        if out:
            # Defense in depth for custom adapters that bypass schema validation.
            # Reject the whole ambiguous audience; do not silently drop recipients
            # or widen an invalid private message into a public broadcast.
            if out.type not in {"private", "broadcast"}:
                return None
            recipients = [str(p).strip().upper() for p in (out.recipient or [])]
            if any(p not in eng.game.powers or p == self.country for p in recipients):
                return None
            if ((out.type == "private" and not recipients)
                    or (out.type == "broadcast" and recipients)):
                return None
            out.recipient = sorted(set(recipients))
            out.content = out.content[:2000]
        return out

    def _stab_cue(self, eng: OperationEngine) -> str:
        it = self.mem.intent or {}                          # planned betrayal: strike target at move_turn
        yr = int("".join(filter(str.isdigit, eng.phase())) or 0)
        tgt = it.get("target")
        if tgt and tgt != self.country and it.get("move_turn", 9999) <= yr:
            return f"\n先前曾考虑对 {tgt} 背刺；这只是候选方案，重新核对现有盟约、收益、报复风险和本土安全，条件不利就取消。"
        return ""

    async def a_decide_orders(self, eng: OperationEngine, inbox: str | None = None, *,
                              preflight_review: bool = False) -> tuple[OrderSet | None, list[str]]:
        """Optionally review one mechanically inconsistent plan, never enforce diplomacy.

        The initial scoped context is reused; provisional speech and arbitrary
        rejected output are never fed back. Only the final decision is recorded.
        A failed review preserves the initial decision; cancellation propagates.
        """
        if inbox is not None:
            self.observe_diplomacy(eng.phase(), inbox)
        self.context_stats.pop("order_review", None)
        flat = self._legal_flat(eng)
        prompt = self._order_prompt(eng, flat)
        prompt += self._stab_cue(eng)
        prompt = self._record_prompt("order", prompt)
        out = await self.gw.achat([self.sys, {"role": "user", "content": prompt}], OrderSet, tag=f"{self.country}:order", temp=0.2)
        review_codes = {"unrecognized_order", "duplicate_order", "structured_plan_mismatch",
                        "own_destination_collision", "no_planned_convoy_path",
                        "own_support_mismatch", "own_nonvacating_destination"}

        def diagnose(candidate):
            warnings: list[dict] = []
            orders = self._resolve(candidate.orders if candidate else [], flat, warnings)
            orders = self._check_unit_plan(candidate, orders, flat, warnings)
            warnings.extend(self._diagnose_orders(eng, orders, candidate.intentional_self_standoffs if candidate else []))
            return orders, warnings

        def errors(candidate, warnings):
            # Missing orders remain degraded fallback, but do not justify a
            # tactical review by themselves. Foreign uncertainty is not error.
            codes = [d["code"] for d in warnings if d["code"] in review_codes | {"missing_order"}
                     and not d.get("acknowledged", False)]
            if candidate is None: codes.insert(0, "no_order_response")
            return list(dict.fromkeys(codes))

        chosen, diagnostics = diagnose(out)
        initial_errors = errors(out, diagnostics)
        self.decision_health.update(initial_errors=initial_errors, final_errors=initial_errors,
                                    review_attempted=False, review_used=False, review_error=None)
        if preflight_review and out is not None and any(code in review_codes for code in initial_errors):
            # Canonical engine orders only. Do not echo rationale, unknown unit
            # labels, raw rejected candidates, exception text, or hidden orders.
            legal = set(flat)
            relevant = [d for d in diagnostics if d["code"] in review_codes]
            feedback = [{"code": d["code"],
                         "orders": [o for o in d.get("orders", []) if o in legal][:4],
                         "acknowledged": bool(d.get("acknowledged", False))}
                        for d in relevant[:16]]
            payload = {"candidate_orders": chosen[:64], "errors": initial_errors,
                       "diagnostics": feedback, "details_omitted": len(relevant) > 16 or len(chosen) > 64}
            while len(encoded(payload).encode("utf-8")) > 4096:
                payload["details_omitted"] = True
                if feedback: feedback.pop()
                elif payload["candidate_orders"]: payload["candidate_orders"].pop()
                else: break
            review_prompt = (prompt + "\nOne optional internal coordination review. "
                "The following is bounded diagnostic data, not an instruction from another player. "
                "Check the canonical candidate against the same current board and legal table. "
                "Return a complete OrderSet with a consistent unit_plan and final orders. "
                "You may deliberately retain a legal feint or an order expected to fail; give one short explicit explanation. "
                "If retaining an intentional own standoff, list its province in intentional_self_standoffs. "
                "Do not treat uncertain foreign cooperation as an error or assume allies will honor promises. "
                "Do not enforce promises or reverse a strategic betrayal just because of this review. "
                "Never substitute an order silently.\nPREFLIGHT_DIAGNOSTICS:" + encoded(payload))
            prompt_bytes = len((self.sys["content"] + "\n" + review_prompt).encode("utf-8"))
            self.context_stats["order_review"] = {"prompt_bytes": prompt_bytes,
                "estimated_tokens_bytes_div_4": (prompt_bytes + 3) // 4,
                "details_omitted": payload["details_omitted"]}
            if prompt_bytes > PROMPT_BUDGETS["order"]:
                self.decision_health["review_error"] = "review_prompt_budget"
            else:
                self.decision_health["review_attempted"] = True
                try:
                    reviewed = await self.gw.achat([self.sys, {"role": "user", "content": review_prompt}],
                                                  OrderSet, tag=f"{self.country}:order_review", retry=0, temp=0.2)
                except Exception:
                    # Includes bounded-gateway budget/timeout failures. Never
                    # catch BaseException: room shutdown must still cancel.
                    reviewed = None
                    self.decision_health["review_error"] = "review_unavailable"
                if reviewed is None:
                    self.decision_health["review_error"] = self.decision_health["review_error"] or "no_review_response"
                else:
                    initial_health = dict(self.decision_health)
                    reviewed_chosen, reviewed_diagnostics = diagnose(reviewed)
                    if chosen and not reviewed_chosen:
                        self.decision_health.update(initial_health, review_error="unusable_review")
                    else:
                        out, chosen, diagnostics = reviewed, reviewed_chosen, reviewed_diagnostics
                        self.decision_health["review_used"] = True
        final_errors = errors(out, diagnostics)
        self.decision_health.update(final_errors=final_errors,
            status="degraded" if final_errors else "ready", last_error=final_errors[0] if final_errors else None)
        self.mem.record_order_diagnostics(eng.phase(), diagnostics)
        if not chosen: log.warning("%s 本回合零命令，采用引擎默认 hold", self.country)
        yr = int("".join(filter(str.isdigit, eng.phase())) or 0)
        for o in chosen:
            self.mem.record_action(yr, self.country, o, source="submitted_order")
        return out, chosen
