"""Task 9 — coordination workflow and the append-only audit trail.

These tests are as much about the guardrails as about the happy path: a case
must always land on a named human, and no action may ever cross a provider
boundary or read as a money movement.
"""
import pytest

from app.coordination import (
    DEFAULT_ROUTE,
    FORBIDDEN_ACTION_VERBS,
    ROUTES,
    AuditLog,
    VALID_ACTIONS,
    open_case,
    provider_boundary_ok,
    route,
    transition,
)
from app.domain import Alert, AlertKind, CaseEvent, CaseStatus, Severity

SEVERITIES = ("low", "medium", "high", "critical")


def _alert(kind=AlertKind.LIQUIDITY, provider="nagad", severity="high",
           alert_id="AL-1"):
    return Alert(id=alert_id, outlet_id="AG-1000", provider_id=provider,
                 kind=kind, severity=severity, confidence=0.7,
                 reason="pressure", created_at=1000.0)


# --- routing ---------------------------------------------------------------

def test_routing_assigns_owner_by_severity_and_kind():
    role, assignee = route(_alert())
    assert role and assignee


@pytest.mark.parametrize("kind", list(AlertKind))
@pytest.mark.parametrize("severity", SEVERITIES)
def test_every_kind_and_severity_routes_to_a_role_and_named_assignee(kind, severity):
    role, assignee = route(_alert(kind=kind, severity=severity))
    assert isinstance(role, str) and role
    assert isinstance(assignee, str) and assignee


def test_routes_table_covers_every_alert_kind_and_severity():
    for kind in AlertKind:
        assert kind in ROUTES, f"{kind} is not routable"
        table = ROUTES[kind]
        for severity in SEVERITIES:
            assert severity in table, f"{kind}/{severity} has no route"
            role, assignee = table[severity]
            assert role and assignee


def test_high_severity_liquidity_routes_to_field_officer():
    assert route(_alert(severity="high"))[0] == "field_officer"


def test_high_severity_anomaly_routes_to_central_operations():
    assert route(_alert(kind=AlertKind.ANOMALY))[0] == "central_operations"


def test_routed_roles_stay_on_the_escalation_chain():
    chain = {"agent", "field_officer", "area_manager", "central_operations",
             "risk_analyst"}
    for table in ROUTES.values():
        for role, assignee in table.values():
            assert role in chain
            assert assignee


def test_unknown_kind_and_severity_fall_back_instead_of_raising():
    assert route(_alert(kind="not_a_kind")) == DEFAULT_ROUTE
    assert route(_alert(kind=AlertKind.LIQUIDITY, severity="catastrophic"))
    assert route(_alert(kind=AlertKind.LIQUIDITY, severity=Severity.HIGH))[0] == \
        "field_officer"


# --- case opening ----------------------------------------------------------

def test_open_case_sets_owner_and_new_status():
    case = open_case(_alert(), now=2000.0)
    assert case.owner and case.assignee
    assert case.status is CaseStatus.NEW
    assert case.created_at == 1000.0  # pre-existing timestamp preserved


def test_open_case_stamps_created_at_when_missing():
    alert = _alert()
    alert.created_at = 0.0
    assert open_case(alert, now=2000.0).created_at == 2000.0


# --- lifecycle -------------------------------------------------------------

def test_full_lifecycle_acknowledge_escalate_resolve():
    case = open_case(_alert(), now=2000.0)
    assert case.status is CaseStatus.NEW

    case = transition(case, "acknowledge", "FO-12", "on it", 2001.0, "nagad")
    assert case.status is CaseStatus.ACKNOWLEDGED

    case = transition(case, "escalate", "FO-12", "needs ops", 2002.0, "nagad")
    assert case.status is CaseStatus.ESCALATED

    case = transition(case, "resolve", "OPS-3", "balance arranged", 2003.0,
                      "nagad")
    assert case.status is CaseStatus.RESOLVED


def test_note_action_leaves_status_unchanged():
    case = open_case(_alert(), now=2000.0)
    case = transition(case, "acknowledge", "FO-12", "", 2001.0, "nagad")
    case = transition(case, "note", "FO-12", "called the outlet", 2002.0,
                      "nagad")
    assert case.status is CaseStatus.ACKNOWLEDGED


def test_invalid_action_is_rejected():
    case = open_case(_alert(), now=2000.0)
    with pytest.raises(ValueError):
        transition(case, "freeze_funds", "FO-1", "", 2001.0, "nagad")


def test_invalid_action_is_rejected_even_across_a_provider_boundary():
    """An unknown verb is a ValueError, not a permission leak."""
    case = open_case(_alert(provider="nagad"), now=2000.0)
    with pytest.raises(ValueError):
        transition(case, "refill", "OPS-bkash", "", 2001.0, "bkash")


# --- provider boundary -----------------------------------------------------

def test_boundary_helper_is_explicit():
    assert provider_boundary_ok("nagad", "nagad") is True
    assert provider_boundary_ok("nagad", "bkash") is False
    assert provider_boundary_ok(None, "bkash") is True
    assert provider_boundary_ok(None, "nagad") is True
    assert provider_boundary_ok("bkash", None) is False


def test_cross_provider_action_is_blocked():
    case = open_case(_alert(provider="nagad"), now=2000.0)
    with pytest.raises(PermissionError) as excinfo:
        transition(case, "resolve", "OPS-bkash", "done", 2001.0, "bkash")
    message = str(excinfo.value)
    assert "boundary" in message
    assert "nagad" in message and "bkash" in message
    # The blocked action must not have moved the case.
    assert case.status is CaseStatus.NEW


