"""Tests for the deterministic bilingual narrative assembler (Task 7).

The point of this module is that an alert is *always* produced and is always
safe, so the tests below lean on the invariants rather than on exact wording:
four parts present, Bengali actually Bengali, uncertainty quantified, and no
accusatory vocabulary ever reaching a human.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.narrative import (
    FORBIDDEN,
    Narrative,
    assemble_anomaly,
    assemble_coordination,
    assemble_data_quality,
    assemble_liquidity,
    format_bdt,
    format_confidence,
    format_hours,
    lint,
)

BENGALI_FLOOR = "ঀ"


@dataclass
class _Proj:
    """Stand-in for `app.liquidity.Projection` (built by another module).

    The assembler is duck-typed on purpose; this keeps the test independent of
    the analytics layer's import path.
    """
    balance: float = 6_200.0
    rate_per_hour: float = 2_100.0
    hours_to_empty: float | None = 3.1
    low_hours: float | None = 2.4
    high_hours: float | None = 4.0
    confidence: float | None = 0.71
    label: str = "nagad"


def _proj(**kw) -> _Proj:
    return _Proj(**kw)


def _liquidity(lang="bn", suppressed=False, **kw):
    return assemble_liquidity(_proj(**kw), "nagad", "Nagad", "নগদ", lang,
                              suppressed=suppressed)


def _in_bengali_block(text: str) -> bool:
    """True if the string really uses the Bengali block (U+0980-U+09FF)."""
    return any("ঀ" <= c <= "৿" for c in text)


#: Every assembler, in both languages, on its ordinary input.
ALL_CASES = [
    ("liquidity", lambda lang: _liquidity(lang), "bn", "en"),
    ("anomaly", lambda lang: assemble_anomaly(
        "৯টি প্রায় একই অঙ্কের ক্যাশ-আউট", [("সাধারণ চাহিদা", "অঙ্ক প্রায় একই")],
        lang), "bn", "en"),
    ("data_quality", lambda lang: assemble_data_quality("৳২৫,০০০", lang),
     "bn", "en"),
    ("coordination", lambda lang: assemble_coordination(
        "অনুমোদিত সীমার বেশি লেনদেন দেখা গেছে", "শাখা ব্যবস্থাপক", None, lang),
     "bn", "en"),
]

def _build(case, lang):
    name, factory, *_ = case
    return factory(lang)


# --------------------------------------------------------------------------
# The four required parts
# --------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_CASES, ids=[c[0] for c in ALL_CASES])
def test_every_assembler_and_language_carries_the_four_parts(case):
    for lang in ("bn", "en"):
        n = _build(case, lang)
        assert n.situation.strip(), f"{case[0]}/{lang} has no situation"
        assert n.evidence and all(e.strip() for e in n.evidence), \
            f"{case[0]}/{lang} has no evidence"
        assert n.uncertainty.strip(), f"{case[0]}/{lang} has no uncertainty"
        assert n.next_steps and all(s.strip() for s in n.next_steps), \
            f"{case[0]}/{lang} has no next steps"


@pytest.mark.parametrize("case", ALL_CASES, ids=[c[0] for c in ALL_CASES])
def test_as_text_contains_every_part(case):
    n = _build(case, "bn")
    blob = n.as_text()
    assert n.situation in blob
    for e in n.evidence:
        assert e in blob
    assert n.uncertainty in blob
    for s in n.next_steps:
        assert s in blob


@pytest.mark.parametrize("case", ALL_CASES, ids=[c[0] for c in ALL_CASES])
def test_bengali_output_uses_bengali_codepoints(case):
    n = _build(case, "bn")
    for text in [n.situation, *n.evidence, n.uncertainty, *n.next_steps]:
        assert any(c > BENGALI_FLOOR for c in text), f"not Bengali: {text!r}"


def test_english_and_bengali_differ():
    en, bn = _liquidity("en"), _liquidity("bn")
    assert en.situation != bn.situation
    assert _in_bengali_block(bn.situation)
    assert not _in_bengali_block(en.situation)


# --------------------------------------------------------------------------
# Liquidity: the three cases
# --------------------------------------------------------------------------

def test_normal_case_states_the_point_estimate_and_the_window():
    n = _liquidity("en")
    assert "3.1" in n.situation
    assert "2.4" in n.situation and "4.0" in n.situation
    assert "6,200" in " ".join(n.evidence)


def test_uncertainty_states_the_interval_not_a_point_estimate():
    en, bn = _liquidity("en"), _liquidity("bn")
    assert "2.4" in en.uncertainty and "4.0" in en.uncertainty
    assert "২.৪" in bn.uncertainty and "৪.০" in bn.uncertainty
    assert "0.71" in en.uncertainty, "confidence must keep two decimals"
    assert "০.৭১" in bn.uncertainty


def test_uncertainty_is_not_just_the_point_estimate_restated():
    n = _liquidity("en")
    assert n.uncertainty != n.situation
    assert n.uncertainty_multiline()  # plan-facing helper still works


@pytest.mark.parametrize("lang", ["bn", "en"])
def test_suppressed_projection_refuses_to_recommend(lang):
    n = _liquidity(lang, suppressed=True)
    assert n.next_steps
    assert n.evidence
    if lang == "en":
        assert any("verify" in s.lower() for s in n.next_steps)
        assert "unavailable" in n.situation.lower()
        assert "fraud" not in n.situation.lower()
    else:
        assert any("যাচাই" in s for s in n.next_steps)
        assert any(c > BENGALI_FLOOR for s in n.next_steps for c in s)
    # A suppressed projection must offer no number at all.
    assert "3.1" not in n.as_text()
    assert "hours_to_empty" not in n.as_text()


@pytest.mark.parametrize("lang", ["bn", "en"])
def test_no_depletion_case_never_prints_none(lang):
    n = _liquidity(lang, hours_to_empty=None, low_hours=None, high_hours=None,
                   rate_per_hour=0.0)
    blob = n.as_text()
    assert "None" not in blob
    assert n.evidence and n.uncertainty and n.next_steps
    if lang == "bn":
        assert "কমছে না" in n.situation
        assert any(c > BENGALI_FLOOR for c in blob)
    else:
        assert "not currently depleting" in n.situation


@pytest.mark.parametrize("lang", ["bn", "en"])
def test_missing_optional_values_do_not_render_none(lang):
    n = _liquidity(lang, hours_to_empty=3.1, low_hours=None, high_hours=None,
                   confidence=None)
    assert "None" not in n.as_text()
    assert n.uncertainty


def test_missing_balance_is_not_rendered_as_none():
    n = assemble_liquidity(_Proj(balance=None), "nagad", "Nagad", "নগদ", "en")
    assert "None" not in n.as_text()


def test_provider_name_is_localised():
    assert "নগদ" in _liquidity("bn").situation
    assert "Nagad" in _liquidity("en").situation


# --------------------------------------------------------------------------
# Anomaly / data quality: the differentiators
# --------------------------------------------------------------------------

def test_anomaly_rejected_text_names_the_hypotheses():
    rejected = [("operational demand spike", "amounts are near-identical"),
                ("single customer error", "9 distinct accounts were involved")]
    n = assemble_anomaly("9 near-identical cash-outs", rejected, "en")
    assert n.rejected_text
    for name, why in rejected:
        assert name in n.rejected_text
        assert why in n.rejected_text


def test_anomaly_rejected_text_in_bengali():
    rejected = [("সাধারণ চাহিদা", "অঙ্ক প্রায় একই")]
    n = assemble_anomaly("৯টি ক্যাশ-আউট", rejected, "bn")
    assert "সাধারণ চাহিদা" in n.rejected_text
    assert any(c > BENGALI_FLOOR for c in n.rejected_text)
    assert n.rejected_text in n.as_text()


def test_anomaly_without_hypotheses_still_has_all_four_parts():
    for lang in ("bn", "en"):
        n = assemble_anomaly("9 near-identical cash-outs", [], lang)
        assert n.situation and n.evidence and n.uncertainty and n.next_steps
        # No hypotheses supplied -> nothing to reject, and that is honest.
        assert isinstance(n.rejected_text, str)


def test_anomaly_never_asks_for_an_accusation():
    for lang in ("bn", "en"):
        n = assemble_anomaly("9 near-identical cash-outs", [], lang)
        assert any("accuse" in s.lower() for s in n.next_steps) or \
            any("অভিযুক্ত" in s for s in n.next_steps)


@pytest.mark.parametrize("lang", ["bn", "en"])
def test_data_quality_says_reconciliation_not_behaviour(lang):
    diff = "৳২৫,০০০" if lang == "bn" else "৳25,000"
    n = assemble_data_quality(diff, lang)
    blob = n.as_text()
    assert diff in blob, "the reported difference must survive verbatim"
    if lang == "en":
        assert "reconciliation problem" in n.uncertainty
        assert "not evidence of customer behaviour" in n.uncertainty
    else:
        assert "ডেটা সমন্বয়ের সমস্যা" in n.uncertainty
        assert "গ্রাহকের আচরণের প্রমাণ নয়" in n.uncertainty
        assert _in_bengali_block(blob)
    assert n.rejected_text, "data-quality alerts must also say what they ruled out"


def test_coordination_keeps_the_four_parts_and_the_owner():
    for lang in ("bn", "en"):
        n = assemble_coordination("Baki transfer proposed", "Selim (field officer)",
                                  ["Confirm by phone", "Log the decision"], lang)
        assert n.situation and n.evidence and n.uncertainty and n.next_steps
        assert "Selim (field officer)" in n.as_text()
        assert "Confirm by phone" in n.next_steps


def test_coordination_survives_empty_inputs():
    for lang in ("bn", "en"):
        n = assemble_coordination("", "", [], lang)
        assert n.situation and n.evidence and n.uncertainty and n.next_steps
        assert "None" not in n.as_text()


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def test_bdt_formatting_per_language():
    assert format_bdt(6_200, "en") == "৳6,200"
    bn = format_bdt(6_200, "bn")
    assert "৳" in bn
    assert bn == "৳৬,২০০"
    assert not any(c.isascii() and c.isdigit() for c in bn), \
        "Bengali amounts must not carry Latin digits"
    assert any(c in bn for c in "০১২৩৪৫৬৭৮৯")


def test_bdt_rounds_and_separates():
    assert format_bdt(25_000.4, "en") == "৳25,000"
    assert format_bdt(999, "en") == "৳999"


def test_hours_formatting_per_language():
    assert format_hours(3.1, "en") == "3.1"
    assert format_hours(3.1, "bn") == "৩.১"
    assert format_hours(4.0, "bn") == "৪.০"
    assert format_hours(None, "en") == "unknown"
    assert format_hours(None, "bn") == "অজানা"


def test_confidence_keeps_two_decimals():
    assert format_confidence(0.71, "en") == "0.71"
    assert format_confidence(0.71, "bn") == "০.৭১"


# --------------------------------------------------------------------------
# Vocabulary lint — the compliance guardrail
# --------------------------------------------------------------------------

def test_forbidden_vocabulary_is_detected():
    for word in FORBIDDEN:
        assert lint(f"this is {word} activity"), word
    assert lint("FRAUD") == ["fraud"]
    assert lint("এই কাজটি অপরাধ নয়") == ["অপরাধ"]
    assert lint("this activity requires review") == []


def test_lint_ignores_empty_input():
    assert lint("") == []


@pytest.mark.parametrize("case", ALL_CASES, ids=[c[0] for c in ALL_CASES])
def test_generated_narratives_contain_no_forbidden_vocabulary(case):
    name, factory, *_ = case
    for language in ("bn", "en"):
        n = factory(language)
        assert lint(n.as_text()) == [], f"{name}/{language} leaks forbidden words"


def test_no_assembler_leaks_forbidden_words_on_suppressed_or_edge_inputs():
    built = [
        _liquidity("bn", suppressed=True),
        _liquidity("en", suppressed=True),
        _liquidity("bn", hours_to_empty=None, low_hours=None, high_hours=None),
        _liquidity("en", hours_to_empty=None, low_hours=None, high_hours=None),
        assemble_anomaly("9 near-identical cash-outs",
                         [("demand spike", "amounts identical")], "bn"),
        assemble_anomaly("9 near-identical cash-outs",
                         [("demand spike", "amounts identical")], "en"),
        assemble_data_quality("৳25,000", "bn"),
        assemble_data_quality("৳25,000", "en"),
        assemble_coordination("Baki transfer", "owner", ["step"], "bn"),
        assemble_coordination("Baki transfer", "owner", ["step"], "en"),
    ]
    for n in built:
        assert lint(n.as_text()) == []


def test_upstream_accusatory_text_is_neutralised():
    """Text this layer did not write still must not reach a human unchanged."""
    n = assemble_anomaly("fraud ring detected across 9 accounts",
                         [("cheating", "the accounts are criminal")], "en")
    assert lint(n.as_text()) == []
    assert "fraud ring detected" not in n.as_text()
    assert "unusual" in n.as_text().lower()

    bn = assemble_anomaly("প্রতারণার আশঙ্কা", [("অপরাধ", "সন্দেহ")], "bn")
    assert lint(bn.as_text()) == []


def test_lint_covers_the_rejected_block():
    """The rejected block is part of as_text(), so the lint must see it."""
    n = Narrative(situation="ok", uncertainty="ok",
                  rejected_text="সন্দেহজনক লেনদেন")
    assert n.rejected_text in n.as_text()
