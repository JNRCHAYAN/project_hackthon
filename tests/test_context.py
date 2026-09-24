"""Context classification tests — the three-way verdict and its reasoning.

The claim this module makes is not "here is a risk score" but "here is what we
decided, and here is what we ruled out". So the tests check the decision *and*
the rejection list: an alert that names no rejected hypothesis is not
explainable, and an unexplainable alert is the thing this layer exists to
prevent.

The two shapes that must not be confused are a burst and an Eid afternoon.
They differ only in how many accounts are involved and how wide the amount
range is, which is exactly why both are pinned here with the same velocity.
"""
import datetime as dt

import pytest

from app.anomaly import AnomalySignal, scan
from app.config import SETTINGS
from app.context import (
    EID_WINDOWS, bn_num, calendar_context, classify, verdict_to_alert_fields,
)
from app.domain import Classification
from app.simulator import Simulator

FLOOR = SETTINGS["demand_spike_account_floor"]
NARROW = SETTINGS["narrow_spread_ratio"]


def _signal(accounts=4, amounts=(9_850.0, 9_900.0, 9_950.0, 9_900.0, 9_900.0,
                                 9_900.0),
            kind="burst_identical", provider_id="bkash"):
    return AnomalySignal(
        kind=kind, provider_id=provider_id,
        accounts=[f"h9{i:03d}" for i in range(accounts)], amounts=list(amounts),
        window_minutes=12, magnitude=float(len(amounts)),
        evidence=["9 transactions within ±2% of ৳9,900 in 12 minutes",
                  "originating from only 4 distinct accounts",
                  "combined value ৳89,100"])


def _surge(accounts=14):
    """A legitimate Eid surge: many accounts, amounts all over the place."""
    amounts = [500.0, 900.0, 1_500.0, 2_500.0, 4_000.0, 8_000.0, 1_200.0,
               3_300.0, 6_000.0, 700.0, 5_100.0, 4_400.0, 2_100.0, 6_600.0]
    return _signal(accounts=accounts, amounts=amounts[:accounts])


def _ts(year, month, day, hour=12):
    return dt.datetime(year, month, day, hour,
                       tzinfo=dt.timezone.utc).timestamp()


# --- the calendar -----------------------------------------------------------

def test_the_eid_window_is_recognised_from_the_clock():
    start, end = EID_WINDOWS[0]
    assert calendar_context(start) == "eid_window"
    assert calendar_context(end) == "eid_window"
    assert calendar_context((start + end) / 2) == "eid_window"


def test_dates_at_the_edge_of_the_eid_window_are_not_in_it():
    start, end = EID_WINDOWS[0]
    assert calendar_context(start - 1) != "eid_window"
    assert calendar_context(end + 1) != "eid_window"


def test_the_first_days_of_a_month_are_salary_days():
    assert calendar_context(_ts(2026, 1, 5)) == "salary_day"


def test_salary_days_outrank_the_weekend():
    """Day 1 is a salary day even when it also lands on a Friday."""
    assert calendar_context(_ts(2026, 1, 2)) == "salary_day"


def test_the_weekend_market_peak_is_recognised():
    assert calendar_context(_ts(2026, 1, 9)) == "market_day"     # Friday
    assert calendar_context(_ts(2026, 1, 10)) == "market_day"    # Saturday


def test_an_ordinary_weekday_is_ordinary():
    assert calendar_context(_ts(2026, 1, 14)) == "ordinary"


def test_calendar_context_is_evaluated_in_utc():
    """The same instant reads the same way from any machine timezone."""
    ts = _ts(2026, 1, 14, hour=23)
    assert calendar_context(ts) == "ordinary"


# --- the three-way verdict --------------------------------------------------

def test_a_burst_with_near_identical_amounts_needs_review():
    verdict = classify(_signal(), [], "ordinary")
    assert verdict.classification is Classification.NEEDS_REVIEW
    assert verdict.priority == "high"
    assert verdict.confidence > 0.0
    assert verdict.accepted == "pattern requiring human review"
    assert verdict.accepted_bn


