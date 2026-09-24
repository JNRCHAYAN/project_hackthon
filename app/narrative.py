"""Deterministic bilingual narrative assembler.

This is the safety net of the whole product. Every alert the system can raise
has to be readable by a human even when the LLM layer is unreachable, rate
limited, or simply wrong. So this module is:

* **pure** — no network, no clock, no I/O, no randomness;
* **deterministic** — the same inputs always yield the same Bengali and
  English text, which is what makes the alerts auditable after the fact;
* **bilingual by construction** — every assembler emits both scripts, so a
  language is never a reason for an alert to be missing;
* **non-accusatory** — the four-part shape (situation, evidence, uncertainty,
  safe next step) plus :func:`lint` keep the wording away from any claim about
  a person. See ``docs/RESPONSIBLE_DESIGN.md``.

The LLM layer (``app.llm``) may later *rephrase* what is produced here; it may
never be the only thing standing between a finding and a human. When it fails,
these texts are what the operator sees, and ``Narrative.source`` stays
``"template"`` so the UI can say so honestly.

House style for the Bengali text: a provider name of unknown inflection takes
the ``-এর`` suffix (e.g. ``নগদ-এর``), and numbers are rendered in Bengali
digits. Latin provider ids, ``৳`` and Bengali words are deliberately mixed —
that mixed-script string is exactly what the UI has to render correctly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Vocabulary this layer must never emit — in either language. These words make
# a claim about a person, and no template here is in a position to make one.
FORBIDDEN = ("fraud", "fraudulent", "প্রতারণা", "cheating", "criminal", "অপরাধ")

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

_UNKNOWN = {"bn": "অজানা", "en": "unknown"}

# Neutral rephrasings used when upstream analytics hands us text that already
# contains forbidden vocabulary. This layer refuses to pass an accusation on,
# even one it did not write itself. Each pattern eats the whole inflected word
# ("fraudulent", "প্রতারণার"), so the replacement never leaves a stem behind.
_BN = "ঀ-৿"  # the Bengali block
_REDACT_RULES = (
    (re.compile(r"fraud[a-z]*", re.IGNORECASE), "unusual activity"),
    (re.compile(r"cheat[a-z]*", re.IGNORECASE), "unusual conduct"),
    (re.compile(r"criminal[a-z]*", re.IGNORECASE), "unusual"),
    (re.compile(f"প্রতারণা[{_BN}]*"), "অস্বাভাবিক কার্যক্রম"),
    (re.compile(f"অপরাধ[{_BN}]*"), "অস্বাভাবিক ঘটনা"),
)


def lint(text: str) -> list[str]:
    """Return the forbidden words present in ``text`` (case-insensitive).

    An empty list is the only acceptable result for anything this module
    generates.
    """
    if not text:
        return []
    low = text.lower()
    return [w for w in FORBIDDEN if w in low]


def redact(text: str) -> str:
    """Neutralise forbidden vocabulary that arrived from an upstream layer."""
    if not text:
        return text
    for pattern, replacement in _REDACT_RULES:
        text = pattern.sub(replacement, text)
    return text


def format_bdt(amount: float | None, lang: str = "en") -> str:
    """``6200`` -> ``৳6,200`` (or ``৳৬,২০০`` in Bengali)."""
    if amount is None:
        return _UNKNOWN.get(lang, _UNKNOWN["en"])
    text = f"{amount:,.0f}"
    if lang == "bn":
        text = text.translate(_BN_DIGITS)
    return f"৳{text}"


def format_hours(hours: float | None, lang: str = "en") -> str:
    """One decimal place; Bengali digits in Bengali.

    ``None`` renders as a word, never as the literal ``"None"`` — an alert
    that prints "None hours" is worse than one that admits it does not know.
    """
    if hours is None:
        return _UNKNOWN.get(lang, _UNKNOWN["en"])
    text = f"{hours:.1f}"
    return text.translate(_BN_DIGITS) if lang == "bn" else text


def format_confidence(confidence: float | None, lang: str = "en") -> str:
    """Two decimals — confidence is a probability, so 0.71 must stay 0.71."""
    if confidence is None:
        return _UNKNOWN.get(lang, _UNKNOWN["en"])
    text = f"{confidence:.2f}"
    return text.translate(_BN_DIGITS) if lang == "bn" else text


@dataclass
class Narrative:
    """The four required parts, plus what we deliberately did not say."""

    situation: str = ""
    evidence: list[str] = field(default_factory=list)
    uncertainty: str = ""
    next_steps: list[str] = field(default_factory=list)
    rejected_text: str = ""
    source: str = "template"  # template | llm

    def uncertainty_multiline(self) -> list[str]:
        return self.uncertainty.splitlines()

    def as_text(self) -> str:
        parts = [self.situation, *self.evidence]
        if self.rejected_text:
            parts.append(self.rejected_text)
        parts.append(self.uncertainty)
        parts.extend(self.next_steps)
        return "\n".join(p for p in parts if p)


def _get(obj, name: str, default=None):
    """Duck-typed attribute read so the assembler never hard-depends on the
    analytics classes (which may not be importable in every context)."""
    return getattr(obj, name, default)


def _lines(items) -> list[str]:
    """Normalise a caller's steps: str | iterable | None -> non-empty list."""
    if items is None:
        return []
    if isinstance(items, str):
        items = [items]
    return [s for s in (str(s).strip() for s in items) if s]


