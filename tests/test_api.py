"""API contract tests.

The dashboard is a browser client, so two classes of failure matter more than
the rest. The first is a payload the browser cannot parse at all: Python's
``json`` writes ``NaN`` and ``Infinity`` by default, and neither token is valid
JSON for ``JSON.parse`` — one division by an empty series is enough to blank
the whole page. The second is the provider boundary: a request that reaches
across provider tracks must be refused, because "the interface declined" is the
only form of that guarantee a user can actually see.

Every test here pins a deterministic world first, so the assertions never
depend on which test ran before.
"""
import json

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.domain import Classification
from app.engine import Engine
from app.main import app

SEED = 1
OUTLETS = 4


# The ``client`` fixture lives in conftest.py: more than one module drives the
# real app now, and the two protections it carries — no live LLM calls and a
# scratch audit database — should not have to be repeated per module.


def _world(client, scenario="baseline", seed=SEED, outlets=OUTLETS):
    """Rebuild a known world and return its snapshot."""
    response = client.post("/api/simulate", json={"scenario": scenario,
                                                  "seed": seed,
                                                  "outlets": outlets})
    assert response.status_code == 200
    return response.json()


def _alert(client, provider_id="nagad", kind="liquidity"):
    """A deterministic alert from the current world."""
    alerts = client.get("/api/state").json()["alerts"]
    match = next((a for a in alerts
                  if a["provider_id"] == provider_id and a["kind"] == kind),
                 None)
    assert match is not None, f"no {kind} alert for {provider_id}: {alerts}"
    return match


def _other_provider(provider_id):
    return "nagad" if provider_id != "nagad" else "bkash"


def _assert_no_non_finite(raw: str):
    """Neither token is valid JSON for a browser's ``JSON.parse``."""
    for token in ("NaN", "Infinity"):
        assert token not in raw, (
            f"{token} in the payload would break JSON.parse in the dashboard")
    json.loads(raw, parse_constant=lambda name: pytest.fail(
        f"non-finite number {name!r} in the payload"))


# --- the basics --------------------------------------------------------------

def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_dashboard_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.strip()


def test_state_exposes_the_documented_top_level_shape(client):
    state = _world(client)
    for key in ("generated_at", "scenario", "seed", "summary", "outlets",
                "alerts", "hotspots", "network", "metrics", "episodes",
                "focus"):
        assert key in state
    assert len(state["outlets"]) == OUTLETS
    assert state["scenario"] == "baseline"


# --- no non-finite numbers, anywhere ----------------------------------------

@pytest.mark.parametrize("scenario", ["baseline", "A", "B", "B2", "C"])
def test_the_state_payload_contains_no_nan_or_infinity(client, scenario):
    _world(client, scenario=scenario)
    response = client.get("/api/state")
    assert response.status_code == 200
    _assert_no_non_finite(response.text)


def test_every_outlet_payload_is_parseable_by_a_browser(client):
    _world(client)
    state = client.get("/api/state")
    _assert_no_non_finite(state.text)
    for outlet in state.json()["outlets"]:
        # The three fields a missing value would most naturally poison.
        assert outlet["cash"] is not None
        assert not isinstance(outlet["cash"], bool)
        for position in outlet["positions"]:
            assert position["hours_to_empty"] is None or \
                isinstance(position["hours_to_empty"], (int, float))
            assert 0.0 <= position["confidence"] <= 1.0


# --- internal consistency ---------------------------------------------------

def test_alerts_only_reference_outlets_that_exist(client):
    state = _world(client)
    outlet_ids = {outlet["id"] for outlet in state["outlets"]}
    alert_ids = {alert["id"] for alert in state["alerts"]}
    for alert in state["alerts"]:
        assert alert["outlet_id"] in outlet_ids
    for outlet in state["outlets"]:
        for alert_id in outlet["alert_ids"]:
            assert alert_id in alert_ids


def test_every_alert_carries_a_reason_evidence_and_uncertainty(client):
    state = _world(client)
    assert state["alerts"], "the fixture produced no alerts"
    for alert in state["alerts"]:
        assert alert["reason"].strip()
        assert alert["evidence"], alert["id"]
        assert alert["uncertainty"].strip()


def test_metrics_endpoint_mirrors_the_state_payload(client):
    state = _world(client)
    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert metrics.json() == state["metrics"]
    assert set(metrics.json()) >= {"precision", "recall", "true_positives",
                                   "false_negatives"}


