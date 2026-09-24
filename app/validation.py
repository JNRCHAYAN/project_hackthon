"""Validation harness — measured evidence, not asserted claims.

The product makes five quantitative claims (spec §9). This module is the only
place where they are produced, and it is written to a single rule:

    every figure is computed from a real run of the real code, or it is
    reported as unmeasurable.

Nothing here is hard-coded and nothing here asserts a quality value. The
scoring is possible at all only because :mod:`app.simulator` plants situations
and records the truth about them up front, so "did we catch the thing we
planted?" has an answer that does not depend on the detector's own opinion.

What is measured, and how
-------------------------
1. **Shortage detection lead time** — the simulator's Scenario A drains one
   provider balance at a rate it knows exactly. The ground-truth exhaustion
   horizon is recovered from that *planted series* (median pairwise slope of
   the injected debits, which is arithmetic on the planted data, not a call
   into the detector), and the predicted horizon is read off the projection
   the API actually serves. Lead time is therefore advance warning measured
   against recorded ground truth.
2. **Anomaly precision / recall** — a confusion matrix against the labelled
   episodes. The headline counts are the ones the engine already computes
   server-side in ``snapshot['metrics']``, summed across seeds; the
   per-detector split is read off the alerts the engine emitted. Detection is
   never re-implemented here.
3. **False-positive rate** — of the deliberately *legitimate* Eid-window
   surges, how many were flagged as a pattern requiring review. A detector
   that flags everything scores perfect recall and fails this one.
4. **Latency p50 / p95** — timed at the volume the spec names, 200 outlets x 3
   providers, against the real snapshot path (``Engine.rebuild``, the exact
   call that produces ``/api/state``) and against the per-outlet analytics
   pass. No ``sleep``, no synthetic delay.
5. **Alert explanation coverage** — the fraction of alerts reaching a user
   carrying a reason, its evidence, and an uncertainty statement. This is a
   completeness invariant rather than a quality measurement, so it is the one
   figure this harness is allowed to assert.

Honesty rules this module obeys
-------------------------------
* A seed whose ground truth cannot be paired with a served projection is
  skipped and named in ``skipped``, never counted as zero and never guessed.
* A shortage the detector missed contributes no lead time — it is reported as
  a miss, because dropping it would quietly inflate the average.
* Latency is the one machine-dependent figure; everything else is
  deterministic for a fixed seed set.

The harness never touches the network: narration is requested with the LLM
layer disabled, so a measurement run cannot depend on an API being up.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.anomaly import scan as scan_anomalies
from app.config import SETTINGS
from app.context import calendar_context, classify
from app.engine import Engine
from app.liquidity import project_outlet, theil_sen
from app.simulator import HOUR, Simulator

REPORT_DIR = Path(__file__).resolve().parent.parent / "data"

# The volume the spec fixes for the latency measurement: 200 outlets, each
# carrying three provider balances plus the shared drawer.
LATENCY_OUTLETS = 200
LATENCY_REPEATS = 5
LATENCY_SEED = 1

# The seeds the deliverable report is generated from. Fixed so the published
# numbers are reproducible exactly.
DEFAULT_SEEDS = (1, 2, 3, 4, 5)
DEFAULT_OUTLETS = 8

# The simulator tags its injected drain series with this marker.
_DRAIN_MARKER = "-drain-"


# --- small numeric helpers --------------------------------------------------

def _percentile(ordered: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile of an already-sorted sample.

    Documented rather than interpolated on purpose: with the sample sizes here
    (5 snapshot builds) an interpolated p95 would imply more precision than the
    measurement has.
    """
    if not ordered:
        return None
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def _summary(values: list[float], digits: int = 2) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), digits),
        "median": round(statistics.median(values), digits),
        "min": round(min(values), digits),
        "max": round(max(values), digits),
    }


# --- metric 1: ground truth for the planted shortage -------------------------