def assemble_liquidity(proj, provider_id: str, provider_name: str,
                       provider_name_bn: str, lang: str = "bn",
                       suppressed: bool = False) -> Narrative:
    """Projection alert for one provider's e-money balance.

    Three cases, and only three:

    * ``suppressed`` — we do not trust the feed, so we refuse to project at all;
    * no depletion (``hours_to_empty is None``) — say that plainly;
    * normal — give the point estimate *and* the interval it came from.
    """
    name = provider_name_bn if lang == "bn" else provider_name
    bal = format_bdt(_get(proj, "balance"), lang)

    if suppressed:
        if lang == "bn":
            return Narrative(
                situation=(f"{name}-এর ব্যালেন্স তথ্য নির্ভরযোগ্যভাবে পাওয়া "
                           f"যাচ্ছে না, তাই এই মুহূর্তে কোনো পূর্বাভাস দেওয়া "
                           f"সম্ভব নয়।"),
                evidence=[f"সর্বশেষ ঘোষিত ব্যালেন্স {bal}",
                          "প্রদানকারীর ফিড ডেটা অসম্পূর্ণ বা পরস্পরবিরোধী",
                          f"প্রদানকারী সূত্র: {provider_id}"],
                uncertainty=("ডেটা নির্ভরযোগ্য নয় — অনুমান করলে তা ভুল হওয়ার "
                             "ঝুঁকি থাকে, তাই কোনো সংখ্যা দেওয়া হচ্ছে না।"),
                next_steps=["অনুমোদিত চ্যানেলে ফিড যাচাই করুন",
                            "যাচাই ছাড়া কোনো সিদ্ধান্ত নেবেন না",
                            "প্রয়োজনে জ্যেষ্ঠ কর্মকর্তাকে অবহিত করুন"],
                source="template")
        return Narrative(
            situation=(f"Liquidity projection for {name} is unavailable: the "
                       f"feed cannot be trusted at this time."),
            evidence=[f"last declared balance {bal}",
                      "provider feed is incomplete or conflicting",
                      f"provider reference: {provider_id}"],
            uncertainty=("The data is not reliable, so no projection and no "
                         "number is offered — a guess here would be worse than "
                         "no answer."),
            next_steps=["Verify the feed through the approved channel",
                        "Do not act on any projection until it is verified",
                        "Notify a senior officer if verification does not complete"],
            source="template")

    hours = _get(proj, "hours_to_empty")
    low = _get(proj, "low_hours")
    high = _get(proj, "high_hours")
    rate = format_bdt(_get(proj, "rate_per_hour"), lang)

    if hours is None:
        # "Not depleting" is a finding, not a missing value. Never print None.
        if lang == "bn":
            return Narrative(
                situation=f"{name}-এর ব্যালেন্স বর্তমানে কমছে না।",
                evidence=[f"বর্তমান ব্যালেন্স {bal}",
                          f"প্রতি ঘণ্টায় নিট প্রবাহ {rate}",
                          "সর্বশেষ প্রাপ্ত ফিড আপডেটের ভিত্তিতে হিসাব"],
                uncertainty=("সাম্প্রতিক তথ্যের ভিত্তিতে কোনো ঘাটতির পূর্বাভাস "
                             "নেই; তাই ঘাটতির কোনো সময়সীমা নির্ধারণ করা যাচ্ছে না।"),
                next_steps=["স্বাভাবিক সেবা চালিয়ে যান",
                            "তথ্য পরিবর্তিত হলে আবার যাচাই করুন",
                            "বড় কোনো পরিবর্তন দেখা গেলে অবহিত করুন"],
                source="template")
        return Narrative(
            situation=f"{name} balance is not currently depleting.",
            evidence=[f"current balance {bal}",
                      f"net flow {rate} per hour",
                      "calculated from the latest available feed update"],
            uncertainty=("No depletion is projected on the current data, so "
                         "there is no exhaustion window to report."),
            next_steps=["Continue normal service",
                        "Recheck if the feed or the flow changes",
                        "Notify a senior officer if a large change appears"],
            source="template")

    h = format_hours(hours, lang)
    lo = format_hours(low, lang)
    hi = format_hours(high, lang)
    conf = format_confidence(_get(proj, "confidence"), lang)
    window = f"{lo}–{hi}" if (low is not None and high is not None) else None

    if lang == "bn":
        span = (f"সম্ভাব্য সীমা {window} ঘণ্টা" if window
                else f"সম্ভাব্য সীমা নির্ধারণ করা যায়নি")
        return Narrative(
            situation=(f"বর্তমান লেনদেনের ধারা অনুযায়ী {name}-এর ই-মানি প্রায় "
                       f"{h} ঘণ্টার মধ্যে ফুরিয়ে যেতে পারে ({span})।"),
            evidence=[f"বর্তমান ব্যালেন্স {bal}",
                      f"প্রতি ঘণ্টায় ব্যালেন্স কমছে প্রায় {rate}",
                      "সর্বশেষ প্রাপ্ত ফিড আপডেটের ভিত্তিতে অনুমান"],
            uncertainty=(f"এটি একটি অনুমান, নিশ্চিত ফলাফল নয় — {span}, "
                         f"আস্থার মাত্রা {conf}। লেনদেনের ধারা বদলালে এই "
                         f"সময়সীমাও বদলাবে।"),
            next_steps=["অনুমোদিত চ্যানেলে অতিরিক্ত ই-মানি ব্যালেন্সের ব্যবস্থা করুন",
                        "শাখা বা ফিল্ড অফিসারকে অবহিত করুন",
                        "প্রদানকারীদের মধ্যে সরাসরি ব্যালেন্স স্থানান্তরের চেষ্টা করবেন না"],
            source="template")
    span = (f"likely range {window} hours" if window
            else "the range could not be bounded")
    return Narrative(
        situation=(f"At the current transaction rate, {name} e-money may be "
                   f"exhausted in about {h} hours ({span})."),
        evidence=[f"current balance {bal}",
                  f"balance falling by {rate} per hour",
                  "estimate based on the latest available feed update"],
        uncertainty=(f"This is an estimate with real uncertainty — {span}, "
                     f"confidence {conf}. The window shifts if transaction "
                     f"flow changes."),
        next_steps=["Arrange additional e-money balance through the approved channel",
                    "Notify the branch or field officer",
                    "Do not attempt to transfer balance between providers"],
        source="template")


