# Super Agent Liquidity & Risk Intelligence Platform — Design Spec

**Event:** Codex Community Hackathon — bKash presents SUST CSE Carnival 2026
**Date:** 2026-09-24
**Status:** Approved for implementation
**Build budget:** 2 hours, single developer

---

## 1. Problem

A multi-provider MFS "super agent" serves bKash, Nagad, and Rocket customers from **one physical cash drawer** but **three separate e-money balances**. The agent can inspect each provider in isolation but cannot answer the operational question that matters: *will this outlet still be able to serve customers in the next few hours?*

Three connected problems must be solved together, not as three screens:

1. **Liquidity** — per-provider and aggregate pressure, projected forward, with honest uncertainty.
2. **Anomaly** — unusual transaction/balance behavior surfaced with evidence and uncertainty, expressed as advisory language only.
3. **Coordination** — an alert must route to a named owner, carry a recommended action, be acknowledged, and reach a visible resolution. Passive notifications are a failure.

### Hard constraints

- Simulated/Anonymized data only. No real balances, identities, credentials, or provider APIs.
- Providers are logically separate systems. No implied conversion, settlement, or interoperation.
- Risk output is advisory. **Never** a fraud determination, never an automatic block or financial action.
- Provider boundaries: a combined outlet *view* is permitted; one provider controlling another's balance is not.

---

## 2. Core Domain Insight

The two flows move in **opposite directions**, and this is the foundation of the entire product:

| Customer action | Shared cash | That provider's e-money |
|---|---|---|
| **Cash-out** (takes cash, sends e-money) | decreases | increases |
| **Cash-in** (gives cash, takes e-money) | increases | decreases |

Consequences that drive the design:

- **Aggregate health is misleading.** Total value can be comfortable while one provider is hours from exhaustion. A single summed number is an actively dangerous metric, not a simplification.
- **Cross-provider imbalance is structural, not a bug.** Cash accumulated from one provider's cash-out cannot be used to replenish another provider's e-money — that is settlement, explicitly out of scope.
- **The guardrail generates the recommendation.** Because conversion is prohibited, the only correct remedy is an approved-channel balance arrangement *before* the projected exhaustion time. The product's advice is derived from its constraints.

---

## 3. Architecture

Single Python process, single HTML page. No frontend build step, no service mesh.

```
Simulator (seeded, ground-truth labelled episodes)
        │  per-provider feeds, independent lag / health / conflict
        ▼
Analytics core — pure functions, no I/O, individually testable
   liquidity.py    robust drain rates → exhaustion time + interval + confidence
   anomaly.py      burst velocity, near-identical amounts, balance reconciliation
   quality.py      feed health → confidence dampening → safe suppression
   context.py      Eid / salary / market calendar → hypothesis classification
        ▼
Decision layer
   narrative.py     deterministic BN/EN assembler → LLM rephrase (cached)
   coordination.py  routing → owner → acknowledge → escalate/resolve → audit
        ▼
FastAPI
   /api/state   /api/alerts   /api/case/*   /api/whatif   /api/narrate
   /api/stream  (SSE)
        ▼
Single-page dashboard (vanilla JS) — language toggle BN/EN
```

**Dependency budget:** `fastapi`, `uvicorn`, `httpx`. Nothing else required.

### Layering rule

Analytics modules are pure functions over data structures — no network, no database, no globals. This is what makes the validation script possible, makes what-if simulation nearly free, and keeps the analytics independently testable.

---

## 4. Data Model

```
Provider        id, name, feed_lag_s, feed_status ∈ {fresh, delayed, stale, conflicting, missing}
Outlet          id, name, area, thana, district, geo, calendar_context
ProviderBalance (outlet, provider) → emoney_balance, last_feed_at, opening_balance
SharedCash      (outlet) → balance, last_updated
Transaction     id, outlet, provider, ts, type ∈ {cash_in, cash_out},
                amount, status ∈ {success, failed, reversed},
                sender_hash, balance_after
Alert           id, outlet, provider, kind ∈ {liquidity, anomaly, data_quality},
                severity, confidence, reason, evidence[], uncertainty,
                hypotheses{accepted, rejected[]}, status, owner, assignee
CaseEvent       alert_id, actor, action, ts, note     (append-only)
```

All identifiers are synthetic. `sender_hash` is a seeded pseudonym — no real identity is representable in the schema.

---

## 5. Analytics Design

### 5.1 Liquidity (`liquidity.py`)

Drain rate is estimated **separately** for shared cash and each provider's e-money, using a Theil–Sen robust slope over a trailing 60-minute window. A robust estimator is required because a naive mean is destroyed by a single large transaction — which is exactly the situation (Eid rush) the product must survive.