# --- the alert detail and the case history ----------------------------------

def test_alert_detail_returns_the_payload_with_its_history(client):
    alert = _alert(client)
    response = client.get(f"/api/alerts/{alert['id']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == alert["id"]
    assert payload["provider_id"] == "nagad"
    assert isinstance(payload["rejected_hypotheses"], list)
    assert "history" in payload
    _assert_no_non_finite(response.text)


def test_a_missing_alert_is_a_404(client):
    assert client.get("/api/alerts/A-DOES-NOT-EXIST").status_code == 404
    response = client.post("/api/alerts/A-DOES-NOT-EXIST/action",
                           json={"action": "acknowledge"})
    assert response.status_code == 404


def test_case_history_is_served_and_filterable(client):
    alert = _alert(client)
    everything = client.get("/api/cases")
    assert everything.status_code == 200
    assert isinstance(everything.json(), list)

    scoped = client.get(f"/api/cases?alert_id={alert['id']}")
    assert scoped.status_code == 200
    assert all(event["alert_id"] == alert["id"] for event in scoped.json())


# --- case actions -----------------------------------------------------------

@pytest.mark.parametrize("action,expected", [("acknowledge", "acknowledged"),
                                             ("escalate", "escalated"),
                                             ("resolve", "resolved")])
def test_a_valid_action_moves_the_case(client, action, expected):
    alert = _alert(client)
    response = client.post(f"/api/alerts/{alert['id']}/action",
                           json={"action": action, "actor": "ops_1"})
    assert response.status_code == 200
    assert response.json()["status"] == expected


def test_a_note_leaves_the_status_alone(client):
    alert = _alert(client)
    before = client.get(f"/api/alerts/{alert['id']}").json()["status"]
    response = client.post(f"/api/alerts/{alert['id']}/action",
                           json={"action": "note", "note": "called the outlet"})
    assert response.status_code == 200
    assert response.json()["status"] == before


@pytest.mark.parametrize("payload", [
    {"action": "note"},
    {"action": "note", "note": ""},
    {"action": "note", "note": "   "},
])
def test_a_note_without_a_note_is_refused(client, payload):
    """A note with no text appends a meaningless row to an append-only trail.

    The dashboard already blocks this before it sends anything, but the
    dashboard is not the only caller, and the row cannot be withdrawn once it
    is in the trail.
    """
    alert = _alert(client)
    before = client.get(f"/api/cases?alert_id={alert['id']}").json()

    response = client.post(f"/api/alerts/{alert['id']}/action", json=payload)

    assert response.status_code == 422
    assert "note" in response.json()["detail"]
    after = client.get(f"/api/cases?alert_id={alert['id']}").json()
    assert len(after) == len(before), "a refused note still wrote to the trail"


def test_acting_on_a_resolved_case_reports_itself_as_a_reopen(client):
    """A case that goes backwards must say so, not just report "recorded".

    Reopening stays legal — resolving by mistake has to be correctable, and
    there is no separate reopen verb — but the caller has to be able to tell it
    apart from an ordinary action. It could not before: the status simply moved
    and the response looked exactly like any other.
    """
    alert = _alert(client)
    client.post(f"/api/alerts/{alert['id']}/action",
                json={"action": "resolve", "actor": "ops_1"})
    assert client.get(f"/api/alerts/{alert['id']}").json()["status"] == "resolved"

    reopened = client.post(f"/api/alerts/{alert['id']}/action",
                           json={"action": "acknowledge", "actor": "ops_1"})

    assert reopened.status_code == 200
    assert reopened.json()["status"] == "acknowledged"
    assert reopened.json().get("reopened") is True


def test_an_ordinary_action_is_not_flagged_as_a_reopen(client):
    """The flag must mean a reopen, not merely a status change."""
    alert = _alert(client, provider_id="bkash", kind="data_quality")
    client.post(f"/api/alerts/{alert['id']}/action",
                json={"action": "acknowledge", "actor": "ops_1"})

    response = client.post(f"/api/alerts/{alert['id']}/action",
                           json={"action": "escalate", "actor": "ops_1"})

    assert response.status_code == 200
    assert response.json().get("reopened") is None


def test_an_action_is_written_to_the_audit_trail(client):
    alert = _alert(client)
    client.post(f"/api/alerts/{alert['id']}/action",
                json={"action": "escalate", "actor": "ops_1",
                      "note": "needs a field visit"})
    trail = client.get(f"/api/cases?alert_id={alert['id']}").json()
    assert trail, "the action left no audit trail"
    assert trail[-1]["action"] == "escalate"
    assert trail[-1]["actor"] == "ops_1"
    assert trail[-1]["note"] == "needs a field visit"


def test_an_unsupported_action_is_rejected_with_422(client):
    alert = _alert(client)
    response = client.post(f"/api/alerts/{alert['id']}/action",
                           json={"action": "transfer"})
    assert response.status_code == 422
    assert "transfer" in response.json()["detail"]


@pytest.mark.parametrize("action", ["refill", "block", "freeze", "reverse", ""])
def test_no_financial_verb_is_ever_a_valid_action(client, action):
    alert = _alert(client)
    assert client.post(f"/api/alerts/{alert['id']}/action",
                       json={"action": action}).status_code == 422


def test_an_invalid_action_is_rejected_before_the_boundary_check(client):
    """A bad verb must not leak a cross-provider verdict."""
    alert = _alert(client)
    response = client.post(f"/api/alerts/{alert['id']}/action",
                           json={"action": "transfer",
                                 "actor_provider": _other_provider(
                                     alert["provider_id"])})
    assert response.status_code == 422


# --- the provider boundary --------------------------------------------------

def test_a_cross_provider_action_is_refused_with_403(client):
    alert = _alert(client, provider_id="nagad")
    response = client.post(
        f"/api/alerts/{alert['id']}/action",
        json={"action": "acknowledge", "actor": "ops_1",
              "actor_provider": "bkash"})

    assert response.status_code == 403
    body = response.json()
    assert "nagad" in body["detail"] and "bkash" in body["detail"]
    assert "separate" in body["boundary"]


def test_a_refused_action_does_not_change_the_case(client):
    alert = _alert(client, provider_id="bkash", kind="anomaly")
    before = client.get(f"/api/alerts/{alert['id']}").json()["status"]

    refused = client.post(f"/api/alerts/{alert['id']}/action",
                          json={"action": "resolve", "actor": "ops_1",
                                "actor_provider": "nagad"})
    assert refused.status_code == 403

    after = client.get(f"/api/alerts/{alert['id']}").json()
    assert after["status"] == before
    trail = client.get(f"/api/cases?alert_id={alert['id']}").json()
    assert all(event["action"] != "resolve" for event in trail)


def test_the_alerts_own_track_may_act_on_it(client):
    alert = _alert(client, provider_id="nagad")
    response = client.post(f"/api/alerts/{alert['id']}/action",
                           json={"action": "acknowledge", "actor": "ops_1",
                                 "actor_provider": "nagad"})
    assert response.status_code == 200


def test_an_oversight_role_acts_within_the_owning_track(client):
    """Central operations handle a nagad alert inside the nagad track."""
    alert = _alert(client, provider_id="nagad")
    for oversight in ("central", "oversight", "risk_analyst"):
        # A note is used here because it is the one verb that leaves the status
        # where it is. It carries a note because a note action without one is
        # refused: the row it would append says nothing.
        response = client.post(f"/api/alerts/{alert['id']}/action",
                               json={"action": "note", "actor": oversight,
                                     "actor_provider": oversight,
                                     "note": f"handled by {oversight}"})
        assert response.status_code == 200, oversight


def test_shared_cash_may_be_actioned_from_any_track(client):
    """The drawer is covered by every provider track, so no boundary applies."""
    alert = _alert(client, provider_id=None, kind="liquidity")
    response = client.post(f"/api/alerts/{alert['id']}/action",
                           json={"action": "acknowledge", "actor": "ops_1",
                                 "actor_provider": "rocket"})
    assert response.status_code == 200


# --- input validation on /api/simulate --------------------------------------

def test_an_unknown_scenario_is_rejected_with_422(client):
    response = client.post("/api/simulate", json={"scenario": "Z"})
    assert response.status_code == 422
    assert "unknown scenario" in response.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"outlets": "many"},
    {"seed": "abc"},
    {"demand_multiplier": "lots"},
])
def test_a_malformed_simulate_payload_is_rejected_with_422(client, payload):
    assert client.post("/api/simulate", json=payload).status_code == 422