def _rejected_block(rejected: list[tuple[str, str]], lang: str) -> str:
    """Render "what was ruled out, and why" for one language.

    Shared by the anomaly and data-quality assemblers so the two cannot drift
    apart. They once did: the data-quality alert hardcoded a single rejected
    hypothesis while the verdict that produced it listed two, so the structured
    list and the prose contradicted each other and the Bengali reader was shown
    half of what the Bengali verdict actually contained.
    """
    if not rejected:
        return ""
    head = ("যেসব সম্ভাব্য কারণ বিবেচনার পর বাদ দেওয়া হয়েছে:"
            if lang == "bn" else
            "Hypotheses considered and set aside:")
    rows = [f"  • {redact(str(n).strip())}: {redact(str(w).strip())}"
            for n, w in rejected]
    return head + "\n" + "\n".join(rows)


def assemble_anomaly(evidence_summary: str,
                     rejected: list[tuple[str, str]] | None = None,
                     lang: str = "bn") -> Narrative:
    """Pattern alert that carries the hypotheses *not* taken.

    The rejected-hypothesis block is the point of this alert: showing what was
    considered and set aside is what turns "unusual" into an accountable
    finding rather than an insinuation.
    """
    summary = redact((evidence_summary or "").strip())
    rejected_text = _rejected_block(list(rejected or []), lang)

    if not summary:
        summary = ("লেনদেনের ধারায় অস্বাভাবিকতা দেখা গেছে"
                   if lang == "bn" else
                   "an unusual pattern was observed in the transaction stream")

    if lang == "bn":
        return Narrative(
            situation=("স্বাভাবিকের চেয়ে ভিন্ন ধরনের লেনদেন লক্ষ করা গেছে; "
                       "বিষয়টি মানুষের পর্যালোচনা প্রয়োজন।"),
            evidence=[summary,
                      "ধারাটি স্বয়ংক্রিয় নিয়মে শনাক্ত হয়েছে — "
                      "কোনো ব্যক্তির অভিযোগের ভিত্তিতে নয়"],
            uncertainty=("সব তথ্য এখনো নিশ্চিত নয় — এটি সাধারণ চাহিদাও হতে "
                         "পারে। তাই কোনো সিদ্ধান্তের আগে একজন কর্মকর্তার "
                         "পর্যালোচনা প্রয়োজন।"),
            next_steps=["অনুমোদিত চ্যানেলে সংশ্লিষ্ট লেনদেনগুলো পর্যালোচনা করুন",
                        "প্রয়োজনে জ্যেষ্ঠ কর্মকর্তার কাছে হস্তান্তর করুন",
                        "কোনো গ্রাহককে অভিযুক্ত করবেন না"],
            rejected_text=rejected_text, source="template")

    return Narrative(
        situation=("An unusual transaction pattern has been identified; the "
                   "case needs human review."),
        evidence=[summary,
                  "the pattern was raised by an automatic rule, not by a person"],
        uncertainty=("Not all information is confirmed — this may equally "
                     "reflect ordinary demand. A human review must come before "
                     "any conclusion."),
        next_steps=["Review the referenced transactions through the approved channel",
                    "Escalate to a senior officer if needed",
                    "Do not accuse any customer"],
        rejected_text=rejected_text, source="template")


