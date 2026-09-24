"""Coordination workflow and append-only audit trail.

The product's failure mode is an alert that ends as a passive notification.
This module is what prevents that: every alert is opened as a *case* with a
named human owner, moved through an explicit lifecycle, and every move is
written to an append-only SQLite trail.

Two safety properties are enforced here rather than trusted to callers:

1. **No financial verbs.** A case may be acknowledged, escalated, resolved or
   annotated. It may never move money. The dashboard can therefore never be
   mistaken for a payments console — see ``VALID_ACTIONS``.
2. **Provider boundary.** An alert tagged to one provider's operations track
   may only be acted on by that same track. Shared-cash alerts (provider
   ``None``) are open to anyone. This stops one operator from reaching into
   another provider's book, which is both a fairness rule and a regulatory one.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.domain import Alert, AlertKind, CaseEvent, CaseStatus

__all__ = [
    "AuditLog",
    "DEFAULT_ROUTE",
    "ROUTES",
    "VALID_ACTIONS",
    "open_case",
    "provider_boundary_ok",
    "route",
    "transition",
]


# Actions a case may take. Deliberately non-financial: there is no verb here
# that moves, freezes, blocks or reverses value. Anything a human operator would
# recognise as a money movement belongs to the providers' own systems, not to
# this coordination layer.
VALID_ACTIONS = {"acknowledge", "escalate", "resolve", "note"}

# Financial-operation verbs that must never appear in VALID_ACTIONS. Kept as a
# named constant so the guardrail is data, and so other modules can assert it.
FORBIDDEN_ACTION_VERBS = ("transfer", "refill", "block", "freeze", "reverse")

# role -> named assignee. The escalation chain is:
#   agent -> field_officer -> area_manager -> central_operations -> risk_analyst
# Severities are the plain strings on Alert.severity: low | medium | high |
# critical. Every kind maps every severity so a case always lands on a named
# human; there is no severity for which routing "does nothing".
ROUTES: dict[AlertKind, dict[str, tuple[str, str]]] = {
    AlertKind.LIQUIDITY: {
        # The agent can usually handle a soft pressure signal themselves.
        "low": ("agent", "AGENT-SELF"),
        "medium": ("area_manager", "AM-207"),
        # Physical cash pressure needs someone who can walk into the outlet.
        "high": ("field_officer", "FO-1042"),
        "critical": ("area_manager", "AM-101"),
    },
    AlertKind.ANOMALY: {
        "low": ("area_manager", "AM-207"),
        "medium": ("central_operations", "OPS-31"),
        "high": ("central_operations", "OPS-31"),
        # The most severe anomaly pattern goes to the analyst, not the desk.
        "critical": ("risk_analyst", "RA-7"),
    },
    AlertKind.DATA_QUALITY: {
        # Feed problems are a platform-side concern at every severity; a bad
        # feed must never be "resolved" by an outlet.
        "low": ("central_operations", "OPS-55"),
        "medium": ("central_operations", "OPS-55"),
        "high": ("central_operations", "OPS-55"),
        "critical": ("central_operations", "OPS-55"),
    },
    AlertKind.COORDINATION: {
        # Coordination alerts exist because two tracks failed to line up, so
        # the low end still stays inside the operating chain.
        "low": ("agent", "AGENT-SELF"),
        "medium": ("field_officer", "FO-2210"),
        "high": ("area_manager", "AM-330"),
        "critical": ("central_operations", "OPS-77"),
    },
}

# Safe default for an unknown kind or an unrecognised severity: we still want a
# named human to own it. Routing an unknown alert to nobody is the exact
# failure mode this module exists to prevent.
DEFAULT_ROUTE: tuple[str, str] = ("area_manager", "AM-000")

_ACTION_STATUS = {
    "acknowledge": CaseStatus.ACKNOWLEDGED,
    "escalate": CaseStatus.ESCALATED,
    "resolve": CaseStatus.RESOLVED,
}


def _sev_key(severity: object) -> str:
    """Normalise a severity to its lookup key.

    Accepts the plain strings used on ``Alert.severity`` and also the
    ``Severity`` enum, so callers can pass either without a routing surprise.
    """
    value = getattr(severity, "value", severity)
    return str(value).strip().lower()


def _kind_key(kind: object) -> AlertKind | None:
    """Normalise an alert kind to a route-table key, or ``None`` if unknown."""
    if isinstance(kind, AlertKind):
        return kind
    try:
        return AlertKind(kind)
    except (ValueError, TypeError):
        return None


def route(alert: Alert) -> tuple[str, str]:
    """Provider-aware routing: return ``(role, named_assignee)``.

    Unknown kinds and unknown severities fall back rather than raising, so a
    mislabelled alert is still owned by somebody instead of silently dropped.
    """
    table = ROUTES.get(_kind_key(alert.kind))
    if not table:
        return DEFAULT_ROUTE
    key = _sev_key(alert.severity)
    if key in table:
        return table[key]
    # Unrecognised severity: treat as the middle of the road, then anything.
    for fallback in ("medium", "high", "low", "critical"):
        if fallback in table:
            return table[fallback]
    return DEFAULT_ROUTE


def provider_boundary_ok(alert_provider: str | None,
                         actor_provider: str | None) -> bool:
    """May this actor's track act on this alert?

    ``None`` on the alert means shared physical cash, which any track may
    coordinate on. Otherwise the tracks must match exactly.
    """
    if alert_provider is None:
        return True
    return alert_provider == actor_provider


def open_case(alert: Alert, now: float,
              prior: "tuple[CaseStatus, str, str] | None" = None) -> Alert:
    """Turn an alert into an owned case: role, named assignee, status NEW.

    ``prior`` is the persisted state of the same case from an earlier build, if
    there was one. The status a human set is not ours to undo, so it survives;
    without this, acknowledging a case and then dragging the what-if slider
    silently reverted it to NEW, which made "resolution tracking" a
    demonstration rather than a record.

    The *role* is deliberately not restored: it is a pure function of the
    alert's kind and current severity, so re-deriving it is how a case that got
    more urgent ends up with the right desk. The named assignee is a human
    assignment, not a derivation, so that one is kept.
    """
    role, assignee = route(alert)
    alert.owner = role
    alert.assignee = assignee
    alert.status = CaseStatus.NEW
    if prior is not None:
        status, _role, prior_assignee = prior
        alert.status = status
        alert.assignee = prior_assignee or assignee
    alert.created_at = alert.created_at or now
    return alert


def transition(alert: Alert, action: str, actor: str, note: str, now: float,
               actor_provider: str | None,
               log: "AuditLog | None" = None) -> Alert:
    """Apply an action to a case, enforcing the guardrails.

    Raises ``ValueError`` for an action outside ``VALID_ACTIONS`` (before any
    permission check, so an invalid action never leaks a boundary verdict) and
    for a note action that carries no note, and ``PermissionError`` for a
    cross-provider action.

    A status-changing action on a resolved case is allowed rather than refused:
    an operator who resolved a case by mistake must be able to correct it, and
    this vocabulary has no separate "reopen" verb, so refusing would leave the
    case stuck. It is instead reported to the caller as a reopen — see
    ``Engine.act``. Leaving it silent is what made it a defect: the case moved
    backwards and the operator was told only that an action was recorded.
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"unsupported action: {action!r}")

    # A note is the one action whose entire content is its text, so an empty
    # one writes a row into an append-only trail that says nothing and cannot
    # be withdrawn. The dashboard already refuses this; the API must too,
    # because the dashboard is not the only caller.
    if action == "note" and not (note or "").strip():
        raise ValueError("a note action requires a note")

    if not provider_boundary_ok(alert.provider_id, actor_provider):
        raise PermissionError(
            f"provider boundary violation: actor on the {actor_provider!r} "
            f"track cannot act on alert {alert.id} tagged "
            f"{alert.provider_id!r}")

    if action != "note":
        alert.status = _ACTION_STATUS[action]

    if log is not None:
        log.append(CaseEvent(alert_id=alert.id, actor=actor, action=action,
                             note=note, ts=now))
    return alert


