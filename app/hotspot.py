"""Hotspot mapping and nearby-agent support discovery.

Two optional objectives that share one computation, because they are the same
question asked from two directions:

* **Hotspot mapping** — aggregate risk by area, so an area manager can see that
  one thana is under pressure while another sits comfortable.
* **Nearby-agent support** — for a specific outlet, find the closest outlet that
  holds a *surplus of the same provider's e-money* and could therefore help
  through the normal, approved channel.

The second feature is careful about one thing: it recommends an **approved
balance arrangement**, never a transfer. No function in this codebase moves
value between providers, so a support suggestion cannot be executed as a
cross-provider transfer even by mistake.

Distances are great-circle. Bangladesh is compact enough that this is honest to
the nearest few hundred metres, which is well inside the precision any of these
recommendations deserve.
"""
from __future__ import annotations

import math

from app.config import SETTINGS
from app.domain import OutletRisk

EARTH_RADIUS_KM = 6371.0
SURPLUS_HOURS = 12.0        # comfortable if it can last well past this horizon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if not any((lat1, lon1, lat2, lon2)):
        return 0.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return round(2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a))), 2)


def _at_risk(projection, horizon: float) -> bool:
    return (projection is not None
            and not projection.exhausted
            and projection.hours_to_empty is not None
            and projection.hours_to_empty <= horizon)


def area_risks(rows: list[dict]) -> list[OutletRisk]:
    """Roll outlet-level risk up to area level.

    ``rows`` are dicts with: outlet (Outlet), total_cash, total_emoney,
    at_risk (bool), worst_hours (float | None).
    """
    by_area: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        outlet = row["outlet"]
        by_area.setdefault((outlet.area, outlet.district), []).append(row)

    risks: list[OutletRisk] = []
    for (area, district), group in by_area.items():
        at_risk = [r for r in group if r["at_risk"]]
        risks.append(OutletRisk(
            area=area,
            district=district,
            outlet_count=len(group),
            at_risk_count=len(at_risk),
            total_cash=round(sum(r["total_cash"] for r in group), 2),
            total_emoney=round(sum(r["total_emoney"] for r in group), 2),
            nearest_surplus_outlet=None,
            nearest_surplus_provider=None,
            nearest_surplus_value=0.0,
            distance_km=0.0,
        ))

    risks.sort(key=lambda r: (-r.at_risk_count, r.area))
    return risks


def find_support(source_outlet, source_provider_id: str,
                 candidates: list[tuple[object, str, float | None, float]],
                 source_balance: float = 0.0,
                 max_distance_km: float = 30.0) -> dict | None:
    """Nearest outlet holding a genuine surplus on the *same* provider.

    Each candidate is ``(outlet, provider_id, hours_to_empty, balance)``.

    Note the asymmetry in how a missing horizon is read. For the outlet in
    trouble, ``hours_to_empty is None`` means "no depletion projected" and is
    good news. For a prospective helper, the same value means "no pressure on
    this balance" — which is exactly the headroom we are looking for. So a
    ``None`` horizon counts as surplus here, not as a disqualification.

    A large balance alone is not enough: the helper must hold at least as much
    of this provider's e-money as the outlet in trouble is holding, otherwise
    the arrangement would push the helper into the same problem.

    Same-provider is mandatory rather than preferred, because a provider's
    e-money cannot be sourced from another provider's float — a cross-provider
    suggestion would be unimplementable and, under the platform's guardrails,
    out of scope. This function recommends an arrangement; it never performs
    one, and no function exists here that could.
    """
    best = None
    for outlet, provider_id, hours, balance in candidates:
        if provider_id != source_provider_id:
            continue
        if outlet is None or outlet.id == source_outlet.id:
            continue
        if hours is not None and hours < SURPLUS_HOURS:
            continue        # itself under pressure — not a source of help
        if balance < source_balance:
            continue        # not enough headroom to be useful
        distance = haversine_km(source_outlet.lat, source_outlet.lon,
                                outlet.lat, outlet.lon)
        if distance > max_distance_km:
            continue
        if best is None or distance < best["distance_km"]:
            same_area = outlet.area == source_outlet.area
            best = {
                "outlet_id": outlet.id,
                "outlet_name": outlet.name,
                "area": outlet.area,
                "thana": outlet.thana,
                "provider_id": provider_id,
                "balance": round(balance, 2),
                "hours_of_headroom": (round(hours, 1)
                                      if hours is not None else None),
                "distance_km": distance,
                "same_area": same_area,
                "note": ("Same provider, comfortable headroom — an approved "
                         "balance arrangement could be coordinated before the "
                         "projected exhaustion. This is a recommendation; the "
                         "arrangement itself is made through the normal "
                         "channel."),
            }
    return best


def hotspot_summary(risks: list[OutletRisk]) -> dict:
    total_outlets = sum(r.outlet_count for r in risks)
    total_at_risk = sum(r.at_risk_count for r in risks)
    return {
        "areas": len(risks),
        "outlets": total_outlets,
        "at_risk": total_at_risk,
        "worst_area": risks[0].area if risks else None,
        "note": ("Areas are ranked by how many outlets are projected to run out "
                 "inside the alert horizon."),
    }
