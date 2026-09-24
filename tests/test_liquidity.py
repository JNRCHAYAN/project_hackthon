"""Liquidity projection tests, weighted toward the ways it can lie.

A projection is the number the dashboard puts a clock on, so the failure modes
that matter are the ones that would render confidently wrong: a division by a
zero drain rate, a negative duration for a balance that is already gone, a
window that silently includes the future. Each of those is pinned here, along
with the robustness property the whole estimator exists for — surviving one
outsized transaction in an otherwise ordinary afternoon.
"""
import math

import pytest

from app.domain import (
    FeedStatus, Outlet, OutletState, ProviderPosition, Transaction, TxnType,
)
from app.quality import CONFIDENCE_MULTIPLIER
from app.liquidity import (
    EPS, apply_demand, project_balance, project_outlet, theil_sen,
    worst_projection,
)

NOW = 1_767_000_000.0
BASE_HOURS = NOW / 3600.0


def _txn(ts, kind, amount, provider_id="nagad", txn_id=None):
    return Transaction(id=txn_id or f"t-{ts}-{amount}", outlet_id="AG-1000",
                       provider_id=provider_id, ts=ts, type=kind,
                       amount=amount, status="success", sender_hash="h0001",
                       balance_after=0.0)


def _state(transactions=(), cash=50_000.0, positions=None):
    outlet = Outlet(id="AG-1000", name="Outlet 1000", area="Sylhet",
                    thana="Zindabazar", district="Sylhet")
    return OutletState(
        outlet=outlet, cash=cash, cash_opening=cash,
        positions=positions if positions is not None
        else {"nagad": ProviderPosition("nagad", 30_000.0, 30_000.0, NOW - 30)},
        transactions=list(transactions))


def _points(values, step_hours=1.0):
    """A hand-built series, so the fit is tested against known arithmetic."""
    return [(i * step_hours, value) for i, value in enumerate(values)]


def _least_squares_slope(points):
    """The non-robust alternative, used only to show the outlier does bite."""
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    return numerator / denominator


# --- zero and near-zero drain -----------------------------------------------

def test_a_flat_series_projects_no_depletion_rather_than_infinity():
    projection = project_balance("cash", 50_000.0, _points([50_000.0] * 6))
    assert projection.hours_to_empty is None
    assert projection.low_hours is None
    assert projection.high_hours is None
    assert projection.exhausted is False
    assert projection.rate_per_hour == 0.0


def test_a_near_zero_drain_still_reports_no_depletion():
    """A drift below the estimator's epsilon is not a countdown."""
    series = _points([50_000.0, 50_000.0 + EPS / 4, 50_000.0,
                      50_000.0 + EPS / 4])
    projection = project_balance("cash", 50_000.0, series)
    assert projection.hours_to_empty is None
    assert projection.hours_to_empty != 0.0


def test_a_rising_balance_reports_no_depletion():
    projection = project_balance("nagad", 53_000.0,
                                 _points([50_000.0, 51_000.0, 52_000.0,
                                          53_000.0]))
    assert projection.hours_to_empty is None
    assert projection.exhausted is False
    # "Not depleting" is a finding, not a missing value: it carries its own
    # confidence, and it still never renders a horizon.
    assert projection.confidence > 0.0


def test_no_depletion_is_never_rendered_as_a_number():
    for values in ([50_000.0] * 5, [10.0, 20.0, 30.0, 40.0]):
        projection = project_balance("cash", 1_000.0, _points(values))
        assert projection.hours_to_empty is None
        assert not math.isinf(projection.rate_per_hour)
        assert math.isfinite(projection.confidence)


def test_a_flat_series_does_not_raise_zero_division():
    """The guard, stated as the bug it prevents."""
    projection = project_balance("cash", 10_000.0, _points([10_000.0] * 3))
    assert projection.hours_to_empty is None


# --- already exhausted ------------------------------------------------------

@pytest.mark.parametrize("balance", [0.0, -1.0, -250_000.0])
def test_an_exhausted_balance_reports_zero_hours_and_never_a_negative_one(balance):
    projection = project_balance("nagad", balance,
                                 _points([10_000.0, 8_000.0, 6_000.0]))
    assert projection.exhausted is True
    assert projection.hours_to_empty == 0.0
    assert projection.hours_to_empty >= 0.0
    assert projection.low_hours == 0.0
    assert projection.high_hours == 0.0
    assert projection.rate_per_hour == 0.0