def _planted_drains(world: dict, now: float) -> list[dict]:
    """The provider balances the simulator deliberately drained.

    Located by the simulator's own marker on its injected series rather than by
    hard-coding which outlet Scenario A lands on, so a change to the planting
    order cannot silently invalidate the measurement. The drain *rate* is then
    recovered from the planted debits alone — a robust fit over the injected
    chain, with no call into the detector being measured.
    """
    found: list[dict] = []
    for outlet_id in sorted(world):
        state = world[outlet_id]
        for pid, pos in sorted(state.positions.items()):
            series = sorted((t for t in state.provider_txns(pid)
                             if _DRAIN_MARKER in t.id), key=lambda t: t.ts)
            if len(series) < 2:
                continue
            balance = pos.opening_balance
            points = []
            for txn in series:
                balance += txn.emoney_delta()
                points.append((txn.ts / HOUR, balance))
            rate = -theil_sen(points).slope          # positive == draining
            if rate <= 0:
                continue
            found.append({
                "outlet_id": outlet_id,
                "provider_id": pid,
                "planted_series": len(series),
                "ground_truth_rate_per_hour": round(rate, 2),
                "ground_truth_hours": round(pos.balance / rate, 4),
                "ground_truth_exhaustion_ts": now + (pos.balance / rate) * HOUR,
            })
    return found


def _lead_time(seed: int, sim: Simulator,
               snapshot: dict) -> tuple[list[dict], dict | None]:
    """Advance warning at detection for every planted provider shortage."""
    world = sim.world()
    if snapshot.get("generated_at") != sim.now:
        # Without a shared clock the served projection and the planted series
        # describe different instants; a number derived from them would be
        # plausible and wrong, which is the one outcome worth avoiding.
        return [], {"seed": seed, "reason": "snapshot clock does not match the "
                                           "simulator clock"}

    rows = {row["id"]: row for row in snapshot["outlets"]}
    alerts = {a["id"] for a in snapshot["alerts"]}

    episodes: list[dict] = []
    for drain in _planted_drains(world, sim.now):
        outlet_id, pid = drain["outlet_id"], drain["provider_id"]
        served = next((p for p in rows.get(outlet_id, {}).get("positions", [])
                       if p["provider_id"] == pid), None)
        predicted = served["hours_to_empty"] if served else None
        # A shortage counts as detected only if an alert for *this* balance
        # reached the surface with a horizon attached to it.
        alerted = (predicted is not None
                   and f"A-{outlet_id}-liquidity-{pid}" in alerts)
        episodes.append({
            "seed": seed,
            "outlet_id": outlet_id,
            "provider_id": pid,
            "ground_truth_minutes": round(drain["ground_truth_hours"] * 60, 2),
            "predicted_minutes": (round(predicted * 60, 2)
                                  if predicted is not None else None),
            "alerted": alerted,
        })
    return episodes, None


# --- metrics 2 and 3: the confusion matrix and the false-positive rate -------

def _confusion(snapshot: dict) -> dict:
    """Per-detector true/false positives and false negatives for one world.

    The pairing rule is the engine's own (``Engine._score``): an expected
    finding is an ``(outlet, label)`` pair from the simulator's ground truth,
    and a detected finding is an ``(outlet, kind)`` pair from the alerts the
    engine emitted. Only the pairing is mirrored — the detection itself is the
    engine's, taken straight from its alert list.

    A withdrawn projection is excluded, exactly as the engine excludes it: an
    alert saying a feed cannot be trusted is a statement about data integrity,
    not a finding about activity. Counting it here while the engine does not
    would publish a false positive the engine never claimed, and would break
    the ``agrees_with_matrix`` invariant below — which is the whole point of
    carrying both numbers side by side.
    """
    counts: dict[str, dict[str, int]] = {}
    for label in ("anomaly", "data_quality"):
        expected = {e["outlet_id"] for e in snapshot["episodes"]
                    if e["label"] == label}
        detected = {a["outlet_id"] for a in snapshot["alerts"]
                    if a["kind"] == label and not a.get("feed_withdrawn")}
        counts[label] = {
            "expected": len(expected),
            "detected": len(detected),
            "tp": len(expected & detected),
            "fp": len(detected - expected),
            "fn": len(expected - detected),
        }
    return counts


