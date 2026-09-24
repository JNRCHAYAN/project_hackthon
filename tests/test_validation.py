"""Tests for the validation harness itself.

Two things are checked here: that the harness runs and writes both artifacts,
and that the figures it reports are internally consistent with the rest of the
system. A harness that quietly reports a plausible-looking zero would be worse
than no harness at all, so the unmeasurable cases are exercised too — the
report must say "not measurable" rather than invent a number.
"""
import json

import pytest

from app import validation
from app.simulator import DRAIN_GAP, DRAIN_STEP, Simulator
from app.validation import evaluate, render_markdown, write_reports

SEEDS = (1, 2, 3)
# ৳2,100 debited every 5 minutes == ৳420 a minute, straight from the
# simulator's planting constants rather than from the projection under test.
PLANTED_RATE_PER_MINUTE = DRAIN_STEP / (DRAIN_GAP / 60.0)


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    """One full evaluation, shared by the assertions below."""
    scratch = tmp_path_factory.mktemp("audit")
    return evaluate(list(SEEDS), outlets=4, db_path=scratch / "audit.sqlite")


# --- shape ------------------------------------------------------------------

def test_evaluate_returns_all_required_metrics(report):
    for key in ("lead_time", "anomaly", "false_positive", "latency",
                "explanation_coverage"):
        assert key in report
    assert report["explanation_coverage"]["value"] == 1.0


def test_the_report_states_the_seeds_and_configuration_it_used(report):
    config = report["configuration"]
    assert config["seeds"] == list(SEEDS)
    assert config["outlets"] == 4
    assert config["providers_per_outlet"] == 3
    assert config["latency_outlets"] == validation.LATENCY_OUTLETS
    assert "disabled" in config["narration"]
    # The detector thresholds are recorded so a reader can tell what the
    # numbers were measured against.
    assert config["burst_window_minutes"] > 0
    assert 0 < config["narrow_spread_ratio"] < 1


def test_the_report_is_deterministic_apart_from_latency(report):
    again = evaluate(list(SEEDS), outlets=4)
    assert {k: v for k, v in again.items() if k != "latency"} == \
        {k: v for k, v in report.items() if k != "latency"}


def test_nothing_is_skipped_for_the_default_configuration(report):
    assert report["skipped"] == []


# --- metric 1: lead time ----------------------------------------------------

def test_every_seed_plants_exactly_one_shortage_and_all_are_detected(report):
    lead = report["lead_time"]
    assert lead["planted"] == len(SEEDS)
    assert lead["detected"] == len(SEEDS)
    assert lead["missed"] == 0
    assert lead["n"] == lead["detected"]
    assert len(lead["episodes"]) == len(SEEDS)


def test_lead_time_is_reported_in_minutes_and_within_the_alert_horizon(report):
    lead = report["lead_time"]
    horizon_minutes = report["configuration"]["alert_horizon_hours"] * 60
    for key in ("mean", "median", "min", "max"):
        assert lead[key] is not None
        assert 0 < lead[key] <= horizon_minutes
    assert lead["min"] <= lead["median"] <= lead["max"]


def test_lead_time_matches_the_planted_drain_rate():
    """Independent arithmetic on the simulator's own planting constants."""
    world = Simulator(seed=SEEDS[0], outlets=4).world()
    drained = [(outlet_id, pid)
               for outlet_id, state in world.items()
               for pid in state.positions
               if any("-drain-" in t.id for t in state.provider_txns(pid))]
    assert len(drained) == 1, f"expected one planted drain, got {drained}"
    outlet_id, pid = drained[0]

    position = world[outlet_id].positions[pid]
    expected_minutes = position.balance / PLANTED_RATE_PER_MINUTE

    report = evaluate([SEEDS[0]], outlets=4, latency_outlets=0,
                      latency_repeats=0)
    episode = next(e for e in report["lead_time"]["episodes"]
                   if e["outlet_id"] == outlet_id and e["provider_id"] == pid)
    assert episode["ground_truth_minutes"] == pytest.approx(expected_minutes,
                                                           abs=0.1)
    assert episode["alerted"] is True


def test_the_predicted_horizon_tracks_the_planted_one(report):
    """The estimator should recover the planted rate, not approximate it."""
    error = report["lead_time"]["prediction_error"]
    assert error["n"] == report["lead_time"]["detected"]
    assert error["mean"] is not None
    assert error["mean"] < 5.0, "the projection is off by more than 5 minutes"


# --- metric 2: the confusion matrix -----------------------------------------

