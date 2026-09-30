"""Memory (per power): facts coded, attitude rated by model.

- relations: trust/attitude rated by LLM.
- ledger: countdown/permanent, ticks down, expires at 0.
- actions: betrayal flag.
- diary + rolling summary: keep last 3 detailed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from .order_diagnostics import safe_order_candidate

RECENT = 3  # keep last N rounds
POWERS = {"AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"}


def diplomatic_candidate(text: str) -> str | None:
    """Retrieval hints, NEVER promise extraction or evidence of acceptance.

    Only first-person diplomatic language is tagged, and quoted/reported claims
    remain unverified. A later refusal is as important to retrieve as an offer.
    """
    if re.search(r"(?i)(?:^|[.!?。！？]\s*)(?:I|we)\s+(?:withdraw|cancel|decline|reject|cannot|can't|will not)\b|(?:我|我们)(?:撤回|取消|拒绝|无法|不能)", text):
        return "revision_or_refusal_candidate"
    if re.search(r"(?i)(?:^|[.!?。！？:]\s*)(?:I|we)\s+(?:will|promise|agree|commit|can|propose|offer|intend)\b|(?:我|我们)(?:承诺|保证|愿意|提议|会|同意)", text) and re.search(
            r"(?i)\bsupport\b|\bDMZ\b|demilitari|non.aggression|\bhelp\b|\bdefend\b|\bhold\b|\balliance\b|\bborder\b|支援|互不侵犯|非军事|结盟|不进|不入|边界", text):
        return "proposal_candidate"
    return None


def _strings(value, count: int, length: int) -> list[str]:
    """Bound new saved evidence fields without accepting arbitrary nested data."""
    return [v[:length] for v in value[:count] if isinstance(v, str)] if isinstance(value, list) else []


def _records(value, count: int, source: str) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [v for v in value[-count:] if isinstance(v, dict) and v.get("source") == source
            and isinstance(v.get("phase"), str) and re.fullmatch(r"[SFW]\d{4}[MRA]", v["phase"])]


@dataclass
class Commitment:
    to: str
    content: str
    round: int
    remaining: int | None  # None=permanent
    fulfilled: bool = False

    @property
    def expired(self) -> bool:
        return self.remaining is not None and self.remaining <= 0


@dataclass
class Action:
    round: int
    actor: str
    action: str
    betray: bool = False
    source: str = "public_result"


@dataclass
class Relation:
    trust: int = 0          # -100..100，模型评
    attitude: str = "中立"   # 模型给的一句话定性
    assessment_phase: str = ""
    evaluated_evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Memory:
    country: str
    relations: dict[str, Relation] = field(default_factory=dict)
    ledger: list[Commitment] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    diary: list[str] = field(default_factory=list)
    profile: dict = field(default_factory=dict)
    intent: dict | None = None   # 当前隐藏意图，只喂自己
    diplomacy_phase: str = ""
    diplomacy: str = ""
    evidence: list[dict] = field(default_factory=list)
    order_diagnostics: list[dict] = field(default_factory=list)
    own_adjudications: list[dict] = field(default_factory=list)
    evidence_retention: dict = field(default_factory=dict)
    _summary: str = ""       # 旧回合压缩后的滚动摘要

    def observe_diplomacy(self, phase: str, transcript: str) -> None:
        if phase != self.diplomacy_phase and self.diplomacy:
            self.add_diary(self.diplomacy_phase, self.diplomacy[-1200:])
        self.diplomacy_phase = phase
        self.diplomacy = str(transcript)[-48000:]
    def observe_messages(self, phase: str, records: list[dict]) -> None:
        """Trusted envelope, untrusted text. Never infer a sender from message text."""
        known = {e["id"] for e in self.evidence}
        powers = POWERS
        for record in records:
            sender, scope = record.get("sender"), record.get("scope")
            if sender not in powers or scope not in ("private", "broadcast"):
                continue
            targets = record.get("to", [])
            if not isinstance(targets, list) or any(not isinstance(p, str) or p not in powers for p in targets):
                continue
            if scope == "private" and (not targets or (self.country != sender and self.country not in targets)):
                continue
            recipients = sorted(set(targets))
            text = str(record.get("text", ""))
            identity = hashlib.sha256(json.dumps([phase, record.get("rnd"), sender, scope,
                                                   record.get("to", []), text], ensure_ascii=False).encode()).hexdigest()[:20]
            if identity in known: continue
            allegation = bool(re.search(r"(?i)betray|liar|lied|背叛|背刺|失信|叛徒|说谎|造谣", text))
            self.evidence.append({"id": identity, "phase": phase, "speaker": sender,
                                  "source": "direct_private" if scope == "private" else "public_statement",
                                  "scope": scope, "participants": sorted({sender, *recipients}) if scope == "private" else sorted(powers),
                                  "round": record.get("rnd") if isinstance(record.get("rnd"), int) else 0,
                                  "kind": "reported_claim" if allegation else "dialogue",
                                  "verified": False, "text": text[:2000]})
            candidate = diplomatic_candidate(text)
            if candidate:
                self.evidence[-1]["candidate"] = {"kind": candidate, "status": "unverified_unresolved",
                    "acceptance": "not_inferred", "expiry": "not_inferred", "source_id": identity}
            known.add(identity)
        # Session may replay the full current phase while old filler has already
        # been evicted. Reinserted rows must not masquerade as the newest reply.
        def chronology(e):
            match = re.fullmatch(r"([SFW])(\d{4})([MRA])", str(e.get("phase", "")))
            phase_key = (int(match[2]), "SFW".index(match[1]), "MRA".index(match[3])) if match else (0, 0, 0)
            return (*phase_key, e.get("round", 0))
        self.evidence.sort(key=chronology)
        # Preserve a separate small reservation for older direct offers/revisions.
        # These are candidates to reconsider, not accepted or still-current deals.
        protected = [e for e in self.evidence if e.get("candidate") and e.get("source") == "direct_private"][-32:]
        keep = {e["id"] for e in protected}
        for e in reversed(self.evidence):
            if len(keep) >= 120: break
            keep.add(e["id"])
        dropped = [e for e in self.evidence if e["id"] not in keep]
        candidate_drops = sum(bool(e.get("candidate")) for e in dropped)
        self.evidence_retention = {"dropped_records": len(dropped),
            "dropped_candidate_records": candidate_drops,
            "prior_candidate_eviction": bool(candidate_drops or self.evidence_retention.get("prior_candidate_eviction")),
            "reason": "bounded_memory_old_low_priority_first"}
        self.evidence = [e for e in self.evidence if e["id"] in keep]

    def observe_adjudication(self, adjudication: dict | None) -> None:
        """Keep recent own results, including bounces across retreat/build phases.

        Called with engine-produced public history, not dialogue or model claims.
        The full public result stays in the current context; this durable subset
        is private memory and never includes another power's pending orders.
        """
        if not adjudication or any(a["phase"] == adjudication["phase"] for a in self.own_adjudications):
            return
        orders = list(adjudication["orders"].get(self.country, []))
        units = {u.lstrip("*") for u in adjudication["units_before"].get(self.country, [])}
        units.update(" ".join(o.split()[:2]) for o in orders if len(o.split()) >= 2)
        self.own_adjudications.append({"phase": adjudication["phase"], "source": "public_result",
                                      "orders": orders,
                                      "results": {u: list(flags) for u, flags in adjudication["results"].items() if u in units},
                                      "units_after": list(adjudication["units_after"].get(self.country, []))})
        self.own_adjudications = self.own_adjudications[-6:]

    def record_order_diagnostics(self, phase: str, diagnostics: list[dict]) -> None:
        """Diagnostics describe a local plan, not adjudicated failures or repairs."""
        # A revised decision for the same phase supersedes its previous warnings.
        self.order_diagnostics = [d for d in self.order_diagnostics if d["phase"] != phase]
        self.order_diagnostics.extend({"phase": phase, "source": "own_order_diagnostic",
                                       "acknowledged": False, **d} for d in diagnostics)
        self.order_diagnostics = self.order_diagnostics[-40:]

    # --- facts (code) ---
    def add_commitment(self, to: str, content: str, rnd: int, turns: int | None) -> None:
        self.ledger.append(Commitment(to, content, rnd, turns))

    def record_action(self, rnd: int, actor: str, action: str, betray: bool = False, source: str = "public_result") -> None:
        self.actions.append(Action(rnd, actor, action, betray, source))
        self.actions = self.actions[-200:]

    def tick(self) -> None:
        """tick: decrement remaining, expire at 0."""
        for c in self.ledger:
            if c.remaining is not None and not c.fulfilled:
                c.remaining -= 1

    def active_commitments(self, power: str | None = None) -> list[Commitment]:
        cs = [c for c in self.ledger if not c.expired and not c.fulfilled]
        return [c for c in cs if c.to == power] if power else cs

    # --- attitude from model, code writes back ---
    def apply_attitude(self, scores: dict[str, dict], phase: str = "", evidence_ids: list[str] | None = None) -> None:
        for ctry, v in scores.items():
            r = self.relations.setdefault(ctry, Relation())
            if phase:
                r.assessment_phase = phase
                r.evaluated_evidence_ids = list(evidence_ids or [])[-12:]
            if "trust" in v:
                r.trust = max(-100, min(100, int(v["trust"])))
            if "attitude" in v:
                r.attitude = str(v["attitude"])

    def relation(self, power: str) -> Relation:
        return self.relations.setdefault(power, Relation())

    # --- diary + rolling summary ---
    def add_diary(self, rnd_label: str, text: str) -> None:
        self.diary.append(f"[{rnd_label}] {text}")
        if len(self.diary) > RECENT:                 # compress old into summary
            old = self.diary[:-RECENT]
            self._summary = (self._summary + " " + " ".join(old)).strip()[-600:]
            self.diary = self.diary[-RECENT:]

    def summary(self) -> str:
        rel = ", ".join(f"{k}:{v.trust}/{v.attitude}" for k, v in self.relations.items()) or "无"
        com = ", ".join(f"{c.to}:{c.content}({c.remaining if c.remaining is not None else '永久'})"
                        for c in self.active_commitments()) or "无"
        evidence = "; ".join(f"{a.actor}:{a.action}[{a.source}]" + ("(背叛)" if a.betray else "") for a in self.actions[-12:])
        return (f"行动记录(已提交不等于成功)[{evidence or '无'}] 关系[{rel}] 承诺[{com}] 摘要[{self._summary or '无'}] 近况[" +
                " | ".join(self.diary[-RECENT:]) + "]")

    def snapshot(self) -> dict:
        return {"country": self.country,
                "relations": {k: asdict(v) for k, v in self.relations.items()},
                "ledger": [asdict(c) for c in self.ledger],
                "actions": [asdict(a) for a in self.actions],
                "diary": list(self.diary), "summary": self._summary,
                "intent": self.intent, "profile": dict(self.profile), "diplomacy_phase": self.diplomacy_phase, "diplomacy": self.diplomacy, "evidence": list(self.evidence),
                "order_diagnostics": list(self.order_diagnostics), "own_adjudications": list(self.own_adjudications),
                "evidence_retention": dict(self.evidence_retention)}

    def restore(self, snap: dict) -> None:               # load saved memory (relations/ledger/actions/diary)
        self.relations = {k: Relation(**v) for k, v in snap.get("relations", {}).items()}
        self.ledger = [Commitment(**c) for c in snap.get("ledger", [])]
        self.actions = [Action(**a) for a in snap.get("actions", [])]
        self.diary = snap.get("diary", [])[-RECENT:]; self._summary = snap.get("summary", "")[-600:]
        self.intent = snap.get("intent")
        profile = snap.get("profile")
        if isinstance(profile, dict):
            # Only known numeric traits, never executable instructions from a save.
            self.profile.update({k: max(0., min(1., float(v))) for k, v in profile.items()
                                 if k in {"honor", "risk", "ambition", "grudge", "forgiveness", "betrayal_threshold", "survival_priority"}
                                 and isinstance(v, (int, float))})
        self.diplomacy_phase = str(snap.get("diplomacy_phase", ""))
        self.diplomacy = str(snap.get("diplomacy", ""))[-48000:]
        # Restore only legitimate envelope sources. Old direct evidence without
        # participant metadata came from this power's already-private save.
        self.evidence = []
        for e in snap.get("evidence", [])[-120:]:
            if not isinstance(e, dict) or not isinstance(e.get("id"), str) or e.get("speaker") not in POWERS:
                continue
            if e.get("source") not in {"direct_private", "public_statement"}:
                continue
            participants = e.get("participants")
            if e["source"] == "direct_private" and isinstance(participants, list) and self.country not in participants:
                continue
            clean = {k: e[k] for k in ("id", "phase", "speaker", "source", "scope", "round", "participants") if k in e}
            clean.update({"kind": "reported_claim" if e.get("kind") == "reported_claim" else "dialogue",
                          "verified": False, "text": str(e.get("text", ""))[:2000]})
            candidate = diplomatic_candidate(clean["text"])
            if candidate:
                clean["candidate"] = {"kind": candidate, "status": "unverified_unresolved",
                    "acceptance": "not_inferred", "expiry": "not_inferred", "source_id": clean["id"]}
            self.evidence.append(clean)
        retention = snap.get("evidence_retention", {})
        self.evidence_retention = {k: max(0, v) for k, v in retention.items()
                                   if k in {"dropped_records", "dropped_candidate_records", "prior_candidate_eviction"} and isinstance(v, int)} if isinstance(retention, dict) else {}
        self.order_diagnostics = []
        codes = {"own_destination_collision", "own_support_mismatch", "missing_order", "unrecognized_order", "duplicate_order", "structured_plan_mismatch", "own_nonvacating_destination", "no_planned_convoy_path", "convoy_requires_foreign_cooperation"}
        for d in _records(snap.get("order_diagnostics"), 40, "own_order_diagnostic"):
            if not isinstance(d.get("code"), str) or d["code"] not in codes:
                continue
            clean = {"phase": d["phase"], "source": "own_order_diagnostic", "code": d["code"],
                     "acknowledged": d.get("acknowledged") is True,
                     "orders": [] if d["code"] == "unrecognized_order" else _strings(d.get("orders"), 34, 80)}
            if isinstance(d.get("message"), str): clean["message"] = d["message"][:300]
            for key in ("destination", "location"):
                if isinstance(d.get(key), str) and re.fullmatch(r"[A-Z]{3}", d[key]): clean[key] = d[key]
            if isinstance(d.get("input_index"), int): clean["input_index"] = max(0, min(9999, d["input_index"]))
            if d["code"] == "unrecognized_order":
                if "candidate" in d:
                    clean.update(safe_order_candidate(d["candidate"]))
                elif type(d.get("candidate_index")) is int and 0 <= d["candidate_index"] <= 999999:
                    clean["candidate_index"] = d["candidate_index"]
                elif d.get("candidate_omitted") == "not_bounded_game_vocabulary":
                    clean["candidate_omitted"] = d["candidate_omitted"]
            self.order_diagnostics.append(clean)
        self.own_adjudications = []
        for a in _records(snap.get("own_adjudications"), 6, "public_result"):
            results = a.get("results") if isinstance(a.get("results"), dict) else {}
            self.own_adjudications.append({"phase": a["phase"], "source": "public_result",
                                          "orders": _strings(a.get("orders"), 34, 80),
                                          "results": {unit[:16]: _strings(flags, 8, 32) for unit, flags in list(results.items())[:34]
                                                      if isinstance(unit, str)},
                                          "units_after": _strings(a.get("units_after"), 34, 16)})
        self.actions = self.actions[-200:]
