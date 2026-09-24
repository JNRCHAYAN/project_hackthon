"""Tests for the reliability heart: feed quality and safe suppression.

Boundary values are tested from both sides throughout — "stale after 30
minutes" is only a real guarantee if exactly-30-minutes-old is still merely
delayed.
"""
import pytest

from app.domain import (
    FeedStatus, Outlet, OutletState, ProviderPosition, Transaction, TxnType,
)
from app.quality import (
    CONFIDENCE_MULTIPLIER, DELAYED_AFTER_S, MIN_RELIABILITY, STALE_AFTER_S,
    SUPPRESSION_NOTICE, SUPPRESSION_NOTICE_BN, classify_feed,
    outlet_reliability, reconcile, should_suppress,
)

FORBIDDEN_VOCABULARY = (
    "fraud", "fraudulent", "cheating", "criminal", "প্রতারণা", "অপরাধ",
)


def _txn(amount, kind=TxnType.CASH_OUT, bal=100.0, provider="nagad"):
    return Transaction(id="t", outlet_id="AG-1", provider_id=provider, ts=1.0,
                       type=kind, amount=amount, status="success",
                       sender_hash="h1", balance_after=bal)


def _position(provider_id, status, last_feed_at, balance=10_000.0):
    return ProviderPosition(
        provider_id=provider_id,
        balance=balance,
        opening_balance=balance,
        last_feed_at=last_feed_at,
        feed_status=status,
    )


def _state(positions):
    outlet = Outlet(id="AG-1", name="Outlet", area="Islampur",
                    thana="Islampur", district="Jamalpur")
    return OutletState(
        outlet=outlet,
        cash=50_000.0,
        cash_opening=50_000.0,
        positions={p.provider_id: p for p in positions},
    )


# --- Confidence propagation -------------------------------------------------

def test_multiplier_ordering_is_strictly_monotonic():
    ladder = [
        FeedStatus.FRESH, FeedStatus.DELAYED, FeedStatus.STALE,
        FeedStatus.CONFLICTING, FeedStatus.MISSING,
    ]
    multipliers = [CONFIDENCE_MULTIPLIER[s] for s in ladder]
    for better, worse in zip(multipliers, multipliers[1:]):
        assert better > worse, f"{better} !> {worse} breaks monotonicity"


def test_multiplier_covers_every_feed_status():
    assert set(CONFIDENCE_MULTIPLIER) == set(FeedStatus)


def test_fresh_is_the_identity_multiplier():
    assert CONFIDENCE_MULTIPLIER[FeedStatus.FRESH] == 1.0


def test_every_state_carries_the_documented_multiplier():
    """The published ladder itself, not merely its ordering."""
    assert CONFIDENCE_MULTIPLIER == {
        FeedStatus.FRESH: 1.0,
        FeedStatus.DELAYED: 0.8,
        FeedStatus.STALE: 0.5,
        FeedStatus.CONFLICTING: 0.3,
        FeedStatus.MISSING: 0.0,
    }


# --- Reconcile --------------------------------------------------------------

def test_reconcile_matches_manual_arithmetic():
    txns = [_txn(1000, TxnType.CASH_OUT), _txn(300, TxnType.CASH_IN)]
    assert reconcile(5_000, txns) == pytest.approx(5_000 + 1000 - 300)


def test_reconcile_uses_emoney_sign_convention():
    """Cash-out grows the provider balance; cash-in shrinks it."""
    cash_out = _txn(250, TxnType.CASH_OUT)
    cash_in = _txn(250, TxnType.CASH_IN)
    assert cash_out.emoney_delta() == 250
    assert cash_in.emoney_delta() == -250
    assert reconcile(1_000, [cash_out]) == pytest.approx(1_250)
    assert reconcile(1_000, [cash_in]) == pytest.approx(750)


def test_reconcile_with_no_transactions_is_the_opening_balance():
    assert reconcile(4_242.0, []) == pytest.approx(4_242.0)


def test_reconcile_is_order_independent():
    txns = [_txn(100), _txn(250, TxnType.CASH_IN), _txn(40)]
    assert reconcile(1_000, txns) == pytest.approx(reconcile(1_000, list(reversed(txns))))


# --- Feed status escalation -------------------------------------------------

def test_feed_status_escalates_with_lag():
    now = 1_000_000.0
    assert classify_feed(now - 30, now, 0.0) is FeedStatus.FRESH
    assert classify_feed(now - 480, now, 0.0) is FeedStatus.DELAYED
    assert classify_feed(now - 3000, now, 0.0) is FeedStatus.STALE
    assert classify_feed(None, now, 0.0) is FeedStatus.MISSING


def test_fresh_delayed_boundary_at_300_seconds():
    now = 1_000_000.0
    assert classify_feed(now - DELAYED_AFTER_S, now, 0.0) is FeedStatus.FRESH
    assert classify_feed(now - DELAYED_AFTER_S - 1, now, 0.0) is FeedStatus.DELAYED


def test_delayed_stale_boundary_at_1800_seconds():
    now = 1_000_000.0
    assert classify_feed(now - STALE_AFTER_S, now, 0.0) is FeedStatus.DELAYED
    assert classify_feed(now - STALE_AFTER_S - 1, now, 0.0) is FeedStatus.STALE


def test_no_feed_timestamp_is_missing_regardless_of_drift():
    now = 1_000_000.0
    assert classify_feed(None, now, 0.0) is FeedStatus.MISSING
    assert classify_feed(None, now, 999_999.0) is FeedStatus.MISSING


