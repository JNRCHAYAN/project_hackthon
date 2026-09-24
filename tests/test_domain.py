"""Domain model tests: the sign convention and the enum values are contracts.

The cash/e-money sign convention *is* the product's core insight, and every
analytic layer reads it from here, so it is pinned at its source rather than
left to whichever module happens to use it first. The enums are a wire
contract too — they are serialised straight into the JSON the dashboard
renders, so their string values are part of the API.
"""
import dataclasses
import json

import pytest

from app.domain import (
    Alert, AlertKind, CaseStatus, Classification, FeedStatus, Outlet,
    OutletState, Provider, ProviderPosition, Severity, Transaction, TxnType,
)


def _txn(kind=TxnType.CASH_OUT, amount=1_000.0, balance_after=1_000.0,
         txn_id="t-1", provider_id="bkash"):
    return Transaction(id=txn_id, outlet_id="AG-1000",
                       provider_id=provider_id, ts=1_000.0, type=kind,
                       amount=amount, status="success", sender_hash="h0001",
                       balance_after=balance_after)


def _position(provider_id="bkash", balance=10_000.0):
    return ProviderPosition(provider_id=provider_id, balance=balance,
                            opening_balance=balance, last_feed_at=1_000.0)


def _state(**overrides):
    outlet = Outlet(id="AG-1000", name="Outlet 1000", area="Sylhet",
                    thana="Zindabazar", district="Sylhet", lat=24.8949,
                    lon=91.8687)
    fields = {
        "cash": 50_000.0,
        "cash_opening": 50_000.0,
        "positions": {"bkash": _position()},
    }
    fields.update(overrides)
    return OutletState(outlet=outlet, **fields)


# --- the sign convention ----------------------------------------------------

def test_cash_out_drains_cash_and_grows_emoney():
    """A cash-out hands cash over and takes e-money in — the whole insight."""
    txn = _txn(TxnType.CASH_OUT, 2_500.0)
    assert txn.cash_delta() == -2_500.0
    assert txn.emoney_delta() == 2_500.0


def test_cash_in_is_the_exact_opposite():
    txn = _txn(TxnType.CASH_IN, 2_500.0)
    assert txn.cash_delta() == 2_500.0
    assert txn.emoney_delta() == -2_500.0


@pytest.mark.parametrize("amount", [0.01, 1.0, 500.0, 9_900.0, 250_000.0])
@pytest.mark.parametrize("kind", [TxnType.CASH_IN, TxnType.CASH_OUT])
def test_the_two_deltas_are_always_exact_negatives(kind, amount):
    txn = _txn(kind, amount)
    assert txn.cash_delta() == -txn.emoney_delta()
    assert abs(txn.cash_delta() + txn.emoney_delta()) == 0.0


def test_the_sign_comes_from_the_type_not_from_the_amount():
    """Directionality is decided by the transaction type, never the magnitude."""
    for amount in (0.0, 0.01, -500.0):
        assert _txn(TxnType.CASH_OUT, amount).cash_delta() == -amount
        assert _txn(TxnType.CASH_IN, amount).cash_delta() == amount


# --- enum values are the JSON contract --------------------------------------

ENUM_VALUES = [
    (TxnType, {"cash_in", "cash_out"}),
    (FeedStatus, {"fresh", "delayed", "stale", "conflicting", "missing"}),
    (AlertKind, {"liquidity", "anomaly", "data_quality", "coordination"}),
    (Classification, {"normal", "demand_spike", "needs_review", "data_quality"}),
    (CaseStatus, {"new", "acknowledged", "escalated", "resolved"}),
    (Severity, {"low", "medium", "high", "critical"}),
]


@pytest.mark.parametrize("enum,expected", ENUM_VALUES)
def test_enum_values_are_the_wire_contract(enum, expected):
    assert {member.value for member in enum} == expected


@pytest.mark.parametrize("enum,_", ENUM_VALUES)
def test_enums_serialise_as_their_plain_string_value(enum, _):
    """They subclass ``str``, so a bare member lands in JSON as its value.

    This is the property the dashboard depends on: ``json.dumps`` must emit
    ``"cash_out"``, never ``"TxnType.CASH_OUT"``.
    """
    for member in enum:
        assert isinstance(member, str)
        assert member == member.value
        assert json.loads(json.dumps({"kind": member})) == {"kind": member.value}


def test_every_classification_is_constructible_from_its_string():
    for member in Classification:
        assert Classification(member.value) is member