Outputs an **interval**, not a point estimate:

```
Nagad e-money exhausted in 3.1h  (likely 2.4h – 4.0h)   confidence 0.71
```

- `time_to_exhaust = balance / max(drain_rate, ε)`
- Interval from residual quantiles of the fitted slope (p10/p90), not a symmetric guess.
- **Confidence** is a product of feed freshness, rate variance, and sample size — so it degrades honestly rather than asserting false precision under noisy data.

### 5.2 Anomaly (`anomaly.py`)

Scoring is **per-agent against that agent's own historical baseline**, never cross-agent. This is a fairness requirement: a low-volume outlet must not be permanently flagged merely for being small.

Two detection families, both grounded in the problem statement's suggested patterns:

1. **Burst velocity with near-identical amounts** — count of transactions in a trailing 12-minute window whose amounts fall within ±2% of one another, originating from a small set of distinct `sender_hash` values. *(Scenario B.)*
2. **Balance-chain inconsistency** — `balance_after` does not reconcile against opening balance plus the sum of signed transactions. This is classified as `data_quality`, **explicitly not** as suspicious activity. *(Scenario C.)*

### 5.3 Context Classification (`context.py`) — the differentiator

The mandatory requirement is to distinguish *operational demand spike* / *data-quality problem* / *pattern requiring review*. The same chart can mean all three. Detection therefore emits a **classification with reasoning**, not a bare score:

| Classification | Conditions | Action |
|---|---|---|
| **Demand spike** | Elevated velocity **and** aligned to known context (Eid window, salary days 1–5, market day) **and** spread across many diverse accounts **and** broad amount distribution | Suppress review priority; explain the benign hypothesis |
| **Requires review** | Elevated velocity **and** concentrated in ≤5 accounts **and** amounts near-identical **and** no context alignment | Raise alert with evidence |
| **Data-quality problem** | Balance chain fails to reconcile | Route as `data_quality`; never as suspicion |

Alerts display **which hypothesis was rejected and why**. This is the single highest-leverage element for the 20%-weighted Data & Analytical Quality criterion.

### 5.4 Data Quality & Safe Fallback (`quality.py`)

Mandatory requirement. `feed_status` propagates into every downstream confidence:

- Confidence multipliers: `delayed ×0.8`, `stale ×0.5`, `conflicting ×0.3`.
- When a feed is **conflicting or unreconcilable, the liquidity recommendation is suppressed entirely** and replaced with *"insufficient reliable data — verify feed before acting."*

A degraded feed must never silently yield a confident conclusion. This is tested, not merely documented.

---

## 6. Narrative Layer (`narrative.py`)

Two stages, ordered deliberately:

1. **Deterministic assembler** — builds `{situation, evidence[], uncertainty, next_step[]}` from analytics output in Bengali and English. Instant, always correct, no external dependency.
2. **LLM rewriter** — `deepseek-v4-flash` via AgentRouter (Anthropic Messages shape, `max_tokens` ≥ 2000, 8s timeout) restyles stage 1 into natural Bengali. Results cached to disk by content hash and **pre-warmed at startup** for demo scenarios.

### Structural safety rule

**Numeric evidence is always rendered directly from the analytics layer and never passes through the model.** The LLM supplies phrasing only. It is therefore structurally incapable of displaying an incorrect balance or a fabricated figure.

Edge cases handled:

- On timeout, error, or an empty text block → fall back to stage 1. A complete, correct alert already exists; nothing is lost.
- The model emits a `thinking` block before its answer (reasoning model), so `max_tokens` truncation is a real failure mode and is explicitly guarded.
- Vocabulary lint rejects forbidden terms (`fraud`, `প্রতারণা`, and equivalents) in generated output.

---

## 7. Coordination (`coordination.py`)

```
Alert → routing rule (provider + area + severity → role) → owner assigned
      → acknowledged → recommended action → escalated | resolved
      → every transition appended to audit log
```

Role chain: agent/outlet → field officer → area manager → central operations → risk analyst.

**Provider boundary, enforced in code:** an alert tagged Nagad may only be owned and escalated within the Nagad track. The unified view is read-only across providers, and any attempted cross-provider action surfaces a boundary notice in the UI. This is a scored guardrail and is made visible during the demo rather than only described.

Risk analysts receive escalations but the platform never records a fraud determination — only review outcomes.

---

## 8. User Interface

Single page, hand-styled, Bengali-first with an English toggle.