def test_anomaly_metrics_have_precision_and_recall(report):
    anomaly = report["anomaly"]
    assert 0.0 <= anomaly["precision"] <= 1.0
    assert 0.0 <= anomaly["recall"] <= 1.0
    assert anomaly["tp"] + anomaly["fp"] + anomaly["fn"] >= 1


def test_the_confusion_matrix_is_arithmetically_consistent(report):
    anomaly = report["anomaly"]
    assert anomaly["precision"] == pytest.approx(
        anomaly["tp"] / (anomaly["tp"] + anomaly["fp"]))
    assert anomaly["recall"] == pytest.approx(
        anomaly["tp"] / (anomaly["tp"] + anomaly["fn"]))


def test_the_matrix_decomposes_into_the_detectors_that_produced_it(report):
    anomaly = report["anomaly"]
    by_detector = anomaly["by_detector"]
    assert set(by_detector) == {"anomaly", "data_quality"}
    for counts in by_detector.values():
        assert counts["tp"] + counts["fn"] == counts["expected"]
        assert counts["tp"] + counts["fp"] == counts["detected"]
    assert sum(c["tp"] for c in by_detector.values()) == anomaly["tp"]
    assert sum(c["fp"] for c in by_detector.values()) == anomaly["fp"]
    assert sum(c["fn"] for c in by_detector.values()) == anomaly["fn"]


def test_the_detector_catches_the_injected_anomaly(report):
    assert report["anomaly"]["by_detector"]["anomaly"]["tp"] >= 1


def test_the_harness_agrees_with_the_engines_own_scoring(report):
    """Reused, not re-derived: the two definitions must not drift apart."""
    scoring = report["anomaly"]["engine_scoring"]
    assert scoring["agrees_with_matrix"] is True
    assert (scoring["tp"], scoring["fp"], scoring["fn"]) == \
        (report["anomaly"]["tp"], report["anomaly"]["fp"],
         report["anomaly"]["fn"])


def test_every_planted_episode_is_accounted_for(report):
    expected = report["anomaly"]["expected_findings"]
    # One anomaly and one data-quality episode per seed with 4 outlets.
    assert expected == 2 * len(SEEDS)


# --- metric 3: false positives on legitimate surges -------------------------

def test_false_positive_rate_counts_eid_spikes(report):
    false_positive = report["false_positive"]
    assert "flagged" in false_positive and "normal_spikes" in false_positive
    assert false_positive["rate"] >= 0.0


def test_every_seed_plants_one_legitimate_surge(report):
    false_positive = report["false_positive"]
    assert false_positive["normal_spikes"] == len(SEEDS)
    assert false_positive["flagged"] <= false_positive["normal_spikes"]
    assert 0.0 <= false_positive["rate"] <= 1.0


def test_the_legitimate_surge_is_not_flagged(report, tmp_path):
    """Recall of 1.0 is worthless if the detector also flags Eid."""
    assert report["false_positive"]["flagged"] == 0
    assert report["false_positive"]["rate"] == 0.0


# --- metric 4: latency ------------------------------------------------------

def test_latency_is_measured_at_the_documented_volume(report):
    latency = report["latency"]
    assert latency["unit"] == "ms"
    assert f"{validation.LATENCY_OUTLETS} outlets" in latency["volume"]
    assert latency["snapshot"]["n"] == validation.LATENCY_REPEATS
    assert latency["per_outlet"]["n"] == validation.LATENCY_OUTLETS
    assert "Engine.rebuild" in latency["snapshot"]["measured_call"]


def test_latency_percentiles_are_ordered_and_plausible(report):
    latency = report["latency"]
    for series in (latency["snapshot"], latency["per_outlet"]):
        assert series["p50"] > 0.0
        assert series["p95"] >= series["p50"]
        assert series["p95"] < 30_000.0, "a snapshot build took over 30 seconds"


def test_latency_can_be_skipped_rather_than_faked():
    """No volume, no number — and the report says so."""
    report = evaluate(seeds=[1], outlets=4, latency_outlets=0, latency_repeats=0)
    latency = report["latency"]
    assert latency["snapshot"] == {"p50": None, "p95": None, "n": 0}
    assert latency["per_outlet"]["p50"] is None
    assert "disabled" in latency["note"]


