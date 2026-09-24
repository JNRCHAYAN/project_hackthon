"""Unusual-activity detection.

Two families, kept deliberately separate because they mean completely different
things and must never be collapsed into one "risk score":

* ``burst_identical`` — near-identical amounts at high velocity from a small set
  of accounts. This is the pattern that requires human review.
* ``balance_chain``   — the declared balance does not reconcile with the
  transaction history. This is a **data integrity fault**, not suspicious
  behaviour, and it is routed as such. Conflating the two would be both
  analytically wrong and unfair to the parties involved.

Detection is per-provider and, in ``scan``, per-outlet. Nothing here compares one
agent's behaviour against another's.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.config import SETTINGS
from app.domain import TxnType
from app.quality import reconcile

MIN_BURST_TXNS = 6


@dataclass
class AnomalySignal:
    kind: str                      # burst_identical | balance_chain
    provider_id: str | None
    accounts: list[str] = field(default_factory=list)
    amounts: list[float] = field(default_factory=list)
    window_minutes: int = 0
    magnitude: float = 0.0
    evidence: list[str] = field(default_factory=list)


def detect_burst(txns: list, provider_id: str | None = None,
                 window_minutes: int | None = None) -> AnomalySignal | None:
    """Near-identical amounts, few distinct accounts, high velocity in a window.

    Three conditions must hold simultaneously. Any one of them alone is
    ordinary: a busy afternoon has high velocity, a single large transfer has
    a distinctive amount, and a small outlet has few accounts. Only the
    conjunction is worth a human's attention.
    """
    window = window_minutes or SETTINGS["burst_window_minutes"]
    tol = SETTINGS["burst_amount_tolerance"]
    max_accounts = SETTINGS["burst_max_accounts"]

    pool = [t for t in txns if t.status == "success"]
    if provider_id is not None:
        pool = [t for t in pool if t.provider_id == provider_id]

    by_provider: dict[str, list] = {}
    for t in pool:
        by_provider.setdefault(t.provider_id, []).append(t)

    best: AnomalySignal | None = None

    for pid, group in by_provider.items():
        group = sorted(group, key=lambda t: t.ts)
        for i, anchor in enumerate(group):
            hi = anchor.ts + window * 60.0
            bucket = [t for t in group[i:] if t.ts <= hi]
            if len(bucket) < MIN_BURST_TXNS:
                continue

            similar = [t for t in bucket
                       if abs(t.amount - anchor.amount)
                       <= tol * max(abs(anchor.amount), 1.0)]
            if len(similar) < MIN_BURST_TXNS:
                continue

            accounts = [t.sender_hash for t in similar]
            if len(set(accounts)) > max_accounts:
                continue

            amounts = [t.amount for t in similar]
            # A broad amount range is ordinary demand, not a burst.
            if max(amounts) - min(amounts) > tol * 4 * max(abs(anchor.amount), 1.0):
                continue

            total = sum(amounts)
            signal = AnomalySignal(
                kind="burst_identical", provider_id=pid,
                accounts=sorted(set(accounts)), amounts=amounts,
                window_minutes=window,
                magnitude=float(len(similar)),
                evidence=[
                    f"{len(similar)} transactions within ±{int(tol * 100)}% of "
                    f"৳{anchor.amount:,.0f} in {window} minutes",
                    f"originating from only {len(set(accounts))} distinct accounts",
                    f"combined value ৳{total:,.0f}",
                ])
            if best is None or signal.magnitude > best.magnitude:
                best = signal

    return best


def detect_balance_drift(state) -> AnomalySignal | None:
    """Balance-chain failure. Classified as data quality, never as suspicion."""
    for pid, pos in state.positions.items():
        provider_txns = state.provider_txns(pid)
        if not provider_txns:
            continue
        computed = reconcile(pos.opening_balance, provider_txns)
        drift = pos.balance - computed
        if not pos.declared_reconciles(computed,
                                       SETTINGS["reconcile_tolerance"]):
            pos.declared_drift = round(drift, 2)
            return AnomalySignal(
                kind="balance_chain", provider_id=pid, magnitude=abs(drift),
                evidence=[
                    f"declared balance ৳{pos.balance:,.0f}",
                    f"reconciled from opening balance plus recorded "
                    f"transactions ৳{computed:,.0f}",
                    f"unexplained difference ৳{drift:,.0f}",
                ])
    return None


def account_concentration(txns: list, provider_id: str | None = None) -> dict:
    """How concentrated is activity among accounts? Feeds the context verdict."""
    pool = [t for t in txns if t.status == "success"]
    if provider_id:
        pool = [t for t in pool if t.provider_id == provider_id]
    counts = Counter(t.sender_hash for t in pool)
    if not pool:
        return {"accounts": 0, "txns": 0, "top_share": 0.0, "amount_spread": 0.0}
    amounts = [t.amount for t in pool]
    hi = max(amounts) or 1.0
    return {
        "accounts": len(counts),
        "txns": len(pool),
        "top_share": counts.most_common(1)[0][1] / len(pool),
        "amount_spread": (max(amounts) - min(amounts)) / hi,
    }


def scan(state, now: float) -> list[AnomalySignal]:
    """All signals for one outlet. Burst first, then integrity faults."""
    signals: list[AnomalySignal] = []
    burst = detect_burst(state.transactions)
    if burst:
        signals.append(burst)
    drift = detect_balance_drift(state)
    if drift:
        signals.append(drift)
    return signals