# --- declared_reconciles ----------------------------------------------------

def test_declared_reconciles_accepts_an_exact_chain():
    assert _position(balance=10_000.0).declared_reconciles(10_000.0)


def test_declared_reconciles_tolerance_scales_with_the_balance():
    """1% of 10,000 is 100 — the tolerance is relative, not absolute."""
    pos = _position(balance=10_000.0)
    assert pos.declared_reconciles(10_100.0)
    assert pos.declared_reconciles(9_900.0)
    assert not pos.declared_reconciles(10_100.01)
    assert not pos.declared_reconciles(9_899.99)


def test_declared_reconciles_uses_an_absolute_floor_for_small_balances():
    """A near-zero balance keeps the 0.01 floor instead of scaling to nothing."""
    pos = _position(balance=0.0)
    assert pos.declared_reconciles(0.01)
    assert not pos.declared_reconciles(0.02)

    tiny = _position(balance=0.5)
    assert tiny.declared_reconciles(0.505)
    assert not tiny.declared_reconciles(0.52)


def test_declared_reconciles_treats_a_negative_balance_by_magnitude():
    pos = _position(balance=-10_000.0)
    assert pos.declared_reconciles(-10_050.0)
    assert not pos.declared_reconciles(-10_200.0)


def test_declared_reconciles_is_symmetric_around_the_declared_balance():
    pos = _position(balance=40_000.0)
    assert pos.declared_reconciles(40_400.0)
    assert pos.declared_reconciles(39_600.0)
    assert not pos.declared_reconciles(40_400.01)
    assert not pos.declared_reconciles(39_599.99)


def test_declared_drift_defaults_to_zero():
    assert ProviderPosition("bkash", 1.0, 1.0, 1.0).declared_drift == 0.0


# --- value objects ----------------------------------------------------------

def test_provider_and_outlet_are_immutable():
    """Shared across the engine, so accidental mutation must be impossible."""
    provider = Provider(id="bkash", name="bKash", name_bn="বিকাশ")
    outlet = Outlet(id="AG-1000", name="Outlet", area="Sylhet",
                    thana="Zindabazar", district="Sylhet")
    with pytest.raises(dataclasses.FrozenInstanceError):
        provider.name = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        outlet.area = "other"


def test_transaction_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _txn().amount = 1.0


def test_outlet_defaults_its_coordinates_to_zero():
    """Hotspot distance degrades gracefully for an outlet with no position."""
    outlet = Outlet(id="AG-1", name="O", area="A", thana="T", district="D")
    assert (outlet.lat, outlet.lon) == (0.0, 0.0)


# --- outlet state -----------------------------------------------------------

def test_total_value_adds_cash_and_every_provider_balance():
    state = _state(cash=10_000.0,
                   positions={"bkash": _position("bkash", 5_000.0),
                              "nagad": _position("nagad", 2_500.0),
                              "rocket": _position("rocket", 1_000.0)})
    assert state.total_value() == pytest.approx(18_500.0)


def test_total_value_of_an_outlet_with_no_provider_positions_is_its_cash():
    assert _state(cash=7_500.0, positions={}).total_value() == pytest.approx(7_500.0)


def test_provider_txns_selects_exactly_one_track():
    state = _state(transactions=[
        _txn(txn_id="a", provider_id="bkash"),
        _txn(txn_id="b", provider_id="nagad"),
    ])
    assert [t.id for t in state.provider_txns("bkash")] == ["a"]
    assert [t.id for t in state.provider_txns("nagad")] == ["b"]
    assert state.provider_txns("rocket") == []


def test_calendar_context_defaults_to_ordinary():
    assert _state().calendar_context == "ordinary"


def test_mutable_defaults_are_not_shared_between_instances():
    """A shared list default would let one outlet mutate another's history."""
    first, second = _state(), _state()
    first.transactions.append(_txn())
    assert second.transactions == []

    alert_a, alert_b = Alert(id="A", outlet_id="AG-1", provider_id=None,
                             kind=AlertKind.LIQUIDITY, severity="low",
                             confidence=0.5, reason="r"), \
        Alert(id="B", outlet_id="AG-1", provider_id=None,
              kind=AlertKind.LIQUIDITY, severity="low", confidence=0.5,
              reason="r")
    alert_a.evidence.append("e")
    alert_a.parts_en["situation"] = "s"
    assert alert_b.evidence == []
    assert alert_b.parts_en == {}