def test_shared_cash_alert_may_be_acted_on_by_any_track():
    case = open_case(_alert(provider=None), now=2000.0)
    case = transition(case, "acknowledge", "OPS-9", "shared drawer", 2001.0,
                      "bkash")
    assert case.status is CaseStatus.ACKNOWLEDGED


# --- audit trail -----------------------------------------------------------

def test_audit_trail_records_every_transition(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite")
    case = open_case(_alert(), now=2000.0)
    case = transition(case, "acknowledge", "FO-12", "ok", 2001.0, "nagad",
                      log=log)
    case = transition(case, "resolve", "FO-12", "done", 2002.0, "nagad",
                      log=log)
    trail = log.trail("AL-1")
    assert len(trail) >= 2
    assert [e["action"] for e in trail][-2:] == ["acknowledge", "resolve"]
    assert trail[-1]["actor"] == "FO-12"
    assert trail[-1]["note"] == "done"
    assert trail[-1]["ts"] == 2002.0
    log.close()


def test_audit_trail_preserves_order_across_a_full_lifecycle(tmp_path):
    log = AuditLog(tmp_path / "nested" / "audit.sqlite")
    case = open_case(_alert(), now=2000.0)
    for i, action in enumerate(
            ["acknowledge", "note", "escalate", "note", "resolve"]):
        case = transition(case, action, "FO-12", f"step {i}", 2001.0 + i,
                          "nagad", log=log)
    assert [e["action"] for e in log.trail("AL-1")] == [
        "acknowledge", "note", "escalate", "note", "resolve"]
    log.close()


def test_audit_trail_survives_a_reopen(tmp_path):
    path = tmp_path / "audit.sqlite"
    log = AuditLog(path)
    case = open_case(_alert(), now=2000.0)
    case = transition(case, "acknowledge", "FO-12", "ok", 2001.0, "nagad",
                      log=log)
    case = transition(case, "escalate", "FO-12", "needs ops", 2002.0, "nagad",
                      log=log)
    log.close()

    reopened = AuditLog(path)
    trail = reopened.trail("AL-1")
    assert [e["action"] for e in trail] == ["acknowledge", "escalate"]
    # Appending after a reopen continues the same history, in order.
    transition(case, "resolve", "OPS-3", "arranged", 2003.0, "nagad",
               log=reopened)
    assert [e["action"] for e in reopened.trail("AL-1")] == [
        "acknowledge", "escalate", "resolve"]
    reopened.close()


def test_audit_log_creates_parent_directories(tmp_path):
    path = tmp_path / "deep" / "deeper" / "audit.sqlite"
    log = AuditLog(path)
    log.append(CaseEvent(alert_id="AL-2", actor="FO-1", action="note",
                         note="hi", ts=1.0))
    assert path.exists()
    log.close()


def test_trails_are_isolated_per_alert(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite")
    log.append(CaseEvent(alert_id="AL-1", actor="a", action="note", note="",
                         ts=1.0))
    log.append(CaseEvent(alert_id="AL-2", actor="b", action="note", note="",
                         ts=2.0))
    assert [e["actor"] for e in log.trail("AL-1")] == ["a"]
    assert [e["actor"] for e in log.trail("AL-2")] == ["b"]
    log.close()


# --- guardrails ------------------------------------------------------------

def test_valid_actions_never_include_financial_operations():
    for banned in FORBIDDEN_ACTION_VERBS:
        assert banned not in VALID_ACTIONS


def test_valid_actions_are_exactly_the_coordination_verbs():
    assert VALID_ACTIONS == {"acknowledge", "escalate", "resolve", "note"}


def test_audit_log_exposes_no_mutation_or_deletion_method():
    """Append-only is a structural property, not a convention."""
    banned_substrings = ("update", "delete", "remove", "drop", "purge",
                         "truncate", "clear", "set", "unlink", "pop", "edit")
    public = [name for name in dir(AuditLog) if not name.startswith("_")]
    offenders = [name for name in public
                 if any(bad in name.lower() for bad in banned_substrings)]
    assert offenders == [], f"mutating API found: {offenders}"
    assert "append" in public and "trail" in public

    log = AuditLog(":memory:")
    for name in ("delete", "update", "remove", "drop", "purge", "clear"):
        assert not hasattr(log, name)
    log.close()


def test_no_route_or_action_exposes_a_financial_verb():
    """The boundary holds for routing too: no role performs an operation."""
    for table in ROUTES.values():
        for role, assignee in table.values():
            for banned in FORBIDDEN_ACTION_VERBS:
                assert banned not in role.lower()
                assert banned not in assignee.lower()


def test_open_case_resumes_a_prior_decision():
    """Re-deriving a case must not silently reopen a case a human closed."""
    alert = _alert(provider="nagad")
    case = open_case(alert, now=2000.0,
                     prior=(CaseStatus.RESOLVED, "nagad risk desk", "Rima"))
    assert case.status is CaseStatus.RESOLVED
    assert case.assignee == "Rima"


def test_open_case_re_routes_but_keeps_the_prior_status():
    """Routing follows the alert's current severity; the status is the human's."""
    alert = _alert(provider="nagad")
    open_case(alert, now=2000.0,
              prior=(CaseStatus.ACKNOWLEDGED, "stale role", ""))
    assert alert.status is CaseStatus.ACKNOWLEDGED
    assert alert.owner == route(alert)[0], "routing should be re-derived"
    assert alert.assignee == route(alert)[1], "a blank assignee falls back"


def test_open_case_without_a_prior_is_new():
    case = open_case(_alert(), now=2000.0)
    assert case.status is CaseStatus.NEW
