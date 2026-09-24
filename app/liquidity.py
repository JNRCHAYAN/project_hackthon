"""Liquidity projection.

The estimator is Theil-Sen (median of pairwise slopes) rather than a least-squares
fit or a mean rate. That choice is deliberate and load-bearing: an Eid afternoon
contains single transactions large enough to invert a naive slope, and a product
whose entire purpose is surviving demand spikes cannot be destroyed by one of them.

Every projection returns an interval and a confidence, never a bare point estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from app.config import SETTINGS
from app.domain import FeedStatus

EPS = 1e-6


@dataclass
class SlopeFit:
    slope: float          # balance units per hour; negative == draining
    low: float            # 10th percentile of pairwise slopes
    high: float           # 90th percentile of pairwise slopes
    n: int
    residual_scale: float


@dataclass
class Projection:
    label: str                    # "cash" or a provider id
    balance: float
    rate_per_hour: float          # positive == draining
    hours_to_empty: float | None  # None when no depletion is projected
    low_hours: float | None
    high_hours: float | None
    exhausted: bool
    confidence: float
    points_used: int


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def theil_sen(points: list[tuple[float, float]]) -> SlopeFit:
    """Robust slope via the median of all pairwise slopes."""
    n = len(points)
    if n < 2:
        return SlopeFit(0.0, 0.0, 0.0, n, 0.0)

    slopes: list[float] = []
    for i in range(n):
        xi, yi = points[i]
        for j in range(i + 1, n):
            dx = points[j][0] - xi
            if dx > EPS:
                slopes.append((points[j][1] - yi) / dx)

    if not slopes:
        return SlopeFit(0.0, 0.0, 0.0, n, 0.0)

    slopes.sort()
    m = len(slopes)
    slope = slopes[m // 2] if m % 2 else (slopes[m // 2 - 1] + slopes[m // 2]) / 2.0
    intercept = median([y - slope * x for x, y in points])
    residual_scale = median([abs(y - (intercept + slope * x)) for x, y in points])

    return SlopeFit(slope=slope, low=_pct(slopes, 0.10), high=_pct(slopes, 0.90),
                    n=n, residual_scale=residual_scale)


def project_balance(label: str, balance: float,
                    points: list[tuple[float, float]],
                    confidence_mult: float = 1.0,
                    now_hours: float | None = None) -> Projection:
    """Project time to exhaustion.

    Guarded against three failure modes that would otherwise reach the UI:
    a zero/rising balance (would divide by zero), an already-exhausted balance
    (would yield a negative duration), and insufficient history (would produce
    a confident answer from noise).
    """
    if now_hours is not None:
        points = [(x, y) for x, y in points if x <= now_hours]
    points = sorted(points)

    if balance <= 0.0:
        return Projection(label, balance, 0.0, 0.0, 0.0, 0.0, True,
                          max(0.05, 0.9 * confidence_mult), len(points))

    if len(points) < 2:
        return Projection(label, balance, 0.0, None, None, None, False,
                          max(0.05, 0.25 * confidence_mult), len(points))

    fit = theil_sen(points)
    rate = -fit.slope                       # positive == draining
    if rate <= EPS:
        # Zero or rising balance. No depletion is projected — this is NOT an
        # infinite horizon and must never be rendered as one.
        return Projection(label, balance, 0.0, None, None, None, False,
                          max(0.05, 0.55 * confidence_mult), len(points))

    hours = balance / rate
    drain_low = max(-fit.high, EPS)         # flattest credible drain -> latest
    drain_high = max(-fit.low, EPS)         # steepest credible drain -> earliest
    high_hours = balance / drain_low
    low_hours = balance / drain_high

    rel_uncertainty = min(1.0, (high_hours - low_hours) / max(hours, EPS))
    sample = min(1.0, len(points) / 20.0)
    confidence = 0.35 + 0.45 * sample - 0.30 * rel_uncertainty
    confidence = max(0.05, min(0.98, confidence * confidence_mult))

    return Projection(label, balance, rate, hours, low_hours, high_hours, False,
                      confidence, len(points))


def _confidence_multiplier(status: FeedStatus) -> float:
    from app.quality import CONFIDENCE_MULTIPLIER
    return CONFIDENCE_MULTIPLIER.get(status, 0.5)


def apply_demand(projection: Projection, multiplier: float) -> Projection:
    """What-if hook: scale the drain rate by a demand multiplier.

    Exhaustion time scales inversely, which is the honest first-order answer to
    "what if demand rises N times?". Estimation uncertainty is unchanged, so
    confidence is preserved — raising demand does not make the estimate better.
    """
    if multiplier == 1.0 or projection.hours_to_empty is None:
        return projection
    mult = max(0.05, float(multiplier))
    return Projection(
        label=projection.label, balance=projection.balance,
        rate_per_hour=projection.rate_per_hour * mult,
        hours_to_empty=projection.hours_to_empty / mult,
        low_hours=(projection.low_hours / mult
                   if projection.low_hours is not None else None),
        high_hours=(projection.high_hours / mult
                    if projection.high_hours is not None else None),
        exhausted=projection.exhausted, confidence=projection.confidence,
        points_used=projection.points_used)


def project_outlet(state, now: float, demand_multiplier: float = 1.0) -> list[Projection]:
    """Project shared cash and every provider e-money balance, separately.

    Shared cash and each provider's e-money are projected independently because
    they are drawn down by opposite transaction types. Aggregating them first
    would hide the exact condition this product exists to expose.
    """
    window = SETTINGS["trailing_window_minutes"] * 60.0
    cutoff = now - window
    base = now / 3600.0

    # --- shared physical cash -------------------------------------------------
    cash_points: list[tuple[float, float]] = []
    running = state.cash_opening
    for t in sorted(state.transactions, key=lambda t: t.ts):
        if t.ts < cutoff or t.ts > now:
            continue
        running += t.cash_delta()
        cash_points.append((t.ts / 3600.0, running))
    if not cash_points:
        cash_points = [(base, state.cash)]

    projections = [
        apply_demand(
            project_balance("cash", state.cash, cash_points, 1.0, base),
            demand_multiplier)
    ]

    # --- each provider's e-money ---------------------------------------------
    for pid, pos in state.positions.items():
        bal = pos.opening_balance
        points: list[tuple[float, float]] = []
        for t in sorted(state.provider_txns(pid), key=lambda t: t.ts):
            if t.ts < cutoff or t.ts > now:
                continue
            bal += t.emoney_delta()
            points.append((t.ts / 3600.0, bal))
        if not points:
            points = [(base, pos.balance)]
        else:
            # The declared balance is authoritative for "now"; the replayed
            # series can drift from it when a feed is inconsistent.
            points[-1] = (points[-1][0], pos.balance)

        projections.append(apply_demand(
            project_balance(pid, pos.balance, points,
                            _confidence_multiplier(pos.feed_status), base),
            demand_multiplier))

    return projections


def worst_projection(projections: list[Projection]) -> Projection | None:
    """The soonest exhaustion across all balances — the outlet's real risk."""
    candidates = [p for p in projections
                  if p.hours_to_empty is not None and not p.exhausted]
    if not candidates:
        return None
    return min(candidates, key=lambda p: p.hours_to_empty or float("inf"))