def _flagged_as_suspicious(snapshot: dict) -> int:
    """Legitimate surge episodes that were flagged for human review.

    Attributed strictly to the episode's own ``(outlet, provider)``: an
    unrelated liquidity alert on the same outlet is a different finding and is
    not counted against the surge.
    """
    flagged = 0
    for episode in snapshot["episodes"]:
        if episode["label"] != "demand_spike":
            continue
        if any(a["kind"] == "anomaly"
               and a["outlet_id"] == episode["outlet_id"]
               and a["provider_id"] == episode["provider_id"]
               for a in snapshot["alerts"]):
            flagged += 1
    return flagged


# --- metric 4: latency at the documented volume ------------------------------

def _latency(outlets: int, repeats: int, seed: int,
             db_path: Any) -> dict:
    """Time the real snapshot path and the real per-outlet analytics pass.

    ``Engine.rebuild`` is timed because it is the exact call that produces the
    ``/api/state`` payload — the figure a user actually waits on. The
    per-outlet pass is timed separately because it explains that number and
    because 200 samples support a p95 where five do not.
    """
    if outlets < 1 or repeats < 1:
        return {"unit": "ms", "volume": f"{outlets} outlets x 3 providers",
                "snapshot": {"p50": None, "p95": None, "n": 0},
                "per_outlet": {"p50": None, "p95": None, "n": 0},
                "note": "latency measurement disabled for this configuration"}

    engine = Engine(seed=seed, outlets=outlets, use_llm=False, db_path=db_path)
    snapshot_times: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        engine.rebuild()
        snapshot_times.append((time.perf_counter() - started) * 1000.0)
    snapshot_times.sort()

    # A second, independent build of the same deterministic world, so the
    # analytics core can be timed outlet by outlet without the aggregation and
    # network work that the snapshot figure already covers.
    sim = Simulator(seed=seed, outlets=outlets)
    world = sim.world()
    now = sim.now
    ctx = calendar_context(now)
    per_outlet: list[float] = []
    for state in world.values():
        started = time.perf_counter()
        project_outlet(state, now)
        for signal in scan_anomalies(state, now):
            classify(signal, state.transactions, ctx)
        per_outlet.append((time.perf_counter() - started) * 1000.0)
    per_outlet.sort()

    return {
        "unit": "ms",
        "volume": f"{outlets} outlets x 3 providers "
                  f"({len(world)} drawers + {len(world) * 3} provider balances)",
        "snapshot": {
            "p50": round(_percentile(snapshot_times, 0.50), 3),
            "p95": round(_percentile(snapshot_times, 0.95), 3),
            "n": len(snapshot_times),
            "measured_call": "Engine.rebuild() — the call behind GET /api/state",
        },
        "per_outlet": {
            "p50": round(_percentile(per_outlet, 0.50), 3),
            "p95": round(_percentile(per_outlet, 0.95), 3),
            "n": len(per_outlet),
            "measured_call": "project_outlet + anomaly scan + context classify",
        },
        "note": ("Measured on the host that ran the harness; the only "
                 "machine-dependent figure in this report."),
    }


# --- metric 5: explanation completeness --------------------------------------

def _explanation_coverage(snapshots: Iterable[dict]) -> dict:
    """Every alert must carry a reason, its evidence, and an uncertainty.

    Checked on the served alert payload rather than on the internal objects,
    because the payload is what reaches a human.
    """
    total = 0
    uncovered: list[dict] = []
    for snapshot in snapshots:
        for alert in snapshot["alerts"]:
            total += 1
            missing = [field for field in ("reason", "evidence", "uncertainty")
                       if not alert.get(field)]
            if missing:
                uncovered.append({"id": alert["id"], "missing": missing})
    return {
        "unit": "fraction of alerts carrying reason + evidence + uncertainty",
        "value": round((total - len(uncovered)) / total, 3) if total else 1.0,
        "alerts": total,
        "uncovered": uncovered,
        "asserted": True,
        "note": ("A completeness invariant, not a quality measurement, so it "
                 "is the one figure this harness asserts at 1.0."),
    }


# --- the harness -------------------------------------------------------------