def test_a_diverse_wide_surge_during_eid_is_a_legitimate_demand_spike():
    """The differentiator: same chart shape as a burst, correct answer is none."""
    verdict = classify(_surge(), [], "eid_window")
    assert verdict.classification is Classification.DEMAND_SPIKE
    assert verdict.priority == "low"
    assert "eid window" in verdict.accepted
    assert verdict.rationale


def test_a_diverse_wide_surge_is_a_spike_without_a_calendar_reason_too():
    """Broad demand on an ordinary day is still broad demand."""
    verdict = classify(_surge(), [], "ordinary")
    assert verdict.classification is Classification.DEMAND_SPIKE
    assert "eid" not in verdict.accepted


@pytest.mark.parametrize("ctx", ["ordinary", "eid_window", "salary_day",
                                 "market_day"])
def test_the_surge_thresholds_are_what_separate_spike_from_review(ctx):
    assert classify(_surge(), [], ctx).classification is \
        Classification.DEMAND_SPIKE
    assert classify(_signal(), [], ctx).classification is \
        Classification.NEEDS_REVIEW


def test_a_narrow_month_end_surge_still_needs_review():
    """A salary day is context, not a licence to ignore the pattern."""
    verdict = classify(_signal(), [], "salary_day")
    assert verdict.classification is Classification.NEEDS_REVIEW
    assert any("salary day" in reason
               for _, reason in verdict.rejected_hypotheses)


def test_just_below_the_account_floor_is_not_a_demand_spike():
    verdict = classify(_signal(accounts=FLOOR - 1), [], "eid_window")
    assert verdict.classification is Classification.NEEDS_REVIEW

    at_floor = classify(_surge(accounts=FLOOR), [], "eid_window")
    assert at_floor.classification is Classification.DEMAND_SPIKE


def test_a_narrow_spread_is_not_a_demand_spike():
    """Many accounts but identical amounts is not ordinary demand either."""
    verdict = classify(_signal(accounts=FLOOR + 2), [], "eid_window")
    assert verdict.classification is Classification.NEEDS_REVIEW


def test_a_balance_chain_fault_is_classified_as_data_quality():
    verdict = classify(_signal(kind="balance_chain"), [], "ordinary")
    assert verdict.classification is Classification.DATA_QUALITY
    assert verdict.priority == "medium"
    assert "data-quality problem" in verdict.accepted
    assert verdict.accepted_bn


def test_a_data_quality_fault_is_never_classified_as_suspicion():
    """A feed problem must not cost anybody an explanation."""
    verdict = classify(_signal(kind="balance_chain"), [], "eid_window")
    assert verdict.classification is Classification.DATA_QUALITY
    assert verdict.classification is not Classification.NEEDS_REVIEW


# --- rejected hypotheses ----------------------------------------------------

def _assert_rejections_are_reasoned(verdict):
    assert len(verdict.rejected_hypotheses) >= 2, "nothing was ruled out"
    for name, reason in verdict.rejected_hypotheses:
        assert name and name.strip()
        assert reason and reason.strip()
        assert len(reason) > 20, f"rejection reason for {name!r} is not a reason"


def test_a_review_verdict_names_the_hypotheses_it_ruled_out():
    verdict = classify(_signal(), [], "ordinary")
    _assert_rejections_are_reasoned(verdict)
    names = {name for name, _ in verdict.rejected_hypotheses}
    assert names == {"operational demand spike", "data-quality problem"}


def test_a_spike_verdict_names_the_hypotheses_it_ruled_out():
    verdict = classify(_surge(), [], "eid_window")
    _assert_rejections_are_reasoned(verdict)
    names = {name for name, _ in verdict.rejected_hypotheses}
    assert names == {"pattern requiring review", "data-quality problem"}


def test_a_data_quality_verdict_names_the_hypotheses_it_ruled_out():
    verdict = classify(_signal(kind="balance_chain"), [], "ordinary")
    _assert_rejections_are_reasoned(verdict)
    names = {name for name, _ in verdict.rejected_hypotheses}
    assert "suspicious activity" in names


