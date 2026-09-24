# Super Agent Liquidity & Risk Intelligence Platform

**Codex Community Hackathon — bKash presents SUST CSE Carnival 2026**

A decision-support prototype for a multi-provider mobile financial service (MFS) *super agent*:
one physical cash drawer, three logically separate provider e-money balances
(bKash, Nagad, Rocket), and three connected operational problems — liquidity pressure,
unusual activity, and coordination.

> **This prototype executes no financial transaction, connects to no provider system, and
> makes no fraud determination.** All data is synthetic. Risk signals are advisory and
> require human review.

**Deployment:** the repository ships deploy-ready for Render's free tier (`render.yaml`).
Creating the service needs a Render account, so it is a documented manual step — see
[`DEPLOYMENT.md`](DEPLOYMENT.md), which also covers cold-start behaviour and the
ephemeral-storage limitation.

---

## The core insight

An agent's shared cash and each provider's e-money move in **opposite directions**:

| Customer action | Shared cash | That provider's e-money |
|---|---|---|
| **Cash-out** (takes cash, sends e-money) | decreases | increases |
| **Cash-in** (gives cash, takes e-money) | increases | decreases |

Two consequences drive the entire design:

1. **Aggregate health is misleading.** Total value can look comfortable while one provider is
   hours from exhaustion. A single summed figure is an actively dangerous metric — which is why
   this product never shows only a total.
2. **Cross-provider imbalance is structural, not a bug.** Cash accumulated from one provider's
   cash-out cannot replenish another provider's e-money — that is settlement, and it is out of
   scope. Because conversion is impossible, the only correct remedy is an approved-channel
   balance arrangement *before* the projected exhaustion time.

The guardrail generates the recommendation. That is the product.

---

## What it does

- **Unified view** — shared cash plus each provider's e-money balance, kept visibly separate.
- **Forward liquidity** — robust drain-rate estimation with an interval, not a false point
  estimate: *"exhausted in ~3.1 h (likely 2.4–4.0 h), confidence 0.71."*
- **Unusual activity, classified** — distinguishes an *operational demand spike*, a
  *data-quality problem*, and a *pattern requiring review*. Each alert shows which hypotheses
  were considered and **rejected**, and why.
- **Data-quality fallback** — when a provider feed is stale or conflicting, confidence drops and
  the projection is **withdrawn** rather than guessed.
- **Coordination** — alerts route to a named owner, carry a recommended next step, and move
  through acknowledge → escalate → resolve with an append-only audit trail.
- **Coverage and hotspots** — areas ranked by how many outlets are projected to run dry
  inside the alert horizon, with nearby-outlet support discovery: an outlet holding headroom
  *in the same provider* can be coordinated with through the approved channel.
- **Cross-outlet relationships** — accounts appearing at three or more outlets, and accounts
  active across multiple providers. Presented as a lead for a human, never as a finding.
- **What-if** — a demand multiplier that re-runs the projection live, because the analytics
  are pure functions.
- **Bengali-first** explanations with an English toggle.
- **Evidence pack** — one download carrying alerts, thresholds, projections, feed status and
  case history, so a reviewer never has to take the dashboard's word for anything.

---

## Architecture

One Python process, one HTML page, no frontend build step.

```
Simulator (seeded, ground-truth labelled)
        │  per-provider feeds, independent lag / health / conflict
        ▼
Analytics core — pure functions, no I/O, individually testable
   liquidity.py    robust drain rates → exhaustion interval + confidence
   anomaly.py      burst velocity, near-identical amounts, balance reconciliation
   quality.py      feed health → confidence dampening → safe suppression
   context.py      Eid / salary / market calendar → hypothesis classification
        ▼
Decision layer
   narrative.py     deterministic BN/EN assembler → LLM rephrase (cached)
   coordination.py  routing → owner → acknowledge → escalate/resolve → audit
        ▼
FastAPI  →  single-page dashboard (vanilla JS)
```

Full detail in [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Run locally

```bash
./run.sh              # installs dependencies and serves on http://127.0.0.1:8000
```

Or manually:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Test

```bash
python -m pytest -q
```

## Measure

```bash
python -m app.validation     # writes data/metrics.json and data/metrics.md
```

---

## Demo path

1. **Baseline** — the unified view: shared cash plus three provider balances, with feed health.
2. **Scenario A** — total value looks healthy, but Nagad e-money is hours from exhaustion.
   The composition panel calls out that the aggregate is misleading.
3. **Scenario B** — an unusual-activity alert. Open it: evidence, confidence, and the panel
   naming which hypotheses were *rejected* and why.
4. **Scenario C** — a conflicting feed. Confidence collapses and the projection is withdrawn
   rather than guessed.
5. **Coordination** — acknowledge, escalate, resolve; show the audit trail. Then attempt a
   cross-provider action and show it is refused.

---

## Provider boundaries

Enforced in code, not merely documented in copy:

- A workflow action whose acting provider differs from the alert's provider raises
  `PermissionError` and returns HTTP 403.
- No code path converts, transfers, or settles value between providers — there is no such
  function to call.
- The unified view is a read-only aggregation for the agent.

Exactly one provider's e-money can be at risk while the aggregate looks fine — detecting that
without implying one provider may act on another's balance is the point.

---

## Documents

| File | Contents |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Components, data flow, provider boundaries |
| [`DATA_AND_SIMULATION.md`](DATA_AND_SIMULATION.md) | Synthetic data generation, assumptions, limitations |
| [`RESPONSIBLE_DESIGN.md`](RESPONSIBLE_DESIGN.md) | Privacy, human review, false positives, explicit non-actions |
| [`METRICS.md`](METRICS.md) | Measured validation evidence |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Host, configuration, cold-start behavior |
| [`docs/superpowers/specs/`](docs/superpowers/specs/) | Design specification |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Implementation plan |

---

## Measured evidence

At least three metrics are measured by `python -m app.validation` rather than asserted:

1. Shortage detection lead time
2. Anomaly precision and recall against injected ground truth
3. False-positive rate on legitimate Eid-window surges
4. Analytics latency (p50 / p95)
5. Alert explanation coverage

Because the simulator owns ground truth for its injected scenarios, precision, recall, and
false-positive rate are genuinely measurable. See [`METRICS.md`](METRICS.md).

---

## Status

Prototype under active development for the Codex Community Hackathon.
Implementation proceeds task by task from
[`docs/superpowers/plans/2026-09-24-super-agent-liquidity-risk-platform.md`](docs/superpowers/plans/2026-09-24-super-agent-liquidity-risk-platform.md).