def evaluate(seeds: Sequence[int] = DEFAULT_SEEDS,
             outlets: int = DEFAULT_OUTLETS,
             *, latency_outlets: int = LATENCY_OUTLETS,
             latency_repeats: int = LATENCY_REPEATS,
             db_path: Any = None) -> dict:
    """Measure all five metrics over the given seeds.

    ``db_path`` only decides where the case audit trail is opened; the harness
    writes no case events, so callers may point it at a scratch file.
    """
    seed_list = list(seeds)
    snapshots: list[dict] = []
    detection: list[float] = []
    prediction_errors: list[float] = []
    episodes: list[dict] = []
    skipped: list[dict] = []
    planted = detected = 0
    counts = {label: {"expected": 0, "detected": 0, "tp": 0, "fp": 0, "fn": 0}
              for label in ("anomaly", "data_quality")}
    engine_counts = {"tp": 0, "fp": 0, "fn": 0}
    normal_spikes = 0
    surge_flagged = 0

    for seed in seed_list:
        # The engine does not expose its world, and ground truth lives in the
        # simulator, so the world is rebuilt here from the same seed — the
        # simulator is deterministic, so this is the same world the engine saw.
        sim = Simulator(seed=seed, outlets=outlets)
        engine = Engine(seed=seed, outlets=outlets, use_llm=False,
                        db_path=db_path)
        snapshot = engine.snapshot
        snapshots.append(snapshot)

        seed_episodes, skip = _lead_time(seed, sim, snapshot)
        if skip is not None:
            skipped.append(skip)
        episodes.extend(seed_episodes)
        for entry in seed_episodes:
            planted += 1
            if entry["alerted"]:
                detected += 1
                detection.append(entry["ground_truth_minutes"])
                prediction_errors.append(
                    abs(entry["predicted_minutes"] - entry["ground_truth_minutes"]))

        for label, row in _confusion(snapshot).items():
            for key, value in row.items():
                counts[label][key] += value

        # The engine already scores itself against the same ground truth; its
        # numbers are summed rather than recomputed, so the harness cannot
        # drift away from the value the API reports.
        server = snapshot["metrics"]
        engine_counts["tp"] += server["true_positives"]
        engine_counts["fp"] += server["false_positives"]
        engine_counts["fn"] += server["false_negatives"]

        normal_spikes += sum(1 for e in snapshot["episodes"]
                             if e["label"] == "demand_spike")
        surge_flagged += _flagged_as_suspicious(snapshot)

    tp = sum(row["tp"] for row in counts.values())
    fp = sum(row["fp"] for row in counts.values())
    fn = sum(row["fn"] for row in counts.values())
    detection.sort()
    prediction_errors.sort()
    lead_stats = _summary(detection)

    report = {
        "generated_by": "python -m app.validation",
        "configuration": {
            "seeds": seed_list,
            "outlets": outlets,
            "providers_per_outlet": 3,
            "latency_outlets": latency_outlets,
            "latency_repeats": latency_repeats,
            "latency_seed": LATENCY_SEED,
            "narration": "LLM disabled — deterministic, no network access",
            "trailing_window_minutes": SETTINGS["trailing_window_minutes"],
            "alert_horizon_hours": SETTINGS["alert_horizon_hours"],
            "burst_window_minutes": SETTINGS["burst_window_minutes"],
            "burst_amount_tolerance": SETTINGS["burst_amount_tolerance"],
            "burst_max_accounts": SETTINGS["burst_max_accounts"],
            "demand_spike_account_floor": SETTINGS["demand_spike_account_floor"],
            "narrow_spread_ratio": SETTINGS["narrow_spread_ratio"],
        },
        "lead_time": {
            "unit": "minutes of advance warning at detection",
            "mean": lead_stats["mean"],
            "median": lead_stats["median"],
            "min": lead_stats["min"],
            "max": lead_stats["max"],
            "n": lead_stats["n"],
            "planted": planted,
            "detected": detected,
            "missed": planted - detected,
            "prediction_error": {
                "unit": "minutes of absolute error in the predicted horizon",
                **_summary(prediction_errors),
            },
            "episodes": episodes,
            "note": ("Ground truth is the exhaustion horizon implied by the "
                     "simulator's injected drain series; the predicted horizon "
                     "is the one the API serves. A missed detection "
                     "contributes no lead time and is counted as a miss."),
        },
        "anomaly": {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 3) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 3) if (tp + fn) else None,
            "expected_findings": sum(r["expected"] for r in counts.values()),
            "detected_findings": sum(r["detected"] for r in counts.values()),
            "by_detector": counts,
            "engine_scoring": {
                **engine_counts,
                "agrees_with_matrix": engine_counts == {"tp": tp, "fp": fp,
                                                        "fn": fn},
                "note": "snapshot['metrics'] summed over seeds — the engine's "
                        "own scoring, carried here so the figure the API "
                        "serves is visible in the evidence pack.",
            },
            "note": ("Pairing rule mirrors Engine._score: an expected finding "
                     "is an (outlet, label) pair from the simulator's ground "
                     "truth, a detected finding an (outlet, kind) pair from "
                     "the alerts actually emitted. Detection is never "
                     "re-implemented in this module."),
        },
        "false_positive": {
            "flagged": surge_flagged,
            "normal_spikes": normal_spikes,
            "rate": (round(surge_flagged / normal_spikes, 3)
                     if normal_spikes else None),
            "note": ("Counted against the simulator's deliberate Eid-window "
                     "surges — many distinct accounts, wide amount spread. "
                     "Attributed strictly to the episode's own (outlet, "
                     "provider); an unrelated liquidity alert on the same "
                     "outlet is not held against the surge."),
        },
        "latency": _latency(latency_outlets, latency_repeats, LATENCY_SEED,
                            db_path),
        "explanation_coverage": _explanation_coverage(snapshots),
        "skipped": skipped,
        "limitations": [
            "Lead time is measured only for the simulator's planted provider "
            "drain: it is the only shortage in the world with recorded ground "
            "truth, so no lead time is claimed for shortfalls that merely look "
            "plausible.",
            "Precision, recall and the false-positive rate are measured "
            "against synthetic injected episodes. They describe the "
            "detectors' behaviour on this simulator, not on production "
            "traffic.",
            "Latency was measured on the host that ran the harness and is the "
            "only non-deterministic figure in this report.",
        ],
    }
    return report


