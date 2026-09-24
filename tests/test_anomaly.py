"""Unusual-activity detection tests.

The burden here is asymmetric. Missing a genuine burst is a real cost, but so
is flagging an ordinary busy afternoon, and a detector that only ever gets
tested on its positives will happily do the latter. So every detection test is
paired with the near-miss it must *not* fire on: high velocity without
identical amounts, identical amounts from many accounts, a burst split across
two providers so that neither track reaches the threshold alone.
"""
import pytest

from app.anomaly import (
    MIN_BURST_TXNS, account_concentration, detect_balance_drift, detect_burst,
    scan,
)
from app.config import SETTINGS
from app.domain import (
    Outlet, OutletState, ProviderPosition, Transaction, TxnType,
)

NOW = 1_767_000_000.0
BURST_AMOUNT = 9_900.0


def _txn(index, amount, account, provider_id="bkash", ts=None, kind=None,
         status="success"):
    return Transaction(
        id=f"{provider_id}-{index}", outlet_id="AG-1000",
        provider_id=provider_id, ts=NOW - 3_600 + index * 60 if ts is None else ts,
        type=TxnType.CASH_OUT if kind is None else kind, amount=amount,
        status=status, sender_hash=account, balance_after=0.0)


def _burst(count=9, amount=BURST_AMOUNT, accounts=4, provider_id="bkash",
           ts=None, kind=None):
    """Near-identical amounts from a handful of accounts, minutes apart."""
    return [
        _txn(i, amount * (1 + 0.005 * ((i % 3) - 1)), f"h9{i % accounts:03d}",
             provider_id=provider_id,
             ts=(NOW - 600 + i * 60) if ts is None else ts + i * 60,
             kind=kind)
        for i in range(count)
    ]


def _state(transactions, positions=None):
    outlet = Outlet(id="AG-1000", name="Outlet 1000", area="Sylhet",
                    thana="Zindabazar", district="Sylhet")
    return OutletState(
        outlet=outlet, cash=50_000.0, cash_opening=50_000.0,
        positions=positions if positions is not None
        else {"bkash": ProviderPosition("bkash", 10_000.0, 10_000.0, NOW - 30)},
        transactions=list(transactions))


# --- burst: what must be flagged --------------------------------------------

def test_a_near_identical_burst_from_few_accounts_is_flagged():
    signal = detect_burst(_burst())
    assert signal is not None
    assert signal.kind == "burst_identical"
    assert signal.provider_id == "bkash"
    assert signal.magnitude == pytest.approx(9.0)


def test_a_flagged_burst_carries_its_evidence():
    """An alert nobody can check is just an accusation."""
    signal = detect_burst(_burst())
    assert len(signal.accounts) == 4
    assert len(signal.amounts) == 9
    assert signal.window_minutes == SETTINGS["burst_window_minutes"]
    assert len(signal.evidence) >= 3
    assert any("distinct accounts" in line for line in signal.evidence)
    assert any("combined value" in line for line in signal.evidence)


def test_the_burst_amounts_really_are_within_tolerance():
    """Guards the fixture itself: the three conditions must all hold."""
    amounts = [t.amount for t in _burst()]
    anchor = amounts[0]
    assert max(amounts) - min(amounts) <= \
        SETTINGS["burst_amount_tolerance"] * anchor
    assert len({t.sender_hash for t in _burst()}) <= SETTINGS["burst_max_accounts"]


# --- burst: what must not be -------------------------------------------------

def test_high_velocity_from_many_accounts_is_not_a_burst():
    """A busy afternoon moves money fast; that alone is not a finding."""
    diverse = [_txn(i, BURST_AMOUNT, f"h8{i:03d}") for i in range(9)]
    assert detect_burst(diverse) is None


def test_identical_amounts_with_a_wide_spread_are_not_a_burst():
    """Near-identical amounts are the signature; a spread is ordinary demand."""
    wide = [_txn(i, 500.0 * (i + 1), f"h9{i % 4:03d}") for i in range(9)]
    assert detect_burst(wide) is None


def test_a_short_burst_below_the_minimum_is_not_flagged():
    assert detect_burst(_burst(count=MIN_BURST_TXNS - 1)) is None


def test_a_burst_spread_wider_than_the_window_is_not_flagged():
    """Same amounts, same accounts, but not at speed."""
    spaced = [_txn(i, BURST_AMOUNT, f"h9{i % 4:03d}",
                   ts=NOW - 6 * 3_600 + i * 900)        # 15 minutes apart
              for i in range(9)]
    assert detect_burst(spaced) is None


def test_a_wide_amount_range_within_few_accounts_is_not_a_burst():
    """The fourth shape: few accounts, but the sizes are all over the place."""
    varied = [_txn(i, 400.0 * (i + 1), f"h9{i % 4:03d}") for i in range(9)]
    assert detect_burst(varied) is None


def test_unsuccessful_transactions_are_ignored():
    """A failed burst is not a burst — nobody moved any money."""
    failed = [_txn(i, BURST_AMOUNT, f"h9{i % 4:03d}", status="failed")
              for i in range(9)]
    assert detect_burst(failed) is None


def test_only_successful_transactions_count_toward_a_burst():
    five = _burst(count=5)
    assert detect_burst(five) is None            # not enough on its own
    failed = [_txn(100 + i, BURST_AMOUNT, f"h9{i % 4:03d}", status="failed")
              for i in range(6)]
    assert detect_burst(five + failed) is None, \
        "failed transactions must not top up the count"
    assert detect_burst(_burst(count=9)) is not None


def test_an_empty_transaction_list_is_not_a_burst():
    assert detect_burst([]) is None


# --- provider scoping -------------------------------------------------------

