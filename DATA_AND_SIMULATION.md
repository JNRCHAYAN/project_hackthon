# Data and Simulation Note

Every figure in this prototype comes from a seeded synthetic simulation. No
production API, customer identity, credential, or real balance is used anywhere,
and no such input is representable in the schema.

## How the data was created

`app/simulator.py` builds the world deterministically from a seed:

- **Outlets.** 12 outlets (`AG-1000`…) distributed across four real Bangladeshi
  areas — Sylhet/Zindabazar, Dhaka/Mirpur, Chattogram/Agrabad, Rajshahi/Boalia —
  each carrying coordinates so that distance-based support discovery is a real
  calculation rather than a label.
- **Balances.** Each outlet gets one shared physical cash balance (৳45,000–160,000)
  and three independent provider e-money balances — bKash, Nagad, Rocket — opening
  between ৳40,000 and ৳190,000. The three providers are independent from the first
  line of the simulator: separate balances, separate feed timestamps, separate feed
  health.
- **Transaction history.** Six hours of history in 18 steps, with a diurnal demand
  curve that peaks in the mid-afternoon to match the problem statement's
  pre-Eid market scenario. **62% of transactions are cash-out**, which is the
  pressure direction that drains the shared cash drawer while growing provider
  e-money.
- **Sign conventions.** `Transaction.cash_delta()` and `emoney_delta()` encode the
  opposite-direction relationship that the whole product rests on: a cash-out
  decreases shared cash and *increases* that provider's e-money; a cash-in does the
  reverse.
- **Identifiers.** `sender_hash` values are seeded pseudonyms (`h0123`). They are
  stable within a run so that burst and network analysis work, and they are not
  derived from any real person. No name, phone number, account number, PIN, or OTP
  exists anywhere in the model.
- **No future-dated transactions.** The simulator sorts the transaction list and
  drops anything stamped after `now`, so the trailing-window calculation can never
  manufacture a negative elapsed time or an upward slope from data that has not
  happened yet.

## Injected scenarios and their ground truth

The simulator plants episodes and records their labels. This is deliberate: it is
the only reason precision, recall, and false-positive rate are *measurable* rather
than asserted.

| Scenario | Planted condition | Ground-truth label |
|---|---|---|
| **A** | Nagad e-money drains hard (8 × ৳2,100 cash-in) while shared cash stays healthy — total value looks fine, one provider is hours from empty | `liquidity` |
| **B** | 9 near-identical cash-outs (৳9,900, spread ~1.8%) from 4 accounts inside 12 minutes | `anomaly` |
| **B2** | 14 diverse-account cash-outs with a broad amount range during an Eid window — a *legitimate* surge that must **not** be flagged | `demand_spike` |
| **C** | Declared balance exceeds the reconciled chain by ৳25,000 — a data-integrity fault, explicitly not suspicion | `data_quality` |
| **Feed fault** | Four provider feeds are degraded, one per outlet: one stale, one late but not yet stale, one absent entirely, one conflicting with the ledger. No episode is recorded — a feed that never arrived is not activity, so there is nothing for a detector to find or miss | `reliability` |

Scenario A is the headline case: aggregate health is misleading by construction.
Scenario B2 is the control. A detector that flags B2 as well as B — or that fails
to distinguish the two — is not measuring anything, and the harness reports it as a
false positive.

## Assumptions

1. **Demand is diurnal and locally peaked.** Demand follows an afternoon-weighted
   curve rather than a flat rate, so a trailing-window slope reflects the real
   direction of travel instead of averaging across a quiet night.
2. **Providers are logically separate systems.** Each has its own balance, its own
   feed cadence, and its own health. There is no shared ledger and no synchronization
   between them, because representing one would imply an integration that does not
   exist.
3. **Cash-out dominates under pressure.** The generator is weighted toward cash-out
   because that is the direction that produces a service failure — the drawer empties
   and the provider e-money grows, so an outlet can be simultaneously rich in e-money
   and unable to serve the next customer.
4. **Feed faults are independent per provider.** Lag, staleness, and reconciliation
   failure are properties of one provider's feed, not of the outlet, which is what
   makes the degraded-data fallback path meaningful.
5. **Analytical thresholds are judgement calls, not constants of nature.** Every
   one of them lives in `app/config.py` so it can be inspected and challenged:
   the 12-minute burst window, the ±2% near-identical tolerance, the 5-account
   concentration ceiling, the 8-account demand-spike floor, the 5%/95% spread
   ratio, the 6-hour alert horizon, and the 5-minute/30-minute feed staleness
   boundaries.

## Limitations

1. **The simulation is not calibrated to real MFS volumes.** Absolute transaction
   counts and amounts are plausible but not derived from any published dataset.
   The analytics are therefore validated for *internal consistency and detection
   behaviour*, not for accuracy against real Bangladeshi agent traffic.
2. **Ground truth is planted, not observed.** Precision and recall measure whether
   the detector finds what the simulator deliberately injected. This is a genuine
   measurement of the detector, but it cannot tell you how it would behave against
   patterns nobody thought to simulate — in particular, adversarial behaviour
   designed to evade these specific rules.
3. **The false-positive check covers one control case.** Eid-window surge (B2) is a
   real control, and salary-day and market-day contexts are handled in
   `context.py`, but a production system would need many more legitimate-demand
   scenarios before a false-positive rate could be quoted with confidence.
4. **Anomaly detection is per-agent against its own baseline.** This is a fairness
   choice — a low-volume outlet must not be permanently flagged for being small —
   but it means a network-wide pattern spread thinly across many outlets, each
   individually unremarkable, would not be caught.
5. **The network view uses shared pseudonymous accounts across outlets.** It shows
   accounts appearing at three or more outlets, which is usually an ordinary mobile
   customer moving through a market. The view is a lead for a human, not a finding.
6. **The demand what-if is first-order.** Scaling demand scales the drain rate and
   therefore inverts the exhaustion time. It does not model the second-order
   behaviour a real market would show — that customers switch providers, queue, or
   leave when an outlet runs dry.

## Reproducing any number

```bash
python -m app.validation     # rewrites data/metrics.json and data/metrics.md
python -m pytest -q          # behavioural guarantees, including the degraded-data paths
```

The simulator is seeded, so a given seed reproduces a given world exactly. The
harness records the seeds and configuration it used alongside the results.