def test_an_exhausted_balance_keeps_a_usable_confidence():
    """The UI still has to render it; a dead surface helps nobody."""
    projection = project_balance("nagad", 0.0, _points([1.0, 0.0]))
    assert 0.05 <= projection.confidence <= 1.0


def test_an_exhausted_balance_stays_exhausted_under_a_damped_multiplier():
    projection = project_balance("nagad", -10.0, _points([1.0, 0.0]), 0.3)
    assert projection.exhausted is True
    assert projection.hours_to_empty == 0.0
    assert projection.confidence == pytest.approx(max(0.05, 0.9 * 0.3))


def test_an_outlet_with_an_exhausted_drawer_still_projects_every_track():
    state = _state(cash=0.0)
    by_label = {p.label: p for p in project_outlet(state, NOW)}
    assert by_label["cash"].exhausted is True
    assert by_label["cash"].hours_to_empty == 0.0
    assert "nagad" in by_label


# --- history hygiene: ordering and the future -------------------------------

def test_project_balance_sorts_an_out_of_order_series():
    ordered = _points([10_000.0, 9_000.0, 8_000.0, 7_000.0])
    shuffled = [ordered[2], ordered[0], ordered[3], ordered[1]]
    assert project_balance("cash", 7_000.0, shuffled).rate_per_hour == \
        pytest.approx(project_balance("cash", 7_000.0, ordered).rate_per_hour)


def test_points_after_now_are_excluded_from_the_fit():
    ordered = _points([10_000.0, 9_000.0, 8_000.0, 7_000.0])
    future = [(4.0, 90_000.0)]        # a wildly different balance, in the future
    with_future = project_balance("cash", 7_000.0, ordered + future,
                                 now_hours=3.0)
    assert with_future.points_used == 4
    assert with_future.hours_to_empty == pytest.approx(
        project_balance("cash", 7_000.0, ordered, now_hours=3.0).hours_to_empty)


def test_project_outlet_ignores_future_dated_and_shuffled_transactions():
    """The same world, presented in a hostile order, must project the same."""
    ordered = [_txn(NOW - 3600 + i * 300, TxnType.CASH_IN, 2_000.0,
                    txn_id=f"o-{i}") for i in range(6)]
    hostile = [_txn(NOW + 5_000, TxnType.CASH_IN, 999_999.0, txn_id="future"),
               ordered[3], ordered[0], ordered[5], ordered[1], ordered[4],
               ordered[2]]

    clean = project_outlet(_state(ordered), NOW)
    messy = project_outlet(_state(hostile), NOW)
    assert [p.label for p in clean] == [p.label for p in messy]
    for expected, actual in zip(clean, messy):
        assert actual.points_used == expected.points_used
        assert actual.rate_per_hour == pytest.approx(expected.rate_per_hour)
        assert actual.hours_to_empty == pytest.approx(expected.hours_to_empty)


def test_transactions_outside_the_trailing_window_are_excluded():
    """A stale history must not dilute the current rate."""
    recent = [_txn(NOW - 600 + i * 60, TxnType.CASH_IN, 2_000.0,
                   txn_id=f"r-{i}") for i in range(6)]
    ancient = [_txn(NOW - 30_000 + i * 60, TxnType.CASH_IN, 5_000.0,
                    txn_id=f"a-{i}") for i in range(6)]
    projection = {p.label: p for p in project_outlet(_state(recent + ancient),
                                                     NOW)}["nagad"]
    assert projection.points_used == 6


# --- an outlet with nothing to project --------------------------------------

def test_an_outlet_with_no_transactions_at_all_does_not_crash():
    projections = project_outlet(_state(), NOW)
    assert {p.label for p in projections} == {"cash", "nagad"}
    for projection in projections:
        assert projection.hours_to_empty is None
        assert projection.points_used == 1
        assert math.isfinite(projection.confidence)


def test_an_outlet_with_no_provider_positions_projects_only_its_drawer():
    projections = project_outlet(_state(positions={}), NOW)
    assert [p.label for p in projections] == ["cash"]


