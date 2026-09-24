"""Feed quality, confidence propagation, and safe suppression.

The reliability rule this module exists to enforce:

    A degraded provider feed must never silently produce a confident
    conclusion.

Every analytic conclusion downstream carries a confidence that has already
been multiplied down by the quality of the feed that produced it, and the two
worst feed states — a feed that contradicts our own ledger, and a feed that is
absent entirely — are suppressed outright rather than softened.

Nothing in here talks to the network or to a database: it is pure arithmetic
over the domain dataclasses, which is what makes the reliability guarantee
testable.
"""
from __future__ import annotations

from app.domain import FeedStatus, OutletState, ProviderPosition, Transaction

# --- Confidence propagation ------------------------------------------------
# Strictly monotonic decreasing: a worse feed can never yield a higher
# confidence, and the ordering itself is asserted in the test suite.
CONFIDENCE_MULTIPLIER: dict[FeedStatus, float] = {
    FeedStatus.FRESH: 1.0,
    FeedStatus.DELAYED: 0.8,
    FeedStatus.STALE: 0.5,
    FeedStatus.CONFLICTING: 0.3,
    FeedStatus.MISSING: 0.0,
}

# An outlet never reaches zero reliability: the UI still has to render
# something, and a floor of 0.05 reads as "essentially no confidence" without
# producing a dead surface.
MIN_RELIABILITY = 0.05

# --- Feed-age thresholds (seconds) ----------------------------------------
DELAYED_AFTER_S = 300.0     # 5 minutes
STALE_AFTER_S = 1800.0      # 30 minutes

# Unexplained balance movement below this is treated as rounding noise rather
# than as a contradiction between the provider's feed and our own ledger.
DRIFT_FLOOR = 1000.0

# --- Suppression language ---------------------------------------------------
# The *policy* statement for a withdrawn projection: what the product promises
# to say when it declines to estimate. It is asserted by the test suite rather
# than rendered, because the text a user actually sees is the four-part
# narrative assembled in narrative.assemble_liquidity() — situation, evidence,
# uncertainty and next steps, in both languages. Keeping the promise in one
# checkable place is the point; quoting this constant as if it were the
# rendered string is not, and RESPONSIBLE_DESIGN.md once did exactly that.
SUPPRESSION_NOTICE = (
    "Provider feed data is unreliable. Verify the feed before acting on any "
    "projection for this provider."
)
SUPPRESSION_NOTICE_BN = (
    "প্রদানকারীর ফিড নির্ভরযোগ্য নয়। কোনো প্রকল্পের ভিত্তিতে ব্যবস্থা নেওয়ার "
    "আগে ফিডটি যাচাই করুন।"
)


def reconcile(opening: float, txns: list[Transaction]) -> float:
    """Replay the e-money chain from an opening balance.

    Each cash-out grows the provider's e-money balance and each cash-in shrinks
    it; the sign convention lives on the transaction itself so it can never
    drift out of sync between modules.
    """
    total = opening
    for txn in txns:
        total += txn.emoney_delta()
    return total


def classify_feed(last_feed_at: float | None, now: float,
                  drift: float) -> FeedStatus:
    """Grade a provider feed.

    Drift outranks freshness: a feed that arrived a second ago but disagrees
    with our own ledger is *less* trustworthy than an old feed that agrees with
    it, so the contradiction is reported as CONFLICTING before lag is even
    considered.
    """
    if last_feed_at is None:
        return FeedStatus.MISSING
    if abs(drift) > DRIFT_FLOOR:
        return FeedStatus.CONFLICTING
    lag = now - last_feed_at
    if lag > STALE_AFTER_S:
        return FeedStatus.STALE
    if lag > DELAYED_AFTER_S:
        return FeedStatus.DELAYED
    return FeedStatus.FRESH


def should_suppress(status: FeedStatus) -> bool:
    """Whether conclusions drawn from this feed must be withheld entirely."""
    return status in (FeedStatus.CONFLICTING, FeedStatus.MISSING)


def _age_minutes(pos: ProviderPosition, now: float) -> int | None:
    """Age of a position's last feed in whole minutes, or None if never seen."""
    if pos.last_feed_at is None:
        return None
    return int((now - pos.last_feed_at) // 60)


def _degradation_note(provider_id: str, pos: ProviderPosition,
                      now: float) -> str:
    """Human-readable note such as ``nagad: stale (45 min old)``."""
    status = pos.feed_status
    age = _age_minutes(pos, now)
    if age is None:
        detail = "no feed"
    else:
        detail = f"{age} min old"
    note = f"{provider_id}: {status.value} ({detail})"
    if should_suppress(status):
        note += "; verify feed before acting"
    return note


def outlet_reliability(state: OutletState, now: float) -> tuple[float, list[str]]:
    """Aggregate confidence multiplier for an outlet, plus degradation notes.

    Multipliers compose rather than average: two independent providers that are
    each only half-trustworthy do not add up to a trustworthy outlet. The
    product is floored at MIN_RELIABILITY so the value stays usable by callers
    that divide by it, while still reading as "do not trust this".
    """
    multiplier = 1.0
    notes: list[str] = []
    for provider_id, pos in state.positions.items():
        status = pos.feed_status
        multiplier *= CONFIDENCE_MULTIPLIER.get(status, MIN_RELIABILITY)
        if status is not FeedStatus.FRESH:
            notes.append(_degradation_note(provider_id, pos, now))
    return max(MIN_RELIABILITY, multiplier), notes