# --- Drift overrides freshness ---------------------------------------------

def test_conflicting_drift_overrides_freshness():
    assert classify_feed(1_000_000.0, 1_000_000.0, 25_000.0) is FeedStatus.CONFLICTING


def test_drift_floor_boundary():
    now = 1_000_000.0
    fresh = now - 1.0
    assert classify_feed(fresh, now, 1_000.0) is FeedStatus.FRESH
    assert classify_feed(fresh, now, 1_000.01) is FeedStatus.CONFLICTING


def test_negative_drift_conflicts_too():
    now = 1_000_000.0
    assert classify_feed(now - 1.0, now, -25_000.0) is FeedStatus.CONFLICTING


def test_drift_outranks_staleness():
    now = 1_000_000.0
    assert classify_feed(now - 90_000, now, 5_000.0) is FeedStatus.CONFLICTING


# --- Suppression ------------------------------------------------------------

def test_suppression_only_for_conflicting_or_missing():
    assert should_suppress(FeedStatus.CONFLICTING) is True
    assert should_suppress(FeedStatus.MISSING) is True
    assert should_suppress(FeedStatus.STALE) is False
    assert should_suppress(FeedStatus.DELAYED) is False
    assert should_suppress(FeedStatus.FRESH) is False


def test_suppression_notice_forbids_action():
    assert "verify" in SUPPRESSION_NOTICE.lower()


def test_suppression_notices_are_non_empty_and_mention_verification():
    assert SUPPRESSION_NOTICE.strip()
    assert SUPPRESSION_NOTICE_BN.strip()
    assert "verify" in SUPPRESSION_NOTICE.lower()
    assert "projection" in SUPPRESSION_NOTICE.lower()
    assert "যাচাই" in SUPPRESSION_NOTICE_BN


def test_suppression_notices_avoid_forbidden_vocabulary():
    haystacks = {
        "SUPPRESSION_NOTICE": SUPPRESSION_NOTICE,
        "SUPPRESSION_NOTICE_BN": SUPPRESSION_NOTICE_BN,
    }
    for label, text in haystacks.items():
        lowered = text.lower()
        for word in FORBIDDEN_VOCABULARY:
            assert word.lower() not in lowered, f"{label} contains {word!r}"


# --- Outlet reliability -----------------------------------------------------

def test_outlet_reliability_all_fresh_is_one_with_no_notes():
    now = 1_000_000.0
    state = _state([
        _position("nagad", FeedStatus.FRESH, now - 10),
        _position("bkash", FeedStatus.FRESH, now - 20),
        _position("rocket", FeedStatus.FRESH, now - 30),
    ])
    multiplier, notes = outlet_reliability(state, now)
    assert multiplier == pytest.approx(1.0)
    assert notes == []


def test_outlet_reliability_multiplies_a_degraded_mix():
    now = 1_000_000.0
    state = _state([
        _position("nagad", FeedStatus.STALE, now - 45 * 60),      # 0.5
        _position("bkash", FeedStatus.DELAYED, now - 10 * 60),    # 0.8
        _position("rocket", FeedStatus.FRESH, now - 10),          # 1.0
    ])
    multiplier, notes = outlet_reliability(state, now)
    assert multiplier == pytest.approx(0.5 * 0.8 * 1.0)
    assert len(notes) == 2
    assert "nagad: stale (45 min old)" in notes
    assert "bkash: delayed (10 min old)" in notes


def test_outlet_reliability_is_floored_for_a_dead_feed():
    now = 1_000_000.0
    state = _state([_position("nagad", FeedStatus.MISSING, None)])
    multiplier, notes = outlet_reliability(state, now)
    assert multiplier == pytest.approx(0.05)
    assert len(notes) == 1
    assert notes[0].startswith("nagad: missing (no feed)")


def test_outlet_reliability_notes_never_use_forbidden_vocabulary():
    now = 1_000_000.0
    state = _state([
        _position("nagad", FeedStatus.CONFLICTING, now - 60),
        _position("bkash", FeedStatus.MISSING, None),
        _position("rocket", FeedStatus.STALE, now - 60 * 60),
    ])
    _, notes = outlet_reliability(state, now)
    assert notes
    for note in notes:
        lowered = note.lower()
        for word in FORBIDDEN_VOCABULARY:
            assert word.lower() not in lowered, f"note contains {word!r}: {note}"


def test_outlet_reliability_of_conflicting_feed_is_heavily_discounted():
    """The headline guarantee: a contradicting feed cannot read as confident."""
    now = 1_000_000.0
    state = _state([_position("nagad", FeedStatus.CONFLICTING, now - 5)])
    multiplier, notes = outlet_reliability(state, now)
    assert multiplier <= 0.3
    assert any("verify feed" in note for note in notes)


@pytest.mark.parametrize("status", list(FeedStatus))
def test_one_degraded_feed_costs_exactly_its_documented_multiplier(status):
    """Every rung of the ladder, propagated through the outlet rollup.

    The rollup is where the multiplier stops being a table entry and starts
    being the number the dashboard prints, so each state is checked there too.
    """
    now = 1_000_000.0
    stamped = None if status is FeedStatus.MISSING else now - 600
    state = _state([_position("nagad", status, stamped)])
    multiplier, _ = outlet_reliability(state, now)
    assert multiplier == pytest.approx(
        max(MIN_RELIABILITY, CONFIDENCE_MULTIPLIER[status]))