def test_insufficient_history_earns_low_confidence_rather_than_a_guess():
    one_point = project_balance("cash", 10_000.0, [(BASE_HOURS, 10_000.0)])
    two_points = project_balance("cash", 10_000.0, _points([10_000.0, 9_000.0]))
    assert one_point.hours_to_empty is None
    assert one_point.confidence < two_points.confidence


# --- robust fitting ---------------------------------------------------------

def test_theil_sen_recovers_a_clean_slope_exactly():
    fit = theil_sen(_points([10_000.0, 9_000.0, 8_000.0, 7_000.0, 6_000.0]))
    assert fit.slope == pytest.approx(-1_000.0)
    assert fit.low == pytest.approx(-1_000.0)
    assert fit.high == pytest.approx(-1_000.0)
    assert fit.n == 5


def test_theil_sen_resists_a_single_large_outlier():
    """The reason this estimator was chosen over least squares.

    An Eid afternoon contains single transactions big enough to invert a naive
    slope. The median of pairwise slopes must not be one of them.
    """
    clean = _points([100_000.0, 99_000.0, 98_000.0, 97_000.0, 96_000.0,
                     95_000.0])
    outlier = clean + [(1.5, 900_000.0)]

    robust = theil_sen(outlier).slope
    naive = _least_squares_slope(outlier)

    assert theil_sen(clean).slope == pytest.approx(-1_000.0)
    assert robust == pytest.approx(-1_000.0), "the outlier moved the robust fit"
    # Proof the outlier is a real threat to the naive alternative: it drags the
    # least-squares slope tens of thousands of units away from the truth.
    assert abs(naive - (-1_000.0)) > 10_000.0


def test_theil_sen_survives_an_outlier_and_keeps_its_interval():
    clean = _points([10_000.0, 9_000.0, 8_000.0, 7_000.0])
    spiked = theil_sen(clean + [(2.0, 500_000.0)])
    assert spiked.low <= spiked.slope <= spiked.high
    assert spiked.slope == pytest.approx(-1_000.0)


def test_theil_sen_needs_two_points():
    fit = theil_sen([(1.0, 500.0)])
    assert (fit.slope, fit.n, fit.residual_scale) == (0.0, 1, 0.0)


def test_a_single_outlier_transaction_does_not_destroy_the_projection():
    """The same property, one level up: an outlier must not shorten the clock."""
    ordinary = [_txn(NOW - 3_600 + i * 300, TxnType.CASH_IN, 1_000.0,
                     txn_id=f"n-{i}") for i in range(8)]
    shocking = ordinary + [_txn(NOW - 120, TxnType.CASH_IN, 400_000.0,
                                txn_id="shock")]
    plain = {p.label: p for p in project_outlet(_state(ordinary), NOW)}["nagad"]
    spiked = {p.label: p for p in project_outlet(_state(shocking), NOW)}["nagad"]
    assert spiked.hours_to_empty == pytest.approx(plain.hours_to_empty,
                                                  rel=0.01)


# --- confidence -------------------------------------------------------------

def test_a_sufficiently_long_window_earns_more_confidence():
    short = project_balance("cash", 10_000.0,
                            _points([10_000.0 - 500 * i for i in range(4)]))
    long = project_balance("cash", 90_000.0,
                           _points([90_000.0 - 500 * i for i in range(30)]))
    assert long.confidence > short.confidence
    assert long.confidence <= 0.98


def test_the_confidence_multiplier_actually_damps_confidence():
    series = _points([10_000.0 - 500 * i for i in range(8)])
    full = project_balance("nagad", 6_000.0, series, 1.0)
    damped = project_balance("nagad", 6_000.0, series, 0.5)
    assert damped.confidence == pytest.approx(full.confidence * 0.5,
                                             rel=1e-6)
    assert damped.confidence < full.confidence
    # The damping must not touch the estimate itself, only trust in it.
    assert damped.hours_to_empty == pytest.approx(full.hours_to_empty)


def test_confidence_never_falls_through_the_floor():
    projection = project_balance("nagad", 6_000.0, [(1.0, 6_000.0)],
                                 0.0)
    assert projection.confidence == pytest.approx(0.05)


