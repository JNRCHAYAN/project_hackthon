"""Seeded simulator with ground truth.

The product needs data whose *true* state is known, because "did the detector
find the thing we planted?" is otherwise unanswerable. So the simulator builds
a small network of agent outlets from a seed and then deliberately plants four
kinds of situation inside it, recording each one as an :class:`Episode`:

===============  =========================================================
label            what was planted
===============  =========================================================
(no episode)     Scenario A — one provider drains hard while the shared
                 cash drawer stays healthy. This is a *liquidity* case, not
                 an anomaly, so it carries no episode; Task 3's projection
                 layer is what should catch it.
``anomaly``      Scenario B — a burst of near-identical cash-outs from a
                 handful of accounts in a short window.
``demand_spike`` Scenario B2 — a genuinely busy Eid window with many
                 distinct accounts and widely varying amounts. Planted so a
                 context-aware detector can prove it does *not* flag it.
``data_quality`` Scenario C — a declared balance that the transaction chain
                 cannot account for.
===============  =========================================================

Two further invariants hold across the whole world and are what make it
usable as a test fixture:

* every transaction is time-ordered and none is future-dated;
* every balance chain reconciles against ``opening_balance`` — *except* the
  one outlet that Scenario C deliberately breaks. Nothing else is allowed to
  drift, because a stray drift would look like a data-quality fault to the
  analytics layer and turn ground truth into noise.

All data is synthetic and every ``sender_hash`` is a pseudonym (``h0123``);
no real identity or account is represented anywhere.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from app.config import SETTINGS
from app.domain import (
    FeedStatus, Outlet, OutletState, Provider, ProviderPosition,
    Transaction, TxnType,
)
from app.quality import DELAYED_AFTER_S, STALE_AFTER_S

PROVIDERS = [
    Provider(id="bkash", name="bKash", name_bn="বিকাশ"),
    Provider(id="nagad", name="Nagad", name_bn="নগদ"),
    Provider(id="rocket", name="Rocket", name_bn="রকেট"),
]

# (area, thana, district, lat, lon). Coordinates are real area centroids; the
# hotspot and "nearest surplus outlet" features measure distance between them.
AREAS = [
    ("Sylhet", "Zindabazar", "Sylhet", 24.8949, 91.8687),
    ("Dhaka", "Mirpur", "Dhaka", 23.8069, 90.3687),
    ("Chattogram", "Agrabad", "Chattogram", 22.3259, 91.8123),
    ("Rajshahi", "Boalia", "Rajshahi", 24.3667, 88.6000),
]

HOUR = 3600.0
MINUTE = 60.0

# Default clock: the afternoon before Eid-ul-Fitr 2026 in Dhaka time — the exact
# situation the problem statement opens with. Fixed rather than "now" so a run
# stays reproducible forever, and placed inside the Eid window so the context
# classifier is genuinely exercised by the demo rather than idling on "ordinary".
DEFAULT_NOW = SETTINGS["demo_clock"]

# --- Scenario A: the provider drain ----------------------------------------
DRAIN_OPENING = 6_200.0          # 8 x 2,100 of head-room, then it runs dry
DRAIN_STEP = 2_100.0             # cash-in => e-money leaves the provider
DRAIN_STEPS = 8
DRAIN_WINDOW = 40 * MINUTE       # the drain sits in the last 40 minutes
DRAIN_GAP = 5 * MINUTE
# A drawer this full is "healthy" for a busy urban outlet; used only as the
# floor below which Scenario A tops up the opening float.
CASH_FLOOR = 42_000.0

# --- Scenario C: the deliberate break --------------------------------------
C_DRIFT = 25_000.0
# --- Feed faults ------------------------------------------------------------
STALE_FEED_AGE = 45 * MINUTE
# The age that lands a planted feed squarely in the *delayed* band. Derived
# from the model's own thresholds rather than written down, because a literal
# here would silently stop demonstrating anything the moment either threshold
# is retuned. The midpoint is strictly inside the band for any ordered pair of
# thresholds, and never sits on a boundary where an exclusive comparison would
# flip it to the neighbouring rung.
DELAYED_FEED_AGE = (DELAYED_AFTER_S + STALE_AFTER_S) / 2

BURST_AMOUNT = 9_900.0           # Scenario B's "near-identical" size
BURST_ACCOUNTS = 4               # <= SETTINGS["burst_max_accounts"]
BURST_TXNS = 9
EID_SURGE_TXNS = 14


@dataclass
class Episode:
    """A planted situation, with the truth about it recorded up front."""
    outlet_id: str
    provider_id: str
    label: str            # anomaly | demand_spike | data_quality
    start: float
    end: float
    note: str = ""


@dataclass
class Simulator:
    """Builds a deterministic outlet network seeded by ``seed``.

    ``scenario(name)`` records which scenario the caller is interested in.
    Every scenario is still injected into every world — ground truth is only
    useful if it is complete, and the guards below make each injection a no-op
    when the world has too few outlets to host it.
    """
    seed: int = 42
    outlets: int = 12
    now: float = 0.0
    history_hours: int = 6
    _episodes: list[Episode] = field(default_factory=list)
    _scenario: str = "baseline"

    def __post_init__(self) -> None:
        if not self.now:
            self.now = DEFAULT_NOW
        self._rng = random.Random(self.seed)

    # -- public surface -----------------------------------------------------
    def scenario(self, name: str) -> "Simulator":
        self._scenario = name
        return self

    def episodes(self) -> list[Episode]:
        if not self._episodes:
            self.world()
        return self._episodes

    def world(self) -> dict[str, OutletState]:
        # Re-seed on every build so world() is idempotent, not just repeatable
        # across fresh instances.
        rng = random.Random(self.seed)
        self._rng = rng
        self._episodes = []
        world: dict[str, OutletState] = {}

        for i in range(self.outlets):
            area, thana, district, lat, lon = AREAS[i % len(AREAS)]
            outlet = Outlet(id=f"AG-{1000 + i}", name=f"Outlet {1000 + i}",
                            area=area, thana=thana, district=district,
                            lat=lat, lon=lon)
            world[outlet.id] = self._build_outlet(outlet, rng)

        self._inject_episodes(world)
        # Normalise: sort by time, then enforce the no-future-dated invariant.
        for state in world.values():
            state.transactions = sorted(
                (t for t in state.transactions if t.ts <= self.now),
                key=lambda t: t.ts)
        return world

    # -- baseline generation ------------------------------------------------
    def _demand(self, ts: float) -> float:
        """Diurnal demand multiplier — afternoon peak, matching the Eid surge."""
        hour = (ts / HOUR) % 24
        return 0.55 + 0.85 * math.exp(-((hour - 15.0) ** 2) / 18.0)

    def _build_outlet(self, outlet: Outlet, rng: random.Random) -> OutletState:
        cash = round(rng.uniform(45_000, 160_000), 2)
        positions = {}
        for p in PROVIDERS:
            opening = round(rng.uniform(40_000, 190_000), 2)
            positions[p.id] = ProviderPosition(
                provider_id=p.id, balance=opening, opening_balance=opening,
                last_feed_at=self.now - rng.uniform(20, 90))

        state = OutletState(outlet=outlet, cash=cash, cash_opening=cash,
                            positions=positions)
        steps = 18
        bal = {p.id: positions[p.id].balance for p in PROVIDERS}
        for k in range(steps, 0, -1):
            ts = self.now - k * (self.history_hours * HOUR / steps)
            n = max(1, int(rng.gauss(3, 1.4) * self._demand(ts)))
            for _ in range(n):
                provider = rng.choice(PROVIDERS).id
                # cash_out dominant in the afternoon: drains cash, grows e-money
                txn_type = (TxnType.CASH_OUT if rng.random() < 0.62
                            else TxnType.CASH_IN)
                amount = round(rng.choice([500, 1000, 2000, 3000, 5000])
                               * rng.uniform(0.9, 1.15), 2)
                bal[provider] += amount if txn_type is TxnType.CASH_OUT else -amount
                state.cash += -amount if txn_type is TxnType.CASH_OUT else amount
                state.transactions.append(Transaction(
                    id=f"{outlet.id}-{provider}-{int(ts)}-{rng.randrange(10**6)}",
                    outlet_id=outlet.id, provider_id=provider, ts=ts,
                    type=txn_type, amount=amount, status="success",
                    sender_hash=f"h{rng.randrange(1, 400):04d}",
                    balance_after=round(bal[provider], 2)))

        for p in PROVIDERS:
            positions[p.id].balance = round(bal[p.id], 2)
        state.cash = round(state.cash, 2)
        return state

    # -- ground-truth injections --------------------------------------------
    def _inject_episodes(self, world: dict[str, OutletState]) -> None:
        ids = sorted(world)
        rng = self._rng

        # Scenario A: one provider drains hard while shared cash stays healthy.
        # The nagad transaction series is rebuilt from scratch so the balance
        # chain still reconciles — a deliberate break is Scenario C's job, and
        # only Scenario C's.
        if ids:
            self._scenario_a(world, ids[0])

        # Scenario B: burst of near-identical cash-outs from few accounts.
        if len(ids) > 1:
            o = ids[1]
            state = world[o]
            start = self.now - SETTINGS["burst_window_minutes"] * MINUTE
            accounts = [f"h9{i:03d}" for i in range(BURST_ACCOUNTS)]
            pos = state.positions["bkash"]
            bal = pos.balance
            amounts = []
            for j in range(BURST_TXNS):
                ts = start + j * 70
                # Half-width on the tolerance, so the whole spread of the
                # burst stays inside SETTINGS["burst_amount_tolerance"].
                tol = SETTINGS["burst_amount_tolerance"] / 2
                amount = BURST_AMOUNT * (1 + rng.uniform(-tol, tol))
                bal += amount
                amounts.append(round(amount, 2))
                state.transactions.append(Transaction(
                    id=f"{o}-burst-{j}", outlet_id=o, provider_id="bkash",
                    ts=ts, type=TxnType.CASH_OUT, amount=round(amount, 2),
                    status="success", sender_hash=accounts[j % len(accounts)],
                    balance_after=round(bal, 2)))
            pos.balance = round(bal, 2)
            self._rebalance_cash(state)
            self._episodes.append(Episode(
                outlet_id=o, provider_id="bkash", label="anomaly",
                start=start, end=self.now,
                note=(f"{BURST_TXNS} near-identical cash-outs "
                      f"(spread {self._spread(amounts):.1%}) from "
                      f"{BURST_ACCOUNTS} accounts in "
                      f"{SETTINGS['burst_window_minutes']} min")))

        # Scenario B2: a legitimate Eid-window surge — must NOT be flagged.
        if len(ids) > 2:
            o = ids[2]
            state = world[o]
            state.calendar_context = "eid_window"
            start = self.now - 20 * MINUTE
            pos = state.positions["rocket"]
            bal = pos.balance
            hashes = []
            for j in range(EID_SURGE_TXNS):
                ts = start + j * 80
                amount = 500.0 * rng.uniform(1, 18)
                bal += amount
                sender = f"h{rng.randrange(100, 399):04d}"
                hashes.append(sender)
                state.transactions.append(Transaction(
                    id=f"{o}-eid-{j}", outlet_id=o, provider_id="rocket",
                    ts=ts, type=TxnType.CASH_OUT, amount=round(amount, 2),
                    status="success", sender_hash=sender,
                    balance_after=round(bal, 2)))
            pos.balance = round(bal, 2)
            self._rebalance_cash(state)
            self._episodes.append(Episode(
                outlet_id=o, provider_id="rocket", label="demand_spike",
                start=start, end=self.now,
                note=(f"Eid-window surge: {len(set(hashes))} distinct accounts, "
                      "wide amount spread — expected, must not be flagged")))

        # Scenario C: balance chain that does not reconcile.
        if len(ids) > 3:
            o = ids[3]
            state = world[o]
            pos = state.positions["bkash"]
            pos.balance = round(pos.balance + C_DRIFT, 2)   # unexplained jump
            pos.feed_status = FeedStatus.CONFLICTING
            self._episodes.append(Episode(
                outlet_id=o, provider_id="bkash", label="data_quality",
                start=self.now - 600, end=self.now,
                note=(f"declared balance exceeds the reconciled chain by "
                      f"{C_DRIFT:,.0f}; declared total value now "
                      f"{state.total_value():,.0f}")))

        # Feed faults: the other three degraded feeds, each on its own outlet
        # and its own provider — stale, delayed, then absent entirely. No
        # episode is recorded for any of them: ground truth describes planted
        # *activity*, and a feed that never arrived is not something a detector
        # can find or miss. One fault per outlet also leaves that outlet's
        # other two positions as fresh evidence rather than collateral damage.
        if len(ids) > 4:
            pos = world[ids[4]].positions["nagad"]
            pos.feed_status = FeedStatus.STALE
            pos.last_feed_at = self.now - STALE_FEED_AGE

        if len(ids) > 5:
            pos = world[ids[5]].positions["rocket"]
            pos.feed_status = FeedStatus.DELAYED
            pos.last_feed_at = self.now - DELAYED_FEED_AGE

        # Missing is the one state with no timestamp at all: classify_feed
        # tests ``last_feed_at is None`` *before* it looks at lag or drift, so
        # the plant has to clear the timestamp rather than age it. An old but
        # present stamp would classify as stale and demonstrate a different
        # rung of the ladder.
        if len(ids) > 6:
            pos = world[ids[6]].positions["bkash"]
            pos.feed_status = FeedStatus.MISSING
            pos.last_feed_at = None

    def _scenario_a(self, world: dict[str, OutletState], o: str) -> None:
        """Drain one provider dry, leaving the shared drawer healthy."""
        state = world[o]
        # Drop the generated nagad history first: the rebuilt chain below is
        # the *only* nagad history for this outlet, so it reconciles exactly.
        state.transactions = [t for t in state.transactions
                              if t.provider_id != "nagad"]

        pos = state.positions["nagad"]
        pos.opening_balance = DRAIN_OPENING + DRAIN_STEPS * DRAIN_STEP
        running = pos.opening_balance
        drain_start = self.now - DRAIN_WINDOW
        for j in range(DRAIN_STEPS):
            running = round(running - DRAIN_STEP, 2)   # cash_in drains e-money
            state.transactions.append(Transaction(
                id=f"{o}-drain-{j}", outlet_id=o, provider_id="nagad",
                ts=drain_start + j * DRAIN_GAP, type=TxnType.CASH_IN,
                amount=DRAIN_STEP, status="success",
                sender_hash=f"h8{j:03d}", balance_after=running))
        pos.balance = round(running, 2)                # ৳6,200 remaining
        pos.last_feed_at = self.now - 120

        # The drain is a cash-in series, so the drawer gains ৳2,100 a step.
        self._rebalance_cash(state)

    @staticmethod
    def _rebalance_cash(state: OutletState) -> None:
        """Re-derive the drawer from the surviving chain, keeping it solvent.

        An injected series has to move cash as well as e-money: a burst of
        cash-outs that never leaves the drawer would leave the outlet's total
        inconsistent with its own transaction list, and the reconciliation
        check downstream would read that as a data-quality fault. Only
        Scenario C is allowed to look like that.
        """
        state.cash = round(state.cash_opening
                           + sum(t.cash_delta() for t in state.transactions), 2)
        if state.cash < CASH_FLOOR:
            # Keep the drawer solvent — and keep the chain exact — by lifting
            # the declared opening float by the shortfall, not by inventing an
            # unexplained credit (that is Scenario C's move, not ours).
            top_up = round(CASH_FLOOR - state.cash, 2)
            state.cash_opening = round(state.cash_opening + top_up, 2)
            state.cash = round(state.cash + top_up, 2)

    @staticmethod
    def _spread(amounts: list[float]) -> float:
        mean = sum(amounts) / len(amounts)
        return (max(amounts) - min(amounts)) / mean if mean else 0.0
