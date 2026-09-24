"""Analytics engine — the single place where the layers meet.

Responsibilities, in order:

1. Build a world from the simulator (which also returns ground truth).
2. Per outlet: assess feed reliability, project every balance separately,
   detect anomalies, classify each finding into one of the three contexts,
   and emit alerts routed to a named owner.
3. Aggregate: area hotspots, cross-outlet network, nearby-support discovery.
4. Score itself against the simulator's ground truth so precision and recall
   are *measured* rather than asserted.

The engine is deliberately synchronous and pure with respect to its inputs: the
whole snapshot is rebuilt from scratch, which makes the what-if simulation a
one-line change and guarantees the dashboard can never show a mixture of old and
new numbers.
"""
from __future__ import annotations

import time

from app import hotspot, network
from app.anomaly import account_concentration
from app.anomaly import scan as scan_anomalies
from app.config import SETTINGS
from app.context import calendar_context, classify
from app.coordination import AuditLog, open_case, route
from app.domain import (Alert, AlertKind, CaseStatus, Classification, FeedStatus,
                        Severity)
from app.llm import rephrase
from app.liquidity import project_outlet, worst_projection
from app.narrative import (Narrative, assemble_anomaly, assemble_coordination,
                           assemble_data_quality, assemble_liquidity, format_bdt,
                           format_hours)
from app.quality import should_suppress
from app.quality import outlet_reliability
from app.simulator import PROVIDERS, Simulator


def _provider_name(pid: str, lang: str = "en") -> str:
    for p in PROVIDERS:
        if getattr(p, "id", None) == pid:
            return getattr(p, "name_bn" if lang == "bn" else "name", pid)
    return pid


def severity_for(hours: float | None, exhausted: bool) -> Severity | None:
    """Severity from time-to-exhaustion. None means 'not worth an alert'."""
    if exhausted:
        return Severity.CRITICAL
    if hours is None:
        return None
    horizon = SETTINGS["alert_horizon_hours"]
    if hours <= 1.0:
        return Severity.CRITICAL
    if hours <= 3.0:
        return Severity.HIGH
    if hours <= horizon:
        return Severity.MEDIUM
    return None


def liquid_severity(proj) -> Severity | None:
    """Severity for a projection, *gated on the projection's own reliability*.

    Without this gate a steep slope fitted through three noisy points becomes a
    CRITICAL alert. The distinction matters: a projection is a number the
    dashboard may show, whereas an alert is an assertion that somebody should
    act — and it should not be possible to assert from noise.

    A low-confidence projection is therefore still displayed on the outlet card,
    marked as such, but it does not raise an alert.
    """
    if proj is None:
        return None
    if not proj.exhausted:
        if proj.points_used < SETTINGS["min_alert_points"]:
            return None
        if proj.confidence < SETTINGS["min_alert_confidence"]:
            return None
    return severity_for(proj.hours_to_empty, proj.exhausted)


def flatten(n: Narrative) -> str:
    """Collapse the four-part narrative into one readable block."""
    parts = [n.situation]
    if n.evidence:
        parts.append("\n".join(f"• {e}" for e in n.evidence))
    if n.uncertainty:
        parts.append(n.uncertainty)
    if n.next_steps:
        parts.append("\n".join(f"→ {s}" for s in n.next_steps))
    if n.rejected_text:
        parts.append(n.rejected_text)
    return "\n\n".join(p for p in parts if p)


def _parts(n: Narrative) -> dict:
    """The four narrative parts plus the rejections, kept structured.

    Rendering the UI from these rather than from ``flatten``'s output means the
    language toggle swaps the whole alert — evidence and next steps included —
    instead of swapping the heading and leaving English underneath.
    """
    return {
        "situation": n.situation,
        "evidence": list(n.evidence),
        "uncertainty": n.uncertainty,
        "next_steps": list(n.next_steps),
        "rejected_text": n.rejected_text,
        "source": n.source,
    }


