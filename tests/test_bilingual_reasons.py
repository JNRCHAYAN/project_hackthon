"""Every alert must carry its one-line reason in both languages.

The queue prints ``reason`` as each alert's triage line and the dashboard is
Bengali by default, so an English-only reason put an English sentence in the
middle of the Bengali queue. The engine builds the reason inline at several
separate sites, which is exactly the shape of code where one site gets updated
and the others do not — so this checks the whole catalogue rather than one
alert, across every scenario rather than one world.
"""
from __future__ import annotations

import re

import pytest

from app.domain import Alert
from app.simulator import AREAS, PROVIDERS

BENGALI = re.compile(r"[ঀ-৿]")
ASCII_WORD = re.compile(r"[A-Za-z]{3,}")


def _allowed_latin() -> set[str]:
    """Latin words that legitimately appear inside Bengali prose.

    Place and provider names are not transliterated in this product — the
    Bengali narrative for a coordination alert reads "Sylhet এলাকার ৩টি শাখায়",
    keeping the name as written — so a bare proper noun is not an untranslated
    sentence. They are read from the simulator rather than listed here so that
    adding an area cannot start failing this test for the wrong reason.
    """
    names = {"Outlet"}
    for area, thana, district, _lat, _lon in AREAS:
        names.update({area, thana, district})
    for provider in PROVIDERS:
        names.add(provider.name)
    return names

SCENARIOS = ["baseline", "A", "B", "B2", "C"]
SEEDS = [1, 7, 42]
OUTLET_COUNTS = [4, 12]


def _world(client, scenario: str, seed: int, outlets: int) -> dict:
    response = client.post("/api/simulate", json={"scenario": scenario,
                                                  "seed": seed,
                                                  "outlets": outlets})
    assert response.status_code == 200, response.text
    return response.json()


def _all_alerts(client) -> list[dict]:
    """Every alert from every scenario, seed and size this test covers."""
    seen: dict[str, dict] = {}
    for scenario in SCENARIOS:
        for seed in SEEDS:
            for outlets in OUTLET_COUNTS:
                snapshot = _world(client, scenario, seed, outlets)
                for alert in snapshot["alerts"]:
                    seen[alert["id"]] = alert
    return list(seen.values())


@pytest.fixture(scope="module")
def alerts(client) -> list[dict]:
    found = _all_alerts(client)
    assert found, "no alerts were produced, so this test would pass vacuously"
    return found


def test_every_alert_has_a_english_reason(alerts):
    for alert in alerts:
        assert alert["reason"].strip(), f"{alert['id']} has no reason"


def test_every_alert_has_a_bengali_reason(alerts):
    missing = sorted(a["id"] for a in alerts if not a.get("reason_bn", "").strip())
    assert not missing, f"alerts with no Bengali reason: {missing}"


def test_every_bengali_reason_is_actually_bengali(alerts):
    """A copy of the English text would satisfy "non-empty" and help nobody."""
    wrong = sorted(a["id"] for a in alerts
                   if not BENGALI.search(a.get("reason_bn", "")))
    assert not wrong, f"Bengali reason has no Bengali script: {wrong}"


def test_no_bengali_reason_keeps_an_english_sentence(alerts):
    """A leftover English sentence is the failure; a proper noun is not.

    The Bengali text below is the one that used to sit in the queue in English —
    "feed data cannot be trusted". A run of Latin words is what that looks like,
    so every Latin word that is not an area, thana, district or provider name is
    reported.
    """
    allowed = _allowed_latin()
    offenders = []
    for alert in alerts:
        words = [w for w in ASCII_WORD.findall(alert.get("reason_bn", ""))
                 if w not in allowed]
        if words:
            offenders.append((alert["id"], words))
    assert not offenders, f"English words left in Bengali reasons: {offenders}"


def test_the_two_reasons_are_different_text(alerts):
    """Identical strings mean the Bengali field was filled with the English one."""
    same = sorted(a["id"] for a in alerts if a["reason"] == a["reason_bn"])
    assert not same, f"Bengali reason is a copy of the English: {same}"


def test_the_alert_dataclass_defaults_the_bengali_reason_empty():
    """A new alert built without a Bengali reason must be valid, not a crash.

    ``Alert`` is constructed with keyword arguments in several places, so the
    field has to have a default for those sites to keep working.
    """
    alert = Alert(id="A", outlet_id="AG-1", provider_id=None,
                  kind="liquidity", severity="low", confidence=0.0,
                  reason="english only")
    assert alert.reason_bn == ""