def test_a_burst_split_across_providers_is_not_flagged():
    """Neither track alone shows the pattern, and tracks are never merged."""
    split = (_burst(count=4, provider_id="nagad") + _burst(count=4,
                                                           provider_id="bkash"))
    assert detect_burst(split) is None


def test_a_burst_is_scoped_to_its_own_provider():
    mixed = _burst(provider_id="bkash") + [
        _txn(200 + i, 500.0 * (i + 1), f"h7{i:03d}", provider_id="nagad")
        for i in range(9)]

    found = detect_burst(mixed)
    assert found is not None
    assert found.provider_id == "bkash"

    # The other track is asked about directly and has nothing to report.
    assert detect_burst(mixed, provider_id="nagad") is None
    assert detect_burst(mixed, provider_id="bkash") is not None


def test_an_unknown_provider_filter_finds_nothing():
    assert detect_burst(_burst(), provider_id="rocket") is None


def test_the_window_can_be_narrowed_by_the_caller():
    """A caller tightening the window must not be given a wider one's answer."""
    burst = _burst()
    assert detect_burst(burst, window_minutes=1) is None
    assert detect_burst(burst, window_minutes=SETTINGS["burst_window_minutes"])


# --- balance-chain integrity -------------------------------------------------

def test_an_unreconciled_balance_is_reported_as_a_balance_chain_fault():
    position = ProviderPosition("bkash", 125_000.0, 100_000.0, NOW - 30)
    state = _state([_txn(0, 1_000.0, "h1"), _txn(1, 2_000.0, "h2")],
                   positions={"bkash": position})

    signal = detect_balance_drift(state)
    assert signal is not None
    assert signal.kind == "balance_chain"
    assert signal.provider_id == "bkash"
    # 100,000 + 1,000 + 2,000 == 103,000 against a declared 125,000.
    assert signal.magnitude == pytest.approx(22_000.0)
    assert position.declared_drift == pytest.approx(22_000.0)
    assert any("unexplained difference" in line for line in signal.evidence)


def test_a_reconciling_chain_is_not_reported():
    position = ProviderPosition("bkash", 103_000.0, 100_000.0, NOW - 30)
    state = _state([_txn(0, 1_000.0, "h1"), _txn(1, 2_000.0, "h2")],
                   positions={"bkash": position})
    assert detect_balance_drift(state) is None
    assert position.declared_drift == 0.0


def test_a_drift_inside_the_reconcile_tolerance_is_not_reported():
    """Rounding is not a data-integrity fault."""
    position = ProviderPosition("bkash", 103_000.0 + 50.0, 100_000.0, NOW - 30)
    state = _state([_txn(0, 1_000.0, "h1"), _txn(1, 2_000.0, "h2")],
                   positions={"bkash": position})
    assert detect_balance_drift(state) is None


def test_a_provider_with_no_history_is_never_accused_of_drifting():
    """Nothing to reconcile against means nothing to report."""
    position = ProviderPosition("bkash", 999_999.0, 1.0, NOW - 30)
    state = _state([], positions={"bkash": position})
    assert detect_balance_drift(state) is None


def test_an_understated_balance_is_detected_too():
    """Drift runs both ways: 100,000 opening + 1,000 against a declared 60,000."""
    position = ProviderPosition("bkash", 60_000.0, 100_000.0, NOW - 30)
    state = _state([_txn(0, 1_000.0, "h1")], positions={"bkash": position})
    signal = detect_balance_drift(state)
    assert signal is not None
    assert signal.magnitude == pytest.approx(41_000.0)


# --- scan -------------------------------------------------------------------

def test_scan_returns_burst_then_integrity_fault():
    position = ProviderPosition("bkash", 500_000.0, 100_000.0, NOW - 30)
    state = _state(_burst(), positions={"bkash": position})
    assert [s.kind for s in scan(state, NOW)] == ["burst_identical",
                                                  "balance_chain"]


def test_scan_of_a_clean_outlet_returns_nothing():
    position = ProviderPosition("bkash", 100_000.0, 100_000.0, NOW - 30)
    assert scan(_state([], positions={"bkash": position}), NOW) == []


def test_scan_never_returns_a_signal_without_evidence():
    position = ProviderPosition("bkash", 500_000.0, 100_000.0, NOW - 30)
    state = _state(_burst(), positions={"bkash": position})
    for signal in scan(state, NOW):
        assert signal.evidence
        assert all(line.strip() for line in signal.evidence)
        assert signal.magnitude > 0


# --- account concentration --------------------------------------------------

def test_account_concentration_counts_distinct_accounts():
    stats = account_concentration(_burst())
    assert stats["accounts"] == 4
    assert stats["txns"] == 9
    assert stats["amount_spread"] == pytest.approx(0.01, abs=0.01)
    assert stats["top_share"] == pytest.approx(3 / 9)


def test_account_concentration_of_diverse_activity_is_broad():
    diverse = [_txn(i, 500.0 * (i + 1), f"h8{i:03d}") for i in range(9)]
    stats = account_concentration(diverse)
    assert stats["accounts"] == 9
    assert stats["top_share"] == pytest.approx(1 / 9)
    assert stats["amount_spread"] > SETTINGS["narrow_spread_ratio"]


def test_account_concentration_can_be_scoped_to_one_provider():
    mixed = _burst(provider_id="bkash") + _burst(count=9, provider_id="nagad",
                                                 accounts=9)
    assert account_concentration(mixed, "bkash")["accounts"] == 4
    assert account_concentration(mixed, "nagad")["accounts"] == 9


def test_account_concentration_of_nothing_is_all_zeros():
    assert account_concentration([]) == {"accounts": 0, "txns": 0,
                                        "top_share": 0.0, "amount_spread": 0.0}