class Engine:
    def __init__(self, seed: int = 42, outlets: int = 12,
                 scenario: str = "baseline", db_path=None,
                 use_llm: bool = True) -> None:
        self.seed = seed
        self.outlets = outlets
        self.scenario = scenario
        self.use_llm = use_llm
        self.audit = AuditLog(db_path or SETTINGS["db_path"])
        self.demand_multiplier = 1.0
        # Case status survives a rebuild: the world is regenerated constantly,
        # but a human's decision about an alert must not be. open_case() is what
        # honours this, by reading self._cases when it re-creates an alert.
        self._cases: dict[str, tuple[CaseStatus, str, str]] = {}
        self.alerts: dict[str, Alert] = {}
        self.snapshot: dict = {}
        self.rebuild()

    # -- world ---------------------------------------------------------------
    def rebuild(self, scenario: str | None = None,
                outlets: int | None = None, seed: int | None = None,
                demand_multiplier: float | None = None) -> dict:
        if scenario is not None:
            self.scenario = scenario
        if outlets is not None:
            self.outlets = outlets
        if seed is not None:
            self.seed = seed
        if demand_multiplier is not None:
            self.demand_multiplier = demand_multiplier

        sim = Simulator(seed=self.seed, outlets=self.outlets).scenario(self.scenario)
        world = sim.world()
        episodes = sim.episodes()
        now = sim.now

        self.alerts = {}
        rows: list[dict] = []
        for outlet_id, state in world.items():
            rows.append(self._analyse(state, now))

        self._aggregate(rows, world, now, episodes)

        self.snapshot = {
            "generated_at": now,
            "scenario": self.scenario,
            "demand_multiplier": self.demand_multiplier,
            "seed": self.seed,
            "summary": self._summary(rows),
            "outlets": rows,
            "alerts": [self._alert_payload(a) for a in self._sorted_alerts()],
            "hotspots": self._hotspot_payload,
            "focus": self._focus,
            "network": self._network_payload,
            "support": self._support,
            "metrics": self._metrics,
            "episodes": [{"outlet_id": e.outlet_id, "provider_id": e.provider_id,
                          "label": e.label, "note": e.note} for e in episodes],
        }
        return self.snapshot

    # -- per-outlet analysis -------------------------------------------------
    def _analyse(self, state, now: float) -> dict:
        outlet = state.outlet
        reliability, notes = outlet_reliability(state, now)
        projections = project_outlet(state, now, self.demand_multiplier)
        by_label = {p.label: p for p in projections}
        cash_proj = by_label.get("cash")
        worst = worst_projection(projections)
        ctx = calendar_context(now)

        positions = []
        for pid, pos in state.positions.items():
            proj = by_label.get(pid)
            suppressed = should_suppress(pos.feed_status)
            sev = None if suppressed else liquid_severity(proj)

            if suppressed:
                self._emit_liquidity_alert(state, pid, pos, proj, now,
                                           suppressed=True)
            elif sev is not None:
                self._emit_liquidity_alert(state, pid, pos, proj, now,
                                           suppressed=False)

            positions.append({
                "provider_id": pid,
                "name": _provider_name(pid, "en"),
                "name_bn": _provider_name(pid, "bn"),
                "balance": round(pos.balance, 2),
                "opening_balance": round(pos.opening_balance, 2),
                "feed_status": pos.feed_status.value,
                "feed_age_minutes": (round((now - pos.last_feed_at) / 60.0)
                                     if pos.last_feed_at else None),
                "hours_to_empty": (round(proj.hours_to_empty, 2)
                                   if proj and proj.hours_to_empty is not None
                                   else None),
                "low_hours": (round(proj.low_hours, 2)
                              if proj and proj.low_hours is not None else None),
                "high_hours": (round(proj.high_hours, 2)
                               if proj and proj.high_hours is not None else None),
                "rate_per_hour": round(proj.rate_per_hour, 2) if proj else 0.0,
                "confidence": round(proj.confidence, 2) if proj else 0.0,
                "exhausted": bool(proj.exhausted) if proj else False,
                "suppressed": suppressed,
                "low_confidence": bool(
                    proj and not suppressed and not proj.exhausted
                    and (proj.confidence < SETTINGS["min_alert_confidence"]
                         or proj.points_used < SETTINGS["min_alert_points"])),
                "severity": sev.value if sev else None,
            })

        # Shared physical cash — covered by every provider track, so provider_id
        # stays None and any track may coordinate on it.
        cash_sev = liquid_severity(cash_proj)
        if cash_sev is not None:
            self._emit_cash_alert(state, cash_proj, now)

        for sig in scan_anomalies(state, now):
            self._emit_signal_alert(state, sig, ctx, now)

        return {
            "id": outlet.id,
            "name": outlet.name,
            "area": outlet.area,
            "thana": outlet.thana,
            "district": outlet.district,
            "lat": outlet.lat,
            "lon": outlet.lon,
            "cash": round(state.cash, 2),
            "cash_opening": round(state.cash_opening, 2),
            "total_value": round(state.total_value(), 2),
            "cash_hours": (round(cash_proj.hours_to_empty, 2)
                           if cash_proj and cash_proj.hours_to_empty is not None
                           else None),
            "cash_confidence": round(cash_proj.confidence, 2) if cash_proj else 0.0,
            "cash_exhausted": bool(cash_proj.exhausted) if cash_proj else False,
            "worst_hours": (round(worst.hours_to_empty, 2)
                            if worst and worst.hours_to_empty is not None else None),
            "worst_label": worst.label if worst else None,
            "reliability": round(reliability, 2),
            "reliability_notes": notes,
            "calendar_context": ctx,
            "txn_count": len(state.transactions),
            "positions": positions,
            "alert_ids": [a.id for a in self.alerts.values()
                          if a.outlet_id == outlet.id],
        }

    # -- alert construction --------------------------------------------------
    def _new_alert(self, outlet_id: str, provider_id: str | None, kind: AlertKind,
                   now: float) -> Alert:
        aid = f"A-{outlet_id}-{kind.value}-{provider_id or 'shared'}"
        # Ownership and status are settled by open_case, which is the one place
        # that reads self._cases. Creating the alert bare keeps a single source
        # of truth for "what did a human already decide about this case".
        alert = Alert(
            id=aid, outlet_id=outlet_id, provider_id=provider_id, kind=kind,
            severity=Severity.MEDIUM.value, confidence=0.0, reason="",
            created_at=now,
        )
        return alert

    def _emit_liquidity_alert(self, state, pid: str, pos, proj, now: float,
                              suppressed: bool) -> None:
        alert = self._new_alert(state.outlet.id, pid, AlertKind.LIQUIDITY, now)
        if suppressed:
            alert.kind = AlertKind.DATA_QUALITY
            alert.classification = Classification.DATA_QUALITY
            alert.severity = Severity.MEDIUM.value
            alert.confidence = 0.9
            alert.feed_withdrawn = True
            alert.reason = ("feed data cannot be trusted; projection withdrawn "
                            "rather than estimated")
        else:
            sev = liquid_severity(proj)
            alert.severity = (sev or Severity.LOW).value
            alert.confidence = round(proj.confidence, 2)
            alert.classification = Classification.NORMAL
            if proj.exhausted:
                alert.reason = "balance is already depleted"
            else:
                alert.reason = (f"projected to run out in "
                                f"{format_hours(proj.hours_to_empty, 'en')}")

        self._apply_narratives(alert, *self._liquidity_narratives(proj, pid,
                                                                  suppressed))
        open_case(alert, now, self._cases.get(alert.id))
        self.alerts[alert.id] = alert

    def _apply_narratives(self, alert: Alert, n_bn: Narrative,
                          n_en: Narrative) -> None:
        """Attach prose and structured fields from the narrative objects.

        The structured fields are read off the objects rather than parsed back
        out of the rendered text. Re-deriving ``evidence`` by splitting a
        rendered string on blank lines would silently break the moment two
        newline conventions drifted apart — which is exactly the kind of bug
        that shows up as a blank evidence panel mid-demo.
        """
        alert.narrative_bn = flatten(n_bn)
        alert.narrative_en = flatten(n_en)
        alert.narrative_source = n_en.source
        alert.parts_bn = _parts(n_bn)
        alert.parts_en = _parts(n_en)
        alert.evidence = list(n_en.evidence)
        alert.uncertainty = n_en.uncertainty
        alert.recommended_steps = list(n_en.next_steps)

    def _liquidity_narratives(self, proj, pid: str, suppressed: bool
                              ) -> tuple[Narrative, Narrative]:
        bn = assemble_liquidity(proj, pid, _provider_name(pid, "en"),
                                _provider_name(pid, "bn"), "bn", suppressed)
        en = assemble_liquidity(proj, pid, _provider_name(pid, "en"),
                                _provider_name(pid, "bn"), "en", suppressed)
        if self.use_llm:
            bn = rephrase(bn, "bn")
            en = rephrase(en, "en")
        return bn, en

    def _emit_cash_alert(self, state, proj, now: float) -> None:
        alert = self._new_alert(state.outlet.id, None, AlertKind.LIQUIDITY, now)
        sev = liquid_severity(proj) or Severity.MEDIUM
        alert.severity = sev.value
        alert.confidence = round(proj.confidence, 2)
        alert.reason = (f"shared cash projected to run out in "
                        f"{format_hours(proj.hours_to_empty, 'en')}")
        self._apply_narratives(alert, *self._cash_narratives(state, proj))
        open_case(alert, now, self._cases.get(alert.id))
        self.alerts[alert.id] = alert

    def _cash_narratives(self, state, proj) -> tuple[Narrative, Narrative]:
        hours_bn = format_hours(proj.hours_to_empty, "bn")
        hours_en = format_hours(proj.hours_to_empty, "en")
        bal_bn = format_bdt(proj.balance, "bn")
        bal_en = format_bdt(proj.balance, "en")
        name_bn = state.outlet.name
        name_en = state.outlet.name

        bn = Narrative(
            situation=(f"{name_bn}-এ নগদ টাকা শেষ হয়ে যেতে পারে — আনুমানিক "
                       f"{hours_bn} পরে।"),
            evidence=[f"বর্তমান নগদ {bal_bn}",
                      f"ব্যবহারের হার {format_bdt(proj.rate_per_hour, 'bn')} প্রতি ঘণ্টা",
                      "নগদ ক্যাশ-আউটে কমে এবং ক্যাশ-ইনে বাড়ে"],
            uncertainty=(f"এই পূর্বাভাস সাম্প্রতিক লেনদেনের ধারার ভিত্তিতে; "
                         f"আস্থার মাত্রা {int(proj.confidence * 100)}%।"),
            next_steps=["যাচাই করা ফিড থেকে নগদের অবস্থা নিশ্চিত করুন",
                        "কাছাকাছি শাখার সাথে নগদ সমন্বয়ের বিষয়ে যোগাযোগ করুন",
                        "প্রয়োজনে জ্যেষ্ঠ কর্মকর্তাকে অবহিত করুন"],
        )
        en = Narrative(
            situation=(f"{name_en} may run out of physical cash in about "
                       f"{hours_en}."),
            evidence=[f"current cash {bal_en}",
                      f"drain rate {format_bdt(proj.rate_per_hour, 'en')} per hour",
                      "cash falls on cash-out and rises on cash-in"],
            uncertainty=(f"This projection is drawn from the recent transaction "
                         f"trend; confidence {int(proj.confidence * 100)}%."),
            next_steps=["confirm cash position against a verified feed",
                        "coordinate with a nearby outlet about a cash arrangement",
                        "notify a senior officer if the position worsens"],
        )
        if self.use_llm:
            bn, en = rephrase(bn, "bn"), rephrase(en, "en")
        return bn, en

    def _emit_signal_alert(self, state, sig, ctx: str, now: float) -> None:
        verdict = classify(sig, state.transactions, ctx)
        kind = (AlertKind.DATA_QUALITY if sig.kind == "balance_chain"
                else AlertKind.ANOMALY)
        alert = self._new_alert(state.outlet.id, sig.provider_id, kind, now)
        alert.classification = verdict.classification
        alert.severity = verdict.priority
        alert.confidence = verdict.confidence
        alert.reason = verdict.accepted
        alert.rejected_hypotheses = list(verdict.rejected_hypotheses)
        alert.evidence = list(sig.evidence)

        if sig.kind == "balance_chain":
            diff = next((e for e in sig.evidence if "difference" in e), "")
            # Each language gets its own rejection reasons here too — the same
            # reason the anomaly branch below gives for not leaving the block
            # untranslated.
            n_bn = assemble_data_quality(diff, "bn", verdict.rejected_for("bn"))
            n_en = assemble_data_quality(diff, "en", verdict.rejected_for("en"))
        else:
            # Each language gets its own rejection reasons. The block is the
            # part a reviewer is meant to check hardest, so it is not left
            # untranslated for the readers who most need to check it.
            n_bn = assemble_anomaly("; ".join(sig.evidence),
                                    verdict.rejected_for("bn"), "bn")
            n_en = assemble_anomaly("; ".join(sig.evidence),
                                    verdict.rejected_for("en"), "en")

        if self.use_llm:
            n_bn, n_en = rephrase(n_bn, "bn"), rephrase(n_en, "en")
        self._apply_narratives(alert, n_bn, n_en)
        # The signal's own evidence is more specific than the narrative's, so it
        # wins where the two disagree.
        alert.evidence = list(sig.evidence)
        open_case(alert, now, self._cases.get(alert.id))
        self.alerts[alert.id] = alert

    @staticmethod
    def _steps_from(text: str) -> list[str]:
        return [line.lstrip("→ ").strip()
                for line in (text or "").splitlines()
                if line.strip().startswith("→")]

    # -- aggregation ---------------------------------------------------------
    def _aggregate(self, rows: list[dict], world: dict, now: float,
                   episodes: list) -> None:
        horizon = SETTINGS["alert_horizon_hours"]
        candidates = []
        for row in rows:
            for pos in row["positions"]:
                candidates.append((_outlet_lookup(world, row["id"]),
                                   pos["provider_id"], pos["hours_to_empty"],
                                   pos["balance"]))

        # --- hotspot + nearby support ---------------------------------------
        risk_rows = []
        support: list[dict] = []
        for row in rows:
            at_risk = bool(row["worst_hours"] is not None
                           and row["worst_hours"] <= horizon)
            risk_rows.append({
                "outlet": _outlet_lookup(world, row["id"]),
                "total_cash": row["cash"],
                "total_emoney": row["total_value"] - row["cash"],
                "at_risk": at_risk,
                "worst_hours": row["worst_hours"],
            })
            if not at_risk:
                continue
            for pos in row["positions"]:
                if pos["hours_to_empty"] is None or pos["suppressed"]:
                    continue
                if pos["hours_to_empty"] > horizon:
                    continue
                found = hotspot.find_support(
                    _outlet_lookup(world, row["id"]), pos["provider_id"],
                    candidates, source_balance=pos["balance"])
                if found:
                    found["outlet_id_source"] = row["id"]
                    found["outlet_name_source"] = row["name"]
                    found["hours_remaining"] = pos["hours_to_empty"]
                    support.append(found)

        areas = hotspot.area_risks(risk_rows)
        self._hotspot_payload = {
            "areas": [
                {"area": r.area, "district": r.district,
                 "outlet_count": r.outlet_count, "at_risk_count": r.at_risk_count,
                 "total_cash": r.total_cash, "total_emoney": r.total_emoney}
                for r in areas],
            "summary": hotspot.hotspot_summary(areas),
        }
        self._support = support
        self._focus = self._resolve_focus(episodes, rows, world)

        # --- coordination alert ---------------------------------------------
        by_area: dict[str, list[dict]] = {}
        for row in rows:
            by_area.setdefault(row["area"], []).append(row)
        for area, group in by_area.items():
            pressed = [r for r in group
                       if r["worst_hours"] is not None
                       and r["worst_hours"] <= SETTINGS["alert_horizon_hours"]]
            if len(pressed) < SETTINGS["hotspot_min_outlets"]:
                continue
            anchor = min(pressed, key=lambda r: r["worst_hours"])
            alert = self._new_alert(anchor["id"], None,
                                    AlertKind.COORDINATION, now)
            alert.severity = Severity.HIGH.value
            alert.confidence = 0.8
            alert.reason = (f"{len(pressed)} outlets in {area} are projected to "
                            f"run short within the alert horizon")
            names = ", ".join(r["name"] for r in pressed)
            n_bn = assemble_coordination(
                f"{area} এলাকার {len(pressed)}টি শাখায় ঘাটতির আশঙ্কা: {names}",
                "এরিয়া ম্যানেজার",
                ["শাখাগুলোর মধ্যে অনুমোদিত চ্যানেলে সমন্বয় করুন",
                 "কোন শাখায় আগে সহায়তা প্রয়োজন তা নির্ধারণ করুন"], "bn")
            n_en = assemble_coordination(
                f"{len(pressed)} outlets in {area} are projected to run short: "
                f"{names}", "area manager",
                ["coordinate between the outlets through the approved channel",
                 "decide which outlet needs support first"], "en")
            if self.use_llm:
                n_bn, n_en = rephrase(n_bn, "bn"), rephrase(n_en, "en")
            self._apply_narratives(alert, n_bn, n_en)
            open_case(alert, now, self._cases.get(alert.id))
            self.alerts[alert.id] = alert

        # --- network ---------------------------------------------------------
        nodes, edges = network.build_graph(world)
        self._network_payload = {
            "nodes": [
                {"account_hash": n.account_hash, "outlet_ids": n.outlet_ids,
                 "provider_ids": n.provider_ids, "txn_count": n.txn_count,
                 "total_value": n.total_value,
                 "is_concentrated": n.is_concentrated}
                for n in nodes],
            "edges": [
                {"source": e.source, "target": e.target,
                 "shared_txns": e.shared_txns, "providers": e.providers}
                for e in edges],
            "summary": network.summarise(nodes, edges),
            "cross_provider": network.cross_provider_patterns(world)[:20],
        }

        self._metrics = self._score(episodes, rows)

    LABEL_TO_KIND = {"anomaly": "anomaly", "data_quality": "data_quality",
                     "demand_spike": "liquidity"}

    SCENARIO_COPY = {
        "baseline": ("Baseline network",
                     "Ordinary operations across the whole network."),
        "A": ("Scenario A — provider liquidity",
              "One provider's e-money is draining toward exhaustion while the "
              "shared cash drawer fills up. Aggregate value looks healthy."),
        "B": ("Scenario B — pattern requiring review",
              "Near-identical amounts at speed from a handful of accounts."),
        "B2": ("Scenario B2 — ordinary demand spike",
               "High volume across many accounts during Eid. The same shape as "
               "B on a chart, and the correct answer is to do nothing."),
        "C": ("Scenario C — data-quality fault",
              "A declared balance no longer reconciles. A feed problem, not a "
              "behavioural finding."),
    }

    def _resolve_focus(self, episodes: list, rows: list, world: dict) -> dict:
        """Which outlet and alert the named demo scenario is about.

        The world always contains every planted situation, because measured
        precision needs complete ground truth. The scenario selector therefore
        cannot *change* the data without making the metrics a lie — so instead
        it says which story to look at, and the dashboard opens there.
        """
        title, blurb = self.SCENARIO_COPY.get(
            self.scenario, self.SCENARIO_COPY["baseline"])
        focus = {"scenario": self.scenario, "title": title, "blurb": blurb,
                 "outlet_id": None, "provider_id": None, "alert_id": None,
                 "kind": None, "expectation": "none", "classifier": None}

        label = {"B": "anomaly", "B2": "demand_spike",
                 "C": "data_quality"}.get(self.scenario)

        if label:
            ep = next((e for e in episodes if e.label == label), None)
            if ep is None:
                return focus
            focus["outlet_id"] = ep.outlet_id
            focus["provider_id"] = ep.provider_id
            focus["kind"] = self.LABEL_TO_KIND[label]
        elif self.scenario == "A":
            # Scenario A deliberately carries no Episode — it is a liquidity
            # case, and the three ground-truth labels describe the other
            # detectors. Find it by looking for the soonest provider drain
            # outside the labelled outlets.
            labelled = {e.outlet_id for e in episodes}
            best = None
            for row in rows:
                if row["id"] in labelled:
                    continue
                for pos in row["positions"]:
                    hours = pos["hours_to_empty"]
                    if hours is None or pos["suppressed"]:
                        continue
                    if best is None or hours < best[0]:
                        best = (hours, row["id"], pos["provider_id"])
            if best is None:
                return focus
            focus["outlet_id"] = best[1]
            focus["provider_id"] = best[2]
            focus["kind"] = "liquidity"
        else:
            return focus

        for alert in self._sorted_alerts():
            if (alert.outlet_id == focus["outlet_id"]
                    and alert.kind.value == focus["kind"]):
                focus["alert_id"] = alert.id
                break

        if label == "demand_spike":
            # The correct outcome for B2 is *no alert*. That is the hardest
            # result to demo, because an empty panel looks like a failure. So
            # say the quiet part out loud: show the measurements that justify
            # doing nothing, and name them as the reason.
            focus["kind"] = "demand_spike"
            focus["expectation"] = "no_action"
            focus["classifier"] = self._explain_demand_spike(
                world.get(focus["outlet_id"]), focus["provider_id"])
        else:
            focus["expectation"] = "action" if focus["alert_id"] else "watch"
        return focus

    @staticmethod
    def _explain_demand_spike(state, provider_id: str | None) -> dict:
        """The numbers behind a demand-spike verdict, for the B2 story."""
        if state is None:
            return {}
        stats = account_concentration(state.transactions, provider_id)
        ctx = calendar_context(state.transactions[-1].ts
                               if state.transactions else 0.0)
        return {
            "accounts": stats["accounts"],
            "txns": stats["txns"],
            "top_account_share": round(stats["top_share"], 2),
            "amount_spread": round(stats["amount_spread"], 2),
            "calendar_context": ctx,
            "verdict": (
                "demand_spike"
                if stats["accounts"] >= SETTINGS["demand_spike_account_floor"]
                and stats["amount_spread"] > SETTINGS["narrow_spread_ratio"]
                else "needs_review"),
            "explanation": (
                f"{stats['accounts']} distinct accounts across "
                f"{stats['txns']} transactions with a "
                f"{stats['amount_spread']:.0%} amount spread. Broad, diverse "
                f"demand — the same shape as a pattern under review, and the "
                f"reason it is not one."),
        }

    def _score(self, episodes: list, rows: list) -> dict:
        """Measured precision/recall against the simulator's own ground truth.

        A withdrawn projection is excluded from ``detected``: alerting that a
        feed is untrustworthy is a statement about data integrity, not a claim
        that activity was found, and the ground truth has no episode kind for
        it. Counting it would let feed faults masquerade as detections — and,
        when one happens to land on an outlet with a real episode, inflate the
        score quietly.
        """
        expected = {(e.outlet_id, e.label) for e in episodes
                    if e.label in ("anomaly", "data_quality")}
        detected = {(a.outlet_id, a.kind.value) for a in self.alerts.values()
                    if a.kind.value in ("anomaly", "data_quality")
                    and not a.feed_withdrawn}
        tp = len(expected & detected)
        fp = len(detected - expected)
        fn = len(expected - detected)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        negatives = max(1, len(rows) - len({o for o, _ in expected}))
        return {
            "episodes": len(episodes),
            "expected_findings": len(expected),
            "detected_findings": len(detected),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "false_positive_rate": round(fp / negatives, 3),
            "demand_spike_episodes": sum(1 for e in episodes
                                         if e.label == "demand_spike"),
            "needs_review_alerts": sum(
                1 for a in self.alerts.values()
                if a.classification is Classification.NEEDS_REVIEW),
            "note": ("Ground truth comes from the simulator's planted episodes. "
                     "Precision and recall are measured, not asserted."),
        }

    def _summary(self, rows: list[dict]) -> dict:
        alerts = list(self.alerts.values())
        return {
            "outlets": len(rows),
            "alerts": len(alerts),
            "critical": sum(1 for a in alerts
                            if a.severity == Severity.CRITICAL.value),
            "high": sum(1 for a in alerts if a.severity == Severity.HIGH.value),
            "needs_review": sum(1 for a in alerts
                                if a.classification is Classification.NEEDS_REVIEW),
            "data_quality": sum(1 for a in alerts
                                if a.kind is AlertKind.DATA_QUALITY),
            "open_cases": sum(1 for a in alerts if a.status is CaseStatus.NEW),
            "suppressed_projections": sum(
                1 for r in rows for p in r["positions"] if p["suppressed"]),
            "total_cash": round(sum(r["cash"] for r in rows), 2),
            "total_value": round(sum(r["total_value"] for r in rows), 2),
            "at_risk_outlets": sum(
                1 for r in rows if r["worst_hours"] is not None
                and r["worst_hours"] <= SETTINGS["alert_horizon_hours"]),
        }

    def _sorted_alerts(self) -> list[Alert]:
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(self.alerts.values(),
                      key=lambda a: (order.get(a.severity, 9),
                                     -(a.confidence or 0), a.id))

    @staticmethod
    def _alert_payload(a: Alert) -> dict:
        return {
            "id": a.id,
            "outlet_id": a.outlet_id,
            "provider_id": a.provider_id,
            "kind": a.kind.value,
            "severity": a.severity,
            "confidence": a.confidence,
            "reason": a.reason,
            "classification": a.classification.value,
            "evidence": a.evidence,
            "uncertainty": a.uncertainty,
            "rejected_hypotheses": [list(r) for r in a.rejected_hypotheses],
            "recommended_steps": a.recommended_steps,
            "feed_withdrawn": a.feed_withdrawn,
            "status": a.status.value,
            "owner": a.owner,
            "assignee": a.assignee,
            "created_at": a.created_at,
            "narrative_bn": a.narrative_bn,
            "narrative_en": a.narrative_en,
            "narrative_source": a.narrative_source,
            "parts_bn": a.parts_bn,
            "parts_en": a.parts_en,
        }

    # -- case actions --------------------------------------------------------
    # Actors who are not on a provider's own track. An oversight user handles a
    # nagad alert *within* the nagad track rather than across it, so their
    # actions still pass the boundary check — they are not bypassing it.
    CROSS_TRACK_ACTORS = (None, "", "central", "central_operations",
                          "oversight", "risk_analyst")

    def act(self, alert_id: str, action: str, actor: str, note: str = "",
            actor_provider: str | None = None) -> dict:
        """Apply a case action, enforcing the provider boundary.

        ``actor_provider`` is how the actor declares their track. Omitting it,
        or naming an oversight role, means "acting within whichever track owns
        this alert" — which is what a central operator actually does. Naming a
        *different* provider is refused with ``PermissionError``, and that
        refusal is the guardrail rather than a bug: the tracks are separate by
        design, and the remedy is coordination through the approved channel.
        """
        from app.coordination import transition
        alert = self.alerts.get(alert_id)
        if alert is None:
            raise KeyError(alert_id)

        if actor_provider in self.CROSS_TRACK_ACTORS:
            actor_provider = alert.provider_id

        now = self.snapshot.get("generated_at", time.time())
        alert = transition(alert, action, actor, note, now,
                           actor_provider=actor_provider, log=self.audit)
        self._cases[alert_id] = (alert.status, alert.owner, alert.assignee)
        self._publish_case(alert)
        return self._alert_payload(alert)

    def _publish_case(self, alert: Alert) -> None:
        """Write a case action back into the snapshot the API serves.

        ``self.alerts`` is the live object graph, but ``/api/state`` serves
        ``self.snapshot["alerts"]`` — a list of dicts serialized at build time.
        Without this, the POST response said "acknowledged" while the very next
        GET said "new", and the dashboard redrew the case as untouched. The
        open-case count is refreshed with it, since it is derived from statuses.
        """
        payload = self._alert_payload(alert)
        for entry in self.snapshot.get("alerts", []):
            if entry.get("id") == alert.id:
                entry.update(payload)
                break
        if "summary" in self.snapshot:
            self.snapshot["summary"]["open_cases"] = sum(
                1 for a in self.alerts.values() if a.status is CaseStatus.NEW)

    def history(self, alert_id: str | None = None) -> list[dict]:
        return self.audit.trail(alert_id) if alert_id else self.audit.everything()


def _outlet_lookup(world: dict, outlet_id: str):
    state = world.get(outlet_id)
    return state.outlet if state else None