def test_a_ruled_out_calendar_explanation_is_named_in_the_rejection():
    """The rejection has to say *why* the season does not explain it."""
    verdict = classify(_signal(), [], "eid_window")
    reason = next(reason for name, reason in verdict.rejected_hypotheses
                  if name == "operational demand spike")
    assert "concentrated" in reason
    assert "near-identical" in reason


def test_a_rejection_on_an_ordinary_day_says_there_is_no_context():
    verdict = classify(_signal(), [], "ordinary")
    reason = next(reason for name, reason in verdict.rejected_hypotheses
                  if name == "operational demand spike")
    assert "no seasonal or salary-day context" in reason


def test_every_rejection_is_stated_in_both_languages():
    for verdict in (classify(_signal(), [], "eid_window"),
                    classify(_surge(), [], "eid_window"),
                    classify(_signal(kind="balance_chain"), [], "ordinary")):
        assert len(verdict.rejected_hypotheses_bn) == \
            len(verdict.rejected_hypotheses)
        for name, reason in verdict.rejected_hypotheses_bn:
            assert _has_bengali(name) and _has_bengali(reason)


def _has_bengali(text):
    return any("ঀ" <= ch <= "৿" for ch in text)


# --- rationale and the alert fields -----------------------------------------

def test_a_verdict_always_carries_a_rationale():
    for verdict in (classify(_signal(), [], "ordinary"),
                    classify(_surge(), [], "eid_window"),
                    classify(_signal(kind="balance_chain"), [], "ordinary")):
        assert verdict.rationale
        assert all(line.strip() for line in verdict.rationale)


def test_a_review_rationale_admits_it_is_advisory():
    verdict = classify(_signal(), [], "ordinary")
    assert any("not a determination of wrongdoing" in line
               for line in verdict.rationale)


def test_verdict_to_alert_fields_maps_both_languages():
    verdict = classify(_signal(), [], "eid_window")

    english = verdict_to_alert_fields(verdict, "en")
    assert english["classification"] is Classification.NEEDS_REVIEW
    assert english["severity"] == "high"
    assert english["reason"] == verdict.accepted
    assert english["confidence"] == verdict.confidence
    assert english["rejected_hypotheses"] == verdict.rejected_hypotheses

    bengali = verdict_to_alert_fields(verdict, "bn")
    assert bengali["reason"] == verdict.accepted_bn
    assert bengali["rejected_hypotheses"] == verdict.rejected_hypotheses_bn


def test_rejected_for_falls_back_to_english_when_bengali_is_absent():
    verdict = classify(_signal(kind="balance_chain"), [], "ordinary")
    verdict.rejected_hypotheses_bn = []
    assert verdict.rejected_for("bn") == verdict.rejected_hypotheses
    assert verdict.rejected_for("en") == verdict.rejected_hypotheses


def test_bengali_numbers_are_rendered_in_bengali_digits():
    assert bn_num(42) == "৪২"
    assert bn_num("1,234") == "১,২৩৪"


# --- against the real detector ----------------------------------------------

def test_the_planted_burst_is_classified_as_needing_review():
    """End to end, on the simulator's own injected burst."""
    sim = Simulator(seed=11, outlets=6)
    world = sim.world()
    outlet_id = sorted(world)[1]
    state = world[outlet_id]

    verdicts = [classify(signal, state.transactions,
                         calendar_context(sim.now))
                for signal in scan(state, sim.now)]
    assert verdicts, "the planted burst produced no signal at all"
    assert [v.classification for v in verdicts] == \
        [Classification.NEEDS_REVIEW]


def test_the_planted_eid_surge_never_reaches_a_review_verdict():
    """The outcome the demo depends on: high volume, and nothing to act on."""
    sim = Simulator(seed=11, outlets=6)
    world = sim.world()
    state = world[sorted(world)[2]]
    assert state.calendar_context == "eid_window"
    assert len(state.provider_txns("rocket")) >= 14, "the fixture is not busy"

    verdicts = [classify(signal, state.transactions,
                         calendar_context(sim.now))
                for signal in scan(state, sim.now)]
    assert all(v.classification is not Classification.NEEDS_REVIEW
               for v in verdicts), [v.classification for v in verdicts]