def assemble_data_quality(difference_text: str, lang: str = "bn",
                          rejected: list[tuple[str, str]] | None = None) -> Narrative:
    """Reconciliation alert — explicitly *not* a behavioural finding.

    ``rejected`` comes from the context classifier, which is where the three-way
    judgement is actually made. The default below is a single-hypothesis
    fallback for callers that have no verdict to hand; the engine always passes
    the real list so that what the alert says it ruled out matches what the
    classifier actually ruled out, in both languages.
    """
    difference = redact((difference_text or "").strip())
    if not difference:
        difference = "অজানা" if lang == "bn" else "unknown"

    fallback = ([("সন্দেহজনক লেনদেন",
                  "পার্থক্যটির কারণ ডেটা সমন্বয়ের সমস্যা, গ্রাহকের আচরণ নয়")]
                if lang == "bn" else
                [("suspicious transactions",
                  "the gap is a data reconciliation fault, not customer behaviour")])
    rejected_text = _rejected_block(list(rejected or fallback), lang)

    if lang == "bn":
        return Narrative(
            situation="প্রদানকারীর ব্যালেন্স তথ্যে অসঙ্গতি পাওয়া গেছে।",
            evidence=[f"ব্যাখ্যাতীত পার্থক্য {difference}",
                      "ঘোষিত ব্যালেন্স লেনদেনের হিসাবের সাথে মিলছে না"],
            uncertainty=("এটি ডেটা সমন্বয়ের সমস্যা — গ্রাহকের আচরণের প্রমাণ "
                         "নয়। পর্যালোচনার আগে ফিড যাচাই করা প্রয়োজন।"),
            next_steps=["প্রদানকারীর অনুমোদিত চ্যানেলে ফিড যাচাইয়ের অনুরোধ করুন",
                        "যাচাই সম্পন্ন না হওয়া পর্যন্ত পূর্বাভাস স্থগিত রাখুন"],
            rejected_text=rejected_text,
            source="template")

    return Narrative(
        situation="An inconsistency has been detected in provider balance data.",
        evidence=[f"unexplained difference {difference}",
                  "declared balance does not reconcile with the transaction chain"],
        uncertainty=("This is a data reconciliation problem, not evidence of "
                     "customer behaviour. The feed must be verified before any "
                     "interpretation is drawn."),
        next_steps=["Request feed verification through the provider's approved channel",
                    "Suspend projections until verification completes"],
        rejected_text=rejected_text,
        source="template")