# --- rendering ---------------------------------------------------------------

def _fmt(value: Any, suffix: str = "") -> str:
    """Render a figure, or say plainly that it could not be measured."""
    if value is None:
        return "not measurable"
    return f"{value}{suffix}"


def render_markdown(report: dict) -> str:
    """The human-readable form: a table plus what the table does not say."""
    cfg = report["configuration"]
    lt = report["lead_time"]
    an = report["anomaly"]
    fp_ = report["false_positive"]
    lat = report["latency"]
    cov = report["explanation_coverage"]

    def detector_row(label: str) -> str:
        row = an["by_detector"][label]
        return (f"| {label.replace('_', ' ')} | {row['expected']} | "
                f"{row['detected']} | {row['tp']} | {row['fp']} | {row['fn']} |")

    lines = [
        "# Measured Validation Evidence",
        "",
        "Generated by `python -m app.validation` over seeded synthetic "
        "scenarios. Every figure below is produced by the harness, not "
        "asserted.",
        "",
        "## Configuration",
        "",
        f"- Seeds: `{cfg['seeds']}` over {cfg['outlets']} outlets x "
        f"{cfg['providers_per_outlet']} providers",
        f"- Latency volume: {lat['volume']}, "
        f"{cfg['latency_repeats']} snapshot builds (seed {cfg['latency_seed']})",
        f"- Narration: {cfg['narration']}",
        f"- Detector thresholds: burst window "
        f"{cfg['burst_window_minutes']} min, amount tolerance "
        f"{cfg['burst_amount_tolerance']:.0%}, max accounts "
        f"{cfg['burst_max_accounts']}, demand-spike account floor "
        f"{cfg['demand_spike_account_floor']}, narrow-spread ratio "
        f"{cfg['narrow_spread_ratio']}",
        "",
        "## Results",
        "",
        "| Metric | Value | Notes |",
        "|---|---|---|",
        f"| Shortage detection lead time (mean) | "
        f"{_fmt(lt['mean'], ' min')} | advance warning at detection; "
        f"{lt['detected']} of {lt['planted']} planted shortages detected |",
        f"| Shortage detection lead time (median) | "
        f"{_fmt(lt['median'], ' min')} | n={lt['n']} |",
        f"| Predicted-horizon error (mean) | "
        f"{_fmt(lt['prediction_error']['mean'], ' min')} | absolute error "
        f"against the planted drain rate |",
        f"| Anomaly precision | {_fmt(an['precision'])} | tp={an['tp']} "
        f"fp={an['fp']} |",
        f"| Anomaly recall | {_fmt(an['recall'])} | fn={an['fn']} |",
        f"| False-positive rate on legitimate surges | "
        f"{_fmt(fp_['rate'])} | {fp_['flagged']} of {fp_['normal_spikes']} "
        f"planted Eid-window surges wrongly flagged for review |",
        f"| Latency p50 / p95 (full snapshot) | "
        f"{_fmt(lat['snapshot']['p50'])} / {_fmt(lat['snapshot']['p95'])} ms | "
        f"n={lat['snapshot']['n']} at {lat['volume']} |",
        f"| Latency p50 / p95 (per outlet) | "
        f"{_fmt(lat['per_outlet']['p50'])} / "
        f"{_fmt(lat['per_outlet']['p95'])} ms | "
        f"n={lat['per_outlet']['n']} |",
        f"| Alert explanation coverage | {cov['value']:.3f} | fraction of "
        f"alerts carrying reason + evidence + uncertainty; {cov['alerts']} "
        f"alerts |",
        "",
        "## Confusion matrix by detector",
        "",
        "| Detector | Expected | Detected | TP | FP | FN |",
        "|---|---|---|---|---|---|",
        detector_row("anomaly"),
        detector_row("data_quality"),
        "",
        "## How to read these",
        "",
        "- **Lead time** is the advance warning available when a depletion "
        "alert fires, measured against the exhaustion horizon implied by the "
        "rate the simulator actually planted. Higher is better; a missed "
        "shortage yields no lead time and is reported as a miss rather than "
        "dropped from the average.",
        "- **Precision** answers \"when we flag, how often are we right\"; "
        "**recall** answers \"of the cases that were genuinely planted, how "
        "many did we catch\".",
        "- **False-positive rate** is measured against deliberately injected "
        "*legitimate* Eid-window surges. A detector that flags everything "
        "scores perfect recall and fails here.",
        "- **Latency** is measured on the real snapshot path at the volume the "
        "spec names, not simulated with a delay.",
        "- **Explanation coverage** is asserted at 1.000: no alert may reach a "
        "user without a reason, its evidence, and an uncertainty statement.",
    ]

    if lt["episodes"]:
        lines += [
            "",
            "## Per-episode detail",
            "",
            "| Seed | Outlet | Provider | Ground truth (min) | Predicted (min) "
            "| Alerted |",
            "|---|---|---|---|---|---|",
        ]
        for entry in lt["episodes"]:
            lines.append(
                f"| {entry['seed']} | {entry['outlet_id']} | "
                f"{entry['provider_id']} | {entry['ground_truth_minutes']} | "
                f"{_fmt(entry['predicted_minutes'])} | "
                f"{'yes' if entry['alerted'] else 'no'} |")

    if report["skipped"]:
        lines += ["", "## Skipped measurements", ""]
        for skip in report["skipped"]:
            lines.append(f"- seed {skip['seed']}: {skip['reason']}")

    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in report["limitations"]]
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict,
                  output_dir: Path | None = None) -> tuple[Path, Path]:
    """Write the JSON and markdown forms of a report. Returns both paths."""
    target = Path(output_dir) if output_dir else REPORT_DIR
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "metrics.json"
    md_path = target / "metrics.md"
    # UTF-8 is explicit: the markdown and the alert text inside the report
    # carry Bengali, and the default encoding on Windows does not.
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    report = evaluate(list(DEFAULT_SEEDS), DEFAULT_OUTLETS)
    json_path, md_path = write_reports(report)

    coverage = report["explanation_coverage"]
    if coverage["value"] < 1.0:
        # The one invariant this harness asserts. An alert without a reason,
        # its evidence or its uncertainty must never reach a user, so a
        # regression here is a genuine failure and exits non-zero.
        raise SystemExit(
            f"FAIL: explanation coverage {coverage['value']:.3f} < 1.0 — "
            f"alerts missing parts: {coverage['uncovered']}")

    print(render_markdown(report))
    print(f"\nWritten to {json_path} and {md_path}")


if __name__ == "__main__":
    main()