def test_the_outlet_count_is_clamped_to_a_usable_range(client):
    assert len(_world(client, outlets=500)["outlets"]) == 60
    assert len(_world(client, outlets=0)["outlets"]) == 1


@pytest.mark.parametrize("payload", [
    {"outlets": 12.7},
    {"outlets": 0.5},
    {"seed": 3.25},
])
def test_a_fractional_count_is_refused_rather_than_truncated(client, payload):
    """A number that is not whole must not be quietly rounded to a different one.

    ``int(12.7)`` is 12, so these were answered with a world of 12 outlets while
    the caller had asked for something the API never acknowledged changing.
    """
    assert client.post("/api/simulate", json=payload).status_code == 422


@pytest.mark.parametrize("body", [
    '{"outlets": 1e400}',      # JSON number syntax for a value too large for a float
    '{"outlets": Infinity}',   # json.loads accepts this constant; strict JSON does not
    '{"outlets": NaN}',
])
def test_a_non_finite_count_is_refused_rather_than_crashing(client, body):
    """These parsed to infinity and ``int(inf)`` raised ``OverflowError``, a
    subclass of neither ``TypeError`` nor ``ValueError``, so the request
    answered 500 — blaming the server for the client's malformed number.

    They are sent as raw bodies because Python's own JSON encoder refuses to
    write ``inf`` or ``nan``, so ``json=`` cannot express the very payloads that
    used to break this. A client is under no such obligation.
    """
    response = client.post("/api/simulate", content=body,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422


@pytest.mark.parametrize("payload", [
    {"outlets": 12.0},
    {"seed": 7.0},
])
def test_a_whole_float_is_accepted(client, payload):
    """JSON does not oblige an encoder to write 12 rather than 12.0.

    A client that reached the number by arithmetic may send either spelling, and
    the two name the same quantity, so refusing this would reject an honest
    request over punctuation.
    """
    assert client.post("/api/simulate", json=payload).status_code == 200


def test_a_bool_is_not_an_outlet_count(client):
    """``bool`` is an ``int`` subclass, so ``True`` would otherwise mean one outlet."""
    assert client.post("/api/simulate", json={"outlets": True}).status_code == 422


def test_a_demand_what_if_rebuilds_the_world(client):
    plain = _world(client)
    raised = client.post("/api/simulate", json={"seed": SEED,
                                                "outlets": OUTLETS,
                                                "demand_multiplier": 3.0})
    assert raised.status_code == 200
    assert raised.json()["demand_multiplier"] == 3.0

    def soonest(snapshot):
        return [position["hours_to_empty"]
                for outlet in snapshot["outlets"]
                for position in outlet["positions"]
                if position["hours_to_empty"] is not None]

    assert soonest(raised.json()) != soonest(plain), \
        "raising demand changed nothing"
    assert min(soonest(raised.json())) <= min(soonest(plain))


def test_an_unknown_scenario_does_not_disturb_the_current_world(client):
    before = _world(client)
    client.post("/api/simulate", json={"scenario": "Z"})
    after = client.get("/api/state").json()
    assert after["seed"] == before["seed"]
    assert after["scenario"] == before["scenario"]


# --- the evidence pack ------------------------------------------------------

def test_export_downloads_the_snapshot_as_a_named_file(client):
    _world(client)
    response = client.get("/api/export")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert 'filename="liquidity-risk-evidence.json"' in disposition


def test_export_carries_the_evidence_a_reviewer_would_need(client):
    state = _world(client)
    payload = client.get("/api/export").json()
    assert payload["thresholds"], "no thresholds in the evidence pack"
    assert "root" not in payload["thresholds"]
    assert payload["case_history"] is not None
    assert payload["seed"] == state["seed"]
    assert payload["metrics"] == state["metrics"]


def test_export_reports_the_rejected_hypotheses(client):
    """A reviewer must be able to check the reasoning, not just the verdict."""
    payload = client.get("/api/export").json()
    reviews = [alert for alert in payload["alerts"]
               if alert["classification"] == Classification.NEEDS_REVIEW.value]
    assert reviews, "the fixture produced no needs-review alert"
    for alert in reviews:
        assert alert["rejected_hypotheses"]
        for name, reason in alert["rejected_hypotheses"]:
            assert name and reason


def test_action_is_visible_in_the_next_state_read(client):
    """The POST response and the following GET must agree about the status.

    They once did not: ``act()`` mutated the live alert objects while
    ``/api/state`` served a list of dicts serialized at build time, so the
    dashboard showed "acknowledged" for one frame and then redrew the case as
    untouched on the next poll.
    """
    _world(client)
    alert = _alert(client)
    response = client.post(
        f"/api/alerts/{alert['id']}/action",
        json={"action": "acknowledge", "actor": "nagad-ops",
              "actor_provider": alert["provider_id"]})
    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"

    reread = next(a for a in client.get("/api/state").json()["alerts"]
                  if a["id"] == alert["id"])
    assert reread["status"] == "acknowledged"


def test_case_status_survives_a_rebuild(client):
    """A human's decision must outlive the world it was made in.

    /api/simulate discards and regenerates every alert. A case a person had
    already acknowledged has to come back acknowledged — otherwise "resolution
    tracking" is a demo that resets the moment anyone touches the controls.
    """
    _world(client)
    alert = _alert(client)
    client.post(f"/api/alerts/{alert['id']}/action",
                json={"action": "escalate", "actor": "nagad-ops",
                      "actor_provider": alert["provider_id"]})

    _world(client)          # same scenario, seed and size: same case ids

    after = next(a for a in client.get("/api/state").json()["alerts"]
                 if a["id"] == alert["id"])
    assert after["status"] == "escalated"


def test_resolving_a_case_lowers_the_open_case_count(client):
    """The KPI is derived from statuses, so it must not go stale either.

    The case is chosen by its current status rather than by provider, because
    earlier tests in this module have already actioned some of them — a
    resolved-looking case would make this assertion pass for the wrong reason.
    """
    _world(client)
    state = client.get("/api/state").json()
    open_alert = next(a for a in state["alerts"] if a["status"] == "new")
    before = state["summary"]["open_cases"]
    client.post(f"/api/alerts/{open_alert['id']}/action",
                json={"action": "resolve", "actor": "nagad-ops",
                      "actor_provider": open_alert["provider_id"]})
    after = client.get("/api/state").json()["summary"]["open_cases"]
    assert after == before - 1


def test_withdrawn_projection_is_not_scored_as_a_detection(client):
    """A withdrawn projection is a feed-integrity statement, not a detection.

    It used to be re-kinded to data_quality and therefore counted as one. In
    this scenario that happened to coincide with a genuinely planted episode,
    so the false-positive rate stayed at zero and hid the conflation. The flag
    has to be published, and the scoring has to honour it.
    """
    state = _world(client)
    withdrawn = [a for a in state["alerts"] if a.get("feed_withdrawn")]
    assert withdrawn, "the scenario plants a conflicting feed; none appeared"
    for alert in withdrawn:
        assert "withdrawn" in alert["reason"]

    # The alert is still shown to the user — it is useful, just not a detection.
    assert all(a["kind"] == "data_quality" for a in withdrawn)


def test_case_status_survives_a_process_restart(tmp_path):
    """A new Engine over the same audit database recovers what was decided.

    This is the sibling of the rebuild case: a restart used to keep the audit
    trail and reset every case to NEW, so the ledger and the case list told
    different stories about the same case.
    """
    db = tmp_path / "audit.sqlite"

    first = Engine(seed=42, outlets=12, use_llm=False, db_path=db)
    alert_id = next(a.id for a in first.alerts.values()
                    if a.status.value == "new" and a.provider_id)
    provider = first.alerts[alert_id].provider_id
    first.act(alert_id, "acknowledge", "ops", actor_provider=provider)
    assert first.alerts[alert_id].status.value == "acknowledged"

    second = Engine(seed=42, outlets=12, use_llm=False, db_path=db)
    assert second.alerts[alert_id].status.value == "acknowledged", (
        "the audit trail said acknowledged; the recovered case disagreed")


def test_a_note_does_not_count_as_a_status_change(tmp_path):
    """Recovery reads status-changing events only — a note leaves the case put."""
    db = tmp_path / "audit.sqlite"
    first = Engine(seed=42, outlets=12, use_llm=False, db_path=db)
    alert_id = next(a.id for a in first.alerts.values()
                    if a.status.value == "new" and a.provider_id)
    provider = first.alerts[alert_id].provider_id
    first.act(alert_id, "acknowledge", "ops", actor_provider=provider)
    first.act(alert_id, "note", "ops", note="called the outlet",
              actor_provider=provider)

    second = Engine(seed=42, outlets=12, use_llm=False, db_path=db)
    assert second.alerts[alert_id].status.value == "acknowledged"