class AuditLog:
    """Append-only case history backed by stdlib SQLite.

    The class deliberately exposes no update and no delete path: there is no
    method that can rewrite history, so a reviewer reading ``trail()`` is
    reading what actually happened. ``seq`` is assigned by SQLite, which keeps
    ordering stable across reopens.
    """

    _SCHEMA = (
        "CREATE TABLE IF NOT EXISTS case_events ("
        " alert_id TEXT NOT NULL,"
        " actor TEXT NOT NULL,"
        " action TEXT NOT NULL,"
        " note TEXT,"
        " ts REAL NOT NULL,"
        " seq INTEGER PRIMARY KEY AUTOINCREMENT)")

    _COLUMNS = ("alert_id", "actor", "action", "note", "ts")

    def __init__(self, path: Path | str):
        self.path = Path(path)
        # Parent directories are created on demand so the caller can point the
        # log at data/audit.sqlite on a fresh checkout.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(self._SCHEMA)
        self._conn.commit()

    def append(self, event: CaseEvent) -> None:
        """Record one case event. The only write path."""
        self._conn.execute(
            "INSERT INTO case_events (alert_id, actor, action, note, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (event.alert_id, event.actor, event.action, event.note, event.ts))
        self._conn.commit()

    def trail(self, alert_id: str) -> list[dict]:
        """Every event for one case, in the order it happened."""
        rows = self._conn.execute(
            "SELECT alert_id, actor, action, note, ts FROM case_events "
            "WHERE alert_id = ? ORDER BY seq", (alert_id,)).fetchall()
        return [dict(zip(self._COLUMNS, row)) for row in rows]

    def everything(self, limit: int = 200) -> list[dict]:
        """The most recent events across all cases, newest first.

        Read-only, like ``trail``. Used by the dashboard's activity feed, which
        needs the whole ledger rather than one case's history.
        """
        rows = self._conn.execute(
            "SELECT alert_id, actor, action, note, ts FROM case_events "
            "ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(self._COLUMNS, row)) for row in rows]

    def resumed_states(self) -> dict:
        """The status each case was left in, derived from the durable trail.

        The log is the permanent record, so it is also the place to recover
        from. Without this, restarting the process kept the whole audit trail
        but reset every case to NEW — so a reviewer saw a case marked new
        sitting next to a trail showing it had been acknowledged, which is
        exactly the kind of self-contradiction this product exists to avoid.

        Notes do not move a case, so they are skipped; the last
        status-changing event wins.
        """
        rows = self._conn.execute(
            "SELECT alert_id, action FROM case_events ORDER BY seq").fetchall()
        states: dict[str, CaseStatus] = {}
        for alert_id, action in rows:
            status = _ACTION_STATUS.get(action)
            if status is not None:
                states[alert_id] = status
        return states

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