def test_a_clock_mismatch_is_skipped_and_named(monkeypatch):
    """If the served snapshot and the planted series disagree about the time,
    the honest answer is no answer — a lead time derived from the pair would
    be plausible and wrong."""
    class Skewed(Simulator):
        def __post_init__(self):
            super().__post_init__()
            self.now += 60.0

    monkeypatch.setattr(validation, "Simulator", Skewed)
    report = evaluate(seeds=[1], outlets=4, latency_outlets=0, latency_repeats=0)

    assert report["skipped"] == [{"seed": 1, "reason": "snapshot clock does "
                                                      "not match the simulator clock"}]
    assert report["lead_time"]["planted"] == 0
    assert report["lead_time"]["mean"] is None
    assert "Skipped measurements" in render_markdown(report)


# --- metric 5: explanation coverage -----------------------------------------

def test_explanation_coverage_is_asserted_at_one(report):
    coverage = report["explanation_coverage"]
    assert coverage["value"] == 1.0
    assert coverage["uncovered"] == []
    assert coverage["asserted"] is True
    assert coverage["alerts"] > 0


def test_coverage_is_one_even_with_no_alerts():
    """Vacuously complete is still complete; it must not divide by zero."""
    report = evaluate(seeds=[], outlets=4, latency_outlets=0, latency_repeats=0)
    coverage = report["explanation_coverage"]
    assert coverage["value"] == 1.0
    assert coverage["alerts"] == 0
    assert coverage["uncovered"] == []


def test_a_missing_metric_is_reported_as_unmeasurable_not_as_zero():
    """The honesty rule: an empty seed set yields no numbers, not zeros."""
    report = evaluate(seeds=[], outlets=4, latency_outlets=0, latency_repeats=0)
    assert report["lead_time"]["n"] == 0
    assert report["lead_time"]["mean"] is None
    assert report["lead_time"]["planted"] == 0
    assert report["anomaly"]["precision"] is None
    assert report["anomaly"]["recall"] is None
    assert report["false_positive"]["rate"] is None
    assert report["false_positive"]["normal_spikes"] == 0
    assert report["limitations"]


# --- the markdown -----------------------------------------------------------

def test_markdown_contains_a_table_and_the_numbers(report):
    markdown = render_markdown(report)
    assert "|" in markdown
    assert "lead time" in markdown.lower()
    assert "false" in markdown.lower()
    for value in (report["anomaly"]["precision"],
                  report["explanation_coverage"]["value"]):
        assert str(value) in markdown


def test_markdown_states_the_configuration_and_the_limitations(report):
    markdown = render_markdown(report)
    assert "## Configuration" in markdown
    assert "## Limitations" in markdown
    assert "## How to read these" in markdown
    assert str(list(SEEDS)) in markdown
    assert "not measurable" not in markdown.split("## Results")[1].split(
        "## Confusion")[0]


def test_markdown_says_so_when_a_figure_could_not_be_measured():
    report = evaluate(seeds=[], outlets=4, latency_outlets=0, latency_repeats=0)
    markdown = render_markdown(report)
    assert "not measurable" in markdown


# --- writing the artifacts --------------------------------------------------

def test_write_reports_writes_both_files(report, tmp_path):
    json_path, md_path = write_reports(report, tmp_path)
    assert json_path.name == "metrics.json"
    assert md_path.name == "metrics.md"
    assert json_path.exists() and md_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["generated_by"] == \
        "python -m app.validation"
    assert "|" in md_path.read_text(encoding="utf-8")


def test_write_reports_is_utf8_safe_for_bengali_text(report, tmp_path):
    """The window default encoding is not UTF-8; the writer must not rely on it."""
    report = dict(report, limitations=[*report["limitations"],
                                       "বাংলা সীমাবদ্ধতা — verify"])
    json_path, md_path = write_reports(report, tmp_path)
    assert "বাংলা" in json_path.read_text(encoding="utf-8")
    assert "বাংলা" in md_path.read_text(encoding="utf-8")


def test_write_reports_creates_the_output_directory(tmp_path):
    target = tmp_path / "nested" / "data"
    json_path, _ = write_reports(evaluate(seeds=[1], outlets=3,
                                          latency_outlets=0,
                                          latency_repeats=0), target)
    assert json_path.exists()


def test_main_writes_the_deliverables_and_reports_coverage(monkeypatch,
                                                            tmp_path, capsys):
    """The documented invocation, redirected away from the real data/ dir."""
    monkeypatch.setattr(validation, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(validation, "DEFAULT_SEEDS", (1, 2))

    validation.main()

    printed = capsys.readouterr().out
    assert "Measured Validation Evidence" in printed
    assert "Written to" in printed
    assert (tmp_path / "metrics.json").exists()
    assert "Explanation coverage" in (tmp_path / "metrics.md").read_text(
        encoding="utf-8")