def assemble_coordination(situation: str, owner: str,
                          steps: list[str] | None = None,
                          lang: str = "bn") -> Narrative:
    """Escalation / handover alert. Same four parts, deliberately boring."""
    core = redact((situation or "").strip())
    who = redact((owner or "").strip())
    todo = [redact(s) for s in _lines(steps)]

    if lang == "bn":
        if not core:
            core = "একাধিক শাখার মধ্যে সমন্বয় প্রয়োজন।"
        if not who:
            who = "এখনো নির্ধারিত হয়নি"
        if not todo:
            todo = ["উল্লিখিত দায়িত্বপ্রাপ্ত কর্মকর্তার সাথে হস্তান্তর নিশ্চিত করুন",
                    "সিদ্ধান্ত ও সময় কেস লগে লিখে রাখুন"]
        return Narrative(
            situation=core,
            evidence=[f"দায়িত্বপ্রাপ্ত কর্মকর্তা: {who}",
                      "সমন্বয়টি অনুমোদিত অফিসিয়াল চ্যানেলে সম্পন্ন করতে হবে",
                      "শাখাগুলোর মধ্যে সরাসরি ব্যালেন্স হস্তান্তরের প্রস্তাব করা হচ্ছে না"],
            uncertainty=("বিষয়টি সর্বশেষ প্রাপ্ত ফিডের ভিত্তিতে উত্থাপিত; "
                         "যাচাইয়ের পর দায়িত্বপ্রাপ্ত কর্মকর্তা বা অগ্রাধিকার "
                         "বদলাতে পারে।"),
            next_steps=todo, source="template")

    if not core:
        core = "Coordination between the affected outlets is required."
    if not who:
        who = "not yet assigned"
    if not todo:
        todo = ["Confirm the handover with the named owner",
                "Record the decision and the time in the case log"]
    return Narrative(
        situation=core,
        evidence=[f"accountable owner: {who}",
                  "the coordination must run through the approved official channel",
                  "no direct balance transfer between outlets is proposed"],
        uncertainty=("This escalation rests on the latest available feed; "
                     "ownership or priority may change once it is verified."),
        next_steps=todo, source="template")