- **Header** — outlet selector; per-provider feed-health pills with feed age; global confidence badge; BN/EN toggle.
- **Row 1 — Liquidity** — three provider balance cards plus one shared-cash card, each with sparkline, drain rate, and projected exhaustion interval.
- **Row 2 — Unified view** — stacked area of total value against composition, exposing "aggregate healthy, composition skewed" *(Scenario A)*; timeline with projected depletion markers.
- **Row 3 — Alerts** — cards with kind, severity, confidence, expandable evidence, and a "why flagged" panel naming the **rejected** hypotheses.
- **Row 4 — Case panel** — owner, status, recommended next step, acknowledge/escalate/resolve actions, audit trail.
- **Sidebar — What-if** — demand multiplier and event-day toggle driving a live analytics re-run (near-free once analytics are pure functions).

**Deterministic demo:** "Run Scenario A/B/C/D" controls drive the simulator clock so the demonstration is staged, repeatable, and never depends on live data arriving.

---

## 9. Validation & Metrics

`python -m app.validation` emits JSON plus a markdown table — this artifact **is** the "validation evidence" deliverable.

| # | Metric | Method |
|---|---|---|
| 1 | Shortage detection lead time | Predicted vs. ground-truth exhaustion over N seeded episodes; mean/median minutes early |
| 2 | Anomaly precision / recall | Confusion matrix against injected labelled episodes |
| 3 | False-positive rate | Eid-window and salary-day episodes wrongly flagged |
| 4 | API latency p50/p95 | At documented volume (200 outlets × 3 providers) |
| 5 | Alert explanation coverage | Percentage of alerts carrying reason + evidence + uncertainty (assert 100%) |

Metrics 1–3 are only measurable because the simulator owns ground truth. This is a deliberate design choice, not incidental.

---

## 10. Explicit Non-Goals

Recorded as documented limitations in `RESPONSIBLE_DESIGN.md`, a scored deliverable:

- No real provider integration, settlement, or interoperation of any kind.
- No final fraud determination, automatic blocking, accusation, or disciplinary action.
- No unauthorized cash movement, wallet refill, transfer, recovery, or reversal.
- No collection of PINs, OTPs, passwords, private keys, or credentials.
- No claim of regulatory approval or production fraud-detection readiness.
- Deferred: network/graph relationship views, hotspot mapping, nearby-agent support discovery, authentication/multi-user, languages beyond Bengali and English.

**Retained despite being optional:** what-if simulation sliders — negligible cost given pure analytics functions, and high demo value.

---

## 11. Build Order

Each stage leaves a runnable application, so an overrun still yields a demonstrable product.

1. Skeleton + simulator + liquidity → live balances and projection
2. Anomaly + context classification + evidence panel
3. Quality/fallback propagation + LLM narration
4. Coordination workflow + audit trail
5. **Deploy to Render** — a working public URL must exist before documentation is written
6. Metrics script + deliverable docs + demo rehearsal

Step 5 is deliberately ahead of step 6. Deployment is a submission requirement rather than
polish, and auto-deploy means every later commit lands on the live URL. Sequencing it last
would risk having nothing submittable but a local repository.

**Documented cut line:** if time is exhausted, reduce polish in stage 4 and compress stage 6
documentation — never drop the metrics script, since "three measured metrics" is a hard
deliverable and analytical validation carries 20% of the score.

---

## 12. Requirement Traceability

| Requirement | Implementation | Priority |
|---|---|---|
| Shared cash + separate provider balances | `store.py`, Row 1 cards | Mandatory |
| Which provider/cash shortage, and when | `liquidity.py` interval projection | Mandatory |
| ≥1 anomaly type with visible reason | `anomaly.py`, "why flagged" panel | Mandatory |
| Careful language, never "fraud" | `narrative.py` lint + copy review | Mandatory |
| Alert recipient, owner, next step, status | `coordination.py`, case panel | Mandatory |
| Lower confidence / fallback on bad data | `quality.py` suppression path | Mandatory |
| Meaningful AI / analytics | LLM narration + analytics core | Mandatory |
| Distinguish spike / data-quality / review | `context.py` three-way classification | Mandatory |
| Provider boundaries preserved | Enforced routing + UI boundary notice | Mandatory |
| Bengali/Banglish alert with evidence + uncertainty | `narrative.py` BN output | Recommended |
| Filter/sort by provider, agent, area, time | Dashboard filters | Recommended |
| ≥3 measured metrics | `validation.py` | Deliverable |
| Repo, architecture diagram, data note, responsible-design note | `ARCHITECTURE.md`, `DATA_AND_SIMULATION.md`, `RESPONSIBLE_DESIGN.md`, `METRICS.md` | Deliverable |
| Publicly reachable prototype | Render deployment via `render.yaml`; `DEPLOYMENT.md` records the URL, cold-start behavior, and ephemeral-storage limitation | Deliverable |