def test_a_worse_feed_state_lowers_the_projected_confidence():
    """The quality layer's ladder must reach the projection, not stop at it."""
    txns = [_txn(NOW - 3_600 + i * 300, TxnType.CASH_IN, 1_000.0,
                 txn_id=f"n-{i}") for i in range(8)]
    fresh, stale = {}, {}
    for status, bucket in ((FeedStatus.FRESH, fresh), (FeedStatus.STALE, stale)):
        positions = {"nagad": ProviderPosition("nagad", 20_000.0, 20_000.0,
                                               NOW - 60, feed_status=status)}
        bucket["p"] = {p.label: p for p in
                       project_outlet(_state(txns, positions=positions),
                                      NOW)}["nagad"]

    assert fresh["p"].hours_to_empty == pytest.approx(stale["p"].hours_to_empty)
    assert stale["p"].confidence == pytest.approx(
        fresh["p"].confidence * CONFIDENCE_MULTIPLIER[FeedStatus.STALE],
        rel=1e-6)


def test_the_confidence_multiplier_is_read_from_the_quality_ladder():
    """Pinned so a change to either module is caught here."""
    from app.liquidity import _confidence_multiplier
    for status, multiplier in CONFIDENCE_MULTIPLIER.items():
        assert _confidence_multiplier(status) == multiplier


# --- what-if -----------------------------------------------------------------

def test_apply_demand_shortens_the_horizon_inversely():
    projection = project_balance("cash", 10_000.0,
                                 _points([10_000.0 - 1_000 * i
                                          for i in range(6)]))
    raised = apply_demand(projection, 2.0)
    assert raised.hours_to_empty == pytest.approx(
        projection.hours_to_empty / 2.0)
    assert raised.low_hours == pytest.approx(projection.low_hours / 2.0)
    assert raised.high_hours == pytest.approx(projection.high_hours / 2.0)


def test_apply_demand_preserves_confidence():
    """Raising demand does not make the estimate any better."""
    projection = project_balance("cash", 10_000.0,
                                 _points([10_000.0 - 1_000 * i
                                          for i in range(6)]))
    assert apply_demand(projection, 3.0).confidence == projection.confidence


def test_apply_demand_is_a_no_op_at_the_identity_multiplier():
    projection = project_balance("cash", 10_000.0,
                                 _points([10_000.0 - 1_000 * i
                                          for i in range(6)]))
    assert apply_demand(projection, 1.0) == projection


def test_apply_demand_leaves_a_non_depleting_projection_alone():
    flat = project_balance("cash", 10_000.0, _points([10_000.0] * 4))
    assert apply_demand(flat, 2.5).hours_to_empty is None


def test_project_outlet_applies_the_demand_multiplier():
    txns = [_txn(NOW - 3_600 + i * 300, TxnType.CASH_IN, 1_000.0,
                 txn_id=f"n-{i}") for i in range(8)]
    plain = {p.label: p for p in project_outlet(_state(txns), NOW)}["nagad"]
    doubled = {p.label: p for p in
               project_outlet(_state(txns), NOW, 2.0)}["nagad"]
    assert doubled.hours_to_empty == pytest.approx(
        plain.hours_to_empty / 2.0)


# --- choosing the balance that matters --------------------------------------

def test_worst_projection_picks_the_soonest_exhaustion():
    soon = project_balance("nagad", 1_000.0,
                           _points([10_000.0 - 2_000 * i for i in range(6)]))
    later = project_balance("cash", 50_000.0,
                            _points([50_000.0 - 1_000 * i for i in range(6)]))
    flat = project_balance("rocket", 9_000.0, _points([9_000.0] * 4))
    assert worst_projection([later, flat, soon]).label == "nagad"


def test_worst_projection_is_none_when_nothing_is_depleting():
    flat = project_balance("cash", 9_000.0, _points([9_000.0] * 4))
    rising = project_balance("nagad", 9_000.0,
                             _points([8_000.0, 9_000.0, 10_000.0]))
    assert worst_projection([flat, rising]) is None
    assert worst_projection([]) is None


def test_worst_projection_ignores_an_already_exhausted_balance():
    """It is not 'soonest' — it has already happened, and the alert path
    handles it separately with a zero-hour horizon."""
    gone = project_balance("nagad", 0.0, _points([1_000.0, 0.0]))
    soon = project_balance("cash", 1_000.0,
                           _points([10_000.0 - 2_000 * i for i in range(6)]))
    assert worst_projection([gone, soon]).label == "cash"
