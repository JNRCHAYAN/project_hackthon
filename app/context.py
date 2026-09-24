"""Context classification — the analytical differentiator.

The same chart can mean three entirely different things:

1. It is Eid week and everyone is cashing out. **Ordinary demand.** Do nothing.
2. The feed is broken and the balance does not reconcile. **Data integrity.**
   Fix the feed; do not interpret the numbers.
3. Amounts are near-identical, concentrated in a handful of accounts, and there
   is no seasonal explanation. **Requires human review.** Escalate.

A detector that outputs a bare risk score cannot express this, which is why this
module emits a *classification with reasoning*, including which hypotheses were
considered and rejected. The rejected-hypothesis list is what makes an alert
explainable to a risk analyst rather than merely alarming — which is also why it
is produced in both languages rather than English only. Reasoning that only the
English-reading half of the audience can check is not really explainability.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from app.config import SETTINGS
from app.domain import Classification

# Eid-ul-Fitr 2026 falls around 20 March; a band of +/- eid_window_days either
# side is treated as context. Derived from config rather than written as a
# literal so that the window and the simulator's clock cannot drift apart — they
# did once, and the context classifier silently degraded to "ordinary".
_HALF_WINDOW = SETTINGS["eid_window_days"] * 86_400.0
_EID_ANCHOR = SETTINGS["eid_ul_fitr_2026"]
EID_WINDOWS = [(_EID_ANCHOR - _HALF_WINDOW, _EID_ANCHOR + _HALF_WINDOW)]

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def bn_num(value: object) -> str:
    """Render a number with Bengali digits for Bengali-language prose."""
    return str(value).translate(_BN_DIGITS)


@dataclass
class Verdict:
    classification: Classification
    confidence: float
    priority: str                                # low | medium | high
    accepted: str = ""
    accepted_bn: str = ""
    rejected_hypotheses: list[tuple[str, str]] = field(default_factory=list)
    rejected_hypotheses_bn: list[tuple[str, str]] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)

    def rejected_for(self, lang: str) -> list[tuple[str, str]]:
        if lang == "bn" and self.rejected_hypotheses_bn:
            return self.rejected_hypotheses_bn
        return self.rejected_hypotheses


def calendar_context(ts: float) -> str:
    """Which calendar effect, if any, is in play. Deliberately conservative."""
    for start, end in EID_WINDOWS:
        if start <= ts <= end:
            return "eid_window"
    day = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
    if day.day <= 5:
        return "salary_day"
    if day.weekday() in (4, 5):     # Fri/Sat weekend market peak in Bangladesh
        return "market_day"
    return "ordinary"


_CONTEXT_BN = {
    "eid_window": "ঈদ সপ্তাহ",
    "salary_day": "বেতন প্রদানের দিন",
    "market_day": "সাপ্তাহিক বাজারের দিন",
    "ordinary": "সাধারণ দিন",
}

# Phrases that read as a date range. Kept distinct from the raw context token so
# the prose does not end up saying "within the eid window window".
_CONTEXT_PHRASE = {
    "eid_window": "the eid window",
    "salary_day": "the salary day window",
    "market_day": "the weekly market peak",
}


def _context_phrase(ctx: str) -> str:
    return _CONTEXT_PHRASE.get(ctx, f"the {ctx.replace('_', ' ')}")


def _spread_ratio(amounts: list[float]) -> float:
    if not amounts:
        return 0.0
    lo, hi = min(amounts), max(amounts)
    if hi <= 0:
        return 0.0
    return (hi - lo) / hi


def classify(signal, txns: list, ctx: str) -> Verdict:
    """Three-way verdict with explicit reasoning about what was ruled out."""
    # --- Data integrity faults are never suspicion ---------------------------
    if signal.kind == "balance_chain":
        return Verdict(
            classification=Classification.DATA_QUALITY,
            confidence=0.9, priority="medium",
            accepted="data-quality problem — the balance chain does not reconcile",
            accepted_bn="ডেটা সমন্বয়ের সমস্যা — ব্যালেন্সের হিসাব মিলছে না",
            rejected_hypotheses=[
                ("suspicious activity",
                 "an unexplained balance difference is a data integrity fault; "
                 "it carries no information about customer behaviour"),
                ("operational demand spike",
                 "a reconciliation failure is independent of transaction volume"),
            ],
            rejected_hypotheses_bn=[
                ("সন্দেহজনক কার্যক্রম",
                 "ব্যাখ্যাতীত ব্যালেন্স পার্থক্য হলো ডেটা সমন্বয়ের ত্রুটি; "
                 "এটি গ্রাহকের আচরণ সম্পর্কে কোনো তথ্য দেয় না"),
                ("স্বাভাবিক চাহিদার বৃদ্ধি",
                 "হিসাব না মেলার সমস্যা লেনদেনের পরিমাণের সাথে সম্পর্কিত নয়"),
            ],
            rationale=[
                "the provider-declared balance disagrees with the reconciled chain",
                "feed verification is recommended before any interpretation",
            ])

    accounts = len(set(signal.accounts))
    spread = _spread_ratio(signal.amounts)
    context_aligned = ctx in ("eid_window", "salary_day", "market_day")
    floor = SETTINGS["demand_spike_account_floor"]
    narrow = SETTINGS["narrow_spread_ratio"]
    label_bn = _CONTEXT_BN.get(ctx, _CONTEXT_BN["ordinary"])

    # --- Broad, diverse, wide-ranged activity is ordinary demand -------------
    if accounts >= floor and spread > narrow:
        return Verdict(
            classification=Classification.DEMAND_SPIKE,
            confidence=0.75, priority="low",
            accepted="operational demand spike"
                     + (f" consistent with the {ctx.replace('_', ' ')}"
                        if context_aligned else ""),
            accepted_bn=("স্বাভাবিক চাহিদার বৃদ্ধি"
                         + (f" — {label_bn}-এর সাথে সঙ্গতিপূর্ণ"
                            if context_aligned else "")),
            rejected_hypotheses=[
                ("pattern requiring review",
                 f"activity is spread across {accounts} distinct accounts with a "
                 f"broad amount range ({spread:.0%} spread), which is ordinary "
                 f"high-demand behaviour rather than concentrated activity"),
                ("data-quality problem",
                 "the balance chain reconciles; only volume is elevated"),
            ],
            rejected_hypotheses_bn=[
                ("পর্যালোচনাপ্রয়োজন এমন ধারা",
                 f"কার্যক্রম {bn_num(accounts)}টি আলাদা অ্যাকাউন্টে ছড়িয়ে আছে এবং "
                 f"পরিমাণের ব্যবধানও বিস্তৃত ({bn_num(f'{spread:.0%}')}) — এটি "
                 f"স্বাভাবিক উচ্চ-চাহিদার আচরণ, কেন্দ্রীভূত কার্যক্রম নয়"),
                ("ডেটা সমন্বয়ের সমস্যা",
                 "ব্যালেন্সের হিসাব মিলছে; কেবল লেনদেনের পরিমাণ বেশি"),
            ],
            rationale=[
                f"{accounts} distinct accounts involved",
                f"amount spread {spread:.0%} — not near-identical",
                f"calendar context: {ctx}",
            ])

    # --- Narrow, concentrated activity requires a human ----------------------
    rejected: list[tuple[str, str]] = []
    rejected_bn: list[tuple[str, str]] = []
    if context_aligned:
        rejected.append(
            ("operational demand spike",
             f"although the date falls within {_context_phrase(ctx)}, "
             f"activity is concentrated in only {accounts} accounts with "
             f"near-identical amounts — seasonal demand does not look like this"))
        rejected_bn.append(
            ("স্বাভাবিক চাহিদার বৃদ্ধি",
             f"তারিখটি {label_bn}-এর মধ্যে পড়লেও কার্যক্রম মাত্র "
             f"{bn_num(accounts)}টি অ্যাকাউন্টে কেন্দ্রীভূত এবং পরিমাণ প্রায় "
             f"একই — মৌসুমি চাহিদা এমন দেখায় না"))
    else:
        rejected.append(
            ("operational demand spike",
             f"no seasonal or salary-day context applies to this date, and "
             f"activity is concentrated in only {accounts} accounts"))
        rejected_bn.append(
            ("স্বাভাবিক চাহিদার বৃদ্ধি",
             f"এই তারিখে কোনো মৌসুমি বা বেতন-দিবসের প্রেক্ষাপট নেই, এবং "
             f"কার্যক্রম মাত্র {bn_num(accounts)}টি অ্যাকাউন্টে কেন্দ্রীভূত"))
    rejected.append(
        ("data-quality problem", "the balance chain reconciles cleanly"))
    rejected_bn.append(
        ("ডেটা সমন্বয়ের সমস্যা", "ব্যালেন্সের হিসাব পরিষ্কারভাবে মিলছে"))

    return Verdict(
        classification=Classification.NEEDS_REVIEW,
        confidence=0.72, priority="high",
        accepted="pattern requiring human review",
        accepted_bn="মানুষের পর্যালোচনা প্রয়োজন এমন ধারা",
        rejected_hypotheses=rejected,
        rejected_hypotheses_bn=rejected_bn,
        rationale=[
            f"{accounts} accounts only, across {len(signal.amounts)} transactions",
            f"amount spread {spread:.0%} — near-identical",
            f"calendar context: {ctx}",
            "advisory only — this is not a determination of wrongdoing",
        ])


def verdict_to_alert_fields(verdict: Verdict, lang: str = "en") -> dict:
    return {
        "classification": verdict.classification,
        "severity": verdict.priority,
        "confidence": verdict.confidence,
        "rejected_hypotheses": verdict.rejected_for(lang),
        "reason": verdict.accepted_bn if lang == "bn" else verdict.accepted,
        "rationale": verdict.rationale,
    }
