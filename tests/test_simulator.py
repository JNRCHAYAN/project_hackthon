"""Tests for the seeded simulator and its ground truth.

The point of these tests is not "does it produce data" but "is the data
trustworthy as a fixture": deterministic, time-ordered, reconciling, and
labelled with the truth about what was planted in it.
"""
from app.config import SETTINGS
from app.domain import FeedStatus, TxnType
from app.quality import DELAYED_AFTER_S, STALE_AFTER_S, classify_feed
from app.simulator import MINUTE, PROVIDERS, Simulator

ALLOWED_LABELS = {"anomaly", "demand_spike", "data_quality"}
PROVIDER_IDS = {p.id for p in PROVIDERS}


def _snapshot(world):
    """Everything about a world that a fixture consumer could depend on."""
    return {
        outlet_id: {
            "cash": state.cash,
            "cash_opening": state.cash_opening,
            "calendar_context": state.calendar_context,
            "positions": {
                pid: (p.balance, p.opening_balance, p.feed_status, p.last_feed_at)
                for pid, p in state.positions.items()
            },
            "txns": [
                (t.id, t.provider_id, t.ts, t.type, t.amount, t.status,
                 t.sender_hash, t.balance_after)
                for t in state.transactions
            ],
        }
        for outlet_id, state in sorted(world.items())
    }


def _outlet(world, index):
    """The i-th outlet, in id order — the order the scenarios are planted in."""
    return sorted(world)[index]


def _episode(sim, label):
    matches = [e for e in sim.episodes() if e.label == label]
    assert len(matches) == 1, f"expected exactly one {label} episode, got {matches}"
    return matches[0]


def _reconciled(state, provider_id):
    """Opening balance plus the provider's own e-money deltas."""
    pos = state.positions[provider_id]
    return pos.opening_balance + sum(
        t.emoney_delta() for t in state.provider_txns(provider_id))


# --- determinism -----------------------------------------------------------

def test_simulator_is_deterministic():
    a = Simulator(seed=7, outlets=3).world()
    b = Simulator(seed=7, outlets=3).world()
    assert list(a) == list(b)
    assert a[list(a)[0]].cash == b[list(b)[0]].cash
    # The whole world, not just the first outlet's cash.
    assert _snapshot(a) == _snapshot(b)


def test_same_seed_rebuilds_the_same_world_twice():
    sim = Simulator(seed=13, outlets=5)
    assert _snapshot(sim.world()) == _snapshot(sim.world())


def test_different_seeds_diverge():
    a = _snapshot(Simulator(seed=7, outlets=3).world())
    b = _snapshot(Simulator(seed=8, outlets=3).world())
    assert a != b


# --- provider structure ----------------------------------------------------

def test_two_providers_minimum_and_separate_positions():
    world = Simulator(seed=1, outlets=2).world()
    assert len(PROVIDERS) >= 2
    assert PROVIDER_IDS == {"bkash", "nagad", "rocket"}
    for state in world.values():
        assert len(state.positions) == len(PROVIDERS)
        for provider in PROVIDERS:
            assert provider.id in state.positions
            # Each provider has its own position object, not a shared one.
            assert state.positions[provider.id].provider_id == provider.id
        assert len({id(p) for p in state.positions.values()}) == len(PROVIDERS)


def test_positions_start_from_their_own_opening_balance():
    world = Simulator(seed=2, outlets=2).world()
    for state in world.values():
        assert state.positions["bkash"].opening_balance != \
            state.positions["nagad"].opening_balance


def test_outlets_carry_area_coordinates():
    world = Simulator(seed=11, outlets=4).world()
    coords = {state.outlet.area: (state.outlet.lat, state.outlet.lon)
              for state in world.values()}
    assert coords["Sylhet"] == (24.8949, 91.8687)
    assert coords["Dhaka"] == (23.8069, 90.3687)
    assert coords["Chattogram"] == (22.3259, 91.8123)
    assert coords["Rajshahi"] == (24.3667, 88.6000)


# --- scenario A: provider drain, healthy drawer ----------------------------

def test_scenario_a_produces_provider_shortage_not_cash_shortage():
    world = Simulator(seed=3, outlets=1).scenario("A").world()
    state = next(iter(world.values()))
    # Nagad drains; shared cash stays healthy -> the headline Scenario A case
    assert state.positions["nagad"].balance < state.positions["bkash"].balance
    assert state.cash > 0


def test_scenario_a_nagad_series_reconciles_against_opening_balance():
    world = Simulator(seed=3, outlets=6).scenario("A").world()
    state = world[_outlet(world, 0)]
    pos = state.positions["nagad"]

    assert pos.balance < pos.opening_balance, "the provider must actually drain"
    computed = _reconciled(state, "nagad")
    assert pos.declared_reconciles(computed, SETTINGS["reconcile_tolerance"]), (
        f"scenario A left {pos.balance - computed:.2f} of unexplained drift "
        "on nagad; only scenario C is allowed to break a chain")


def test_scenario_a_rebuilds_nagad_history_rather_than_appending():
    """The old nagad transactions for that outlet must be gone."""
    world = Simulator(seed=3, outlets=6).scenario("A").world()
    outlet_id = _outlet(world, 0)
    state = world[outlet_id]
    nagad = state.provider_txns("nagad")

    assert nagad, "the drained provider must still have a history"
    # Only the drain series survives; nothing generated by the baseline build.
    assert all(t.id.startswith(f"{outlet_id}-drain-") for t in nagad)
    assert all(t.type is TxnType.CASH_IN for t in nagad)
    # Draining e-money means cash comes *in* to the drawer.
    assert all(t.cash_delta() > 0 for t in nagad)
    # And the chain runs unbroken from the declared opening balance.
    running = state.positions["nagad"].opening_balance
    for t in nagad:
        running -= t.amount
        assert abs(t.balance_after - running) < 0.01


def test_scenario_a_keeps_the_shared_cash_chain_exact():
    """Removing nagad history must not strand cash on an unreconciled total."""
    world = Simulator(seed=3, outlets=6).scenario("A").world()
    for state in world.values():
        computed = state.cash_opening + sum(
            t.cash_delta() for t in state.transactions)
        assert abs(computed - state.cash) <= SETTINGS["reconcile_tolerance"], (
            f"{state.outlet.id}: drawer chain is off by {computed - state.cash:.2f}")


# --- time ordering ---------------------------------------------------------

def test_transactions_are_time_ordered_and_never_future_dated():
    now = 1_700_000_000.0
    world = Simulator(seed=5, outlets=2, now=now).world()
    for state in world.values():
        stamps = [t.ts for t in state.transactions]
        assert stamps == sorted(stamps)
        assert all(t.ts <= now for t in state.transactions)


def test_no_future_dating_with_the_default_clock_either():
    sim = Simulator(seed=5, outlets=6)
    for state in sim.world().values():
        assert all(t.ts <= sim.now for t in state.transactions)


def test_transactions_are_well_formed_pseudonyms():
    world = Simulator(seed=17, outlets=3).world()
    for state in world.values():
        for t in state.transactions:
            assert t.outlet_id == state.outlet.id
            assert t.provider_id in PROVIDER_IDS
            assert t.amount > 0
            assert t.status in {"success", "failed", "reversed"}
            # h#### pseudonyms only — never a real identity
            assert t.sender_hash.startswith("h") and t.sender_hash[1:].isdigit()
            assert t.balance_after >= 0


# --- ground truth ----------------------------------------------------------

def test_ground_truth_episodes_are_labelled():
    sim = Simulator(seed=11, outlets=4)
    sim.world()
    eps = sim.episodes()
    assert eps, "simulator must expose injected ground-truth episodes"
    for e in eps:
        assert e.label in ALLOWED_LABELS
        assert e.outlet_id and e.provider_id


def test_ground_truth_episodes_point_at_real_outlets_and_time():
    sim = Simulator(seed=11, outlets=6)
    world = sim.world()
    eps = sim.episodes()
    assert len(eps) == 3, [e.label for e in eps]
    assert {e.label for e in eps} == ALLOWED_LABELS
    for e in eps:
        assert e.outlet_id in world
        assert e.provider_id in PROVIDER_IDS
        assert e.start <= e.end <= sim.now
        assert e.note


def test_scenarios_are_guarded_by_outlet_count():
    """A world too small for a scenario skips it instead of crashing."""
    two = Simulator(seed=11, outlets=2)
    world = two.world()
    assert len(world) == 2
    # Only scenario B fits in two outlets; the rest are guarded no-ops.
    assert [e.label for e in two.episodes()] == ["anomaly"]

    one = Simulator(seed=11, outlets=1)
    one.world()
    assert one.episodes() == []

    # Every scenario that fits is planted, and nothing else.
    assert {e.label for e in Simulator(seed=11, outlets=5).episodes()} == \
        ALLOWED_LABELS


# --- scenario B: coordinated burst -----------------------------------------

def test_scenario_b_is_a_burst_of_near_identical_cash_outs():
    sim = Simulator(seed=11, outlets=6)
    world = sim.world()
    outlet_id = _outlet(world, 1)
    state = world[outlet_id]
    window = SETTINGS["burst_window_minutes"] * MINUTE

    burst = [t for t in state.provider_txns("bkash")
             if t.ts >= sim.now - window]
    assert len(burst) == 9
    assert all(t.type is TxnType.CASH_OUT for t in burst)
    assert burst[-1].ts - burst[0].ts <= window
    assert burst[-1].ts <= sim.now

    accounts = {t.sender_hash for t in burst}
    assert len(accounts) == 4, "burst should come from only a few accounts"
    assert len(accounts) <= SETTINGS["burst_max_accounts"]

    amounts = [t.amount for t in burst]
    mean = sum(amounts) / len(amounts)
    spread = (max(amounts) - min(amounts)) / mean
    assert spread <= SETTINGS["burst_amount_tolerance"], (
        f"burst amounts are not near-identical (spread {spread:.3%})")

    # And it is labelled as such.
    assert state.calendar_context == "ordinary"
    episode = _episode(sim, "anomaly")
    assert episode.outlet_id == outlet_id
    assert episode.provider_id == "bkash"


# --- scenario B2: legitimate Eid surge -------------------------------------

def test_scenario_b2_is_a_diverse_wide_surge_labelled_demand_spike():
    sim = Simulator(seed=11, outlets=6)
    world = sim.world()
    outlet_id = _outlet(world, 2)
    state = world[outlet_id]
    assert state.calendar_context == "eid_window"

    surge = [t for t in state.provider_txns("rocket")
             if t.ts >= sim.now - 20 * MINUTE]
    assert len(surge) >= 14
    assert all(t.type is TxnType.CASH_OUT for t in surge)

    accounts = {t.sender_hash for t in surge}
    assert len(accounts) >= SETTINGS["demand_spike_account_floor"], (
        "an Eid surge must not look like a handful of colluding accounts")

    amounts = [t.amount for t in surge]
    mean = sum(amounts) / len(amounts)
    spread = (max(amounts) - min(amounts)) / mean
    assert spread > SETTINGS["narrow_spread_ratio"], (
        "an Eid surge must have a wide amount spread, unlike a burst")

    episode = _episode(sim, "demand_spike")
    assert episode.outlet_id == outlet_id
    assert episode.provider_id == "rocket"


# --- scenario C: the deliberate break --------------------------------------

def test_scenario_c_is_an_unexplained_drift_labelled_data_quality():
    sim = Simulator(seed=11, outlets=6)
    world = sim.world()
    outlet_id = _outlet(world, 3)
    state = world[outlet_id]
    pos = state.positions["bkash"]

    computed = _reconciled(state, "bkash")
    drift = pos.balance - computed
    assert abs(drift - 25_000.0) < 1.0, f"expected a 25,000 drift, got {drift:.2f}"
    assert not pos.declared_reconciles(computed, SETTINGS["reconcile_tolerance"])
    assert pos.feed_status is FeedStatus.CONFLICTING

    episode = _episode(sim, "data_quality")
    assert episode.outlet_id == outlet_id
    assert episode.provider_id == "bkash"


def test_only_scenario_c_breaks_a_balance_chain():
    sim = Simulator(seed=11, outlets=6)
    world = sim.world()
    broken = []
    for outlet_id, state in world.items():
        for provider in PROVIDERS:
            if not state.positions[provider.id].declared_reconciles(
                    _reconciled(state, provider.id),
                    SETTINGS["reconcile_tolerance"]):
                broken.append((outlet_id, provider.id))
    assert broken == [(_outlet(world, 3), "bkash")], broken


# --- feed faults -----------------------------------------------------------

def test_one_outlet_has_a_stale_nagad_feed():
    sim = Simulator(seed=11, outlets=6)
    world = sim.world()
    stale = [(outlet_id, pid, pos)
             for outlet_id, state in world.items()
             for pid, pos in state.positions.items()
             if pos.feed_status is FeedStatus.STALE]
    assert len(stale) == 1
    outlet_id, pid, pos = stale[0]
    assert outlet_id == _outlet(world, 4)
    assert pid == "nagad"
    age = sim.now - pos.last_feed_at
    assert 44 * MINUTE <= age <= 46 * MINUTE, f"expected ~45 min stale, got {age}"


def test_only_the_planted_feeds_are_unhealthy():
    """Fresh feeds everywhere except the planted feed faults."""
    sim = Simulator(seed=11, outlets=8)
    world = sim.world()
    unhealthy = {(outlet_id, pid): pos.feed_status
                 for outlet_id, state in world.items()
                 for pid, pos in state.positions.items()
                 if pos.feed_status is not FeedStatus.FRESH}
    assert unhealthy == {
        (_outlet(world, 3), "bkash"): FeedStatus.CONFLICTING,
        (_outlet(world, 4), "nagad"): FeedStatus.STALE,
        (_outlet(world, 5), "rocket"): FeedStatus.DELAYED,
        (_outlet(world, 6), "bkash"): FeedStatus.MISSING,
    }
    for outlet_id, state in world.items():
        for pid, pos in state.positions.items():
            healthy = (outlet_id, pid) not in unhealthy
            if healthy:
                assert sim.now - pos.last_feed_at <= 45 * MINUTE


def test_one_world_reaches_every_feed_state():
    """All five rungs of the ladder, from one ordinary world.

    Two of them — delayed and missing — used to be unreachable: nothing ever
    produced a feed that was late without being stale, or one that was absent
    entirely, so half the fallback ladder could not be demonstrated at all.
    """
    sim = Simulator(seed=11, outlets=8)
    world = sim.world()
    planted: dict[FeedStatus, list[tuple[str, str]]] = {}
    for outlet_id, state in world.items():
        for pid, pos in state.positions.items():
            planted.setdefault(pos.feed_status, []).append((outlet_id, pid))

    assert set(planted) == set(FeedStatus), "a feed state is unreachable"
    degraded = [FeedStatus.DELAYED, FeedStatus.STALE, FeedStatus.CONFLICTING,
                FeedStatus.MISSING]
    for status in degraded:
        planted_times = len(planted[status])
        assert planted_times == 1, f"{status} planted {planted_times}x"
    # One fault per outlet, so each degraded outlet keeps two honest feeds to
    # be read against rather than three untrustworthy ones.
    assert len({outlet_id for status in degraded
                for outlet_id, _ in planted[status]}) == len(degraded)


def test_every_planted_feed_status_is_the_one_the_classifier_derives():
    """The plants are reachable states, not just labels.

    Replaying the model over the planted data must reproduce the state each
    position was given — for every position in the world, not only the faults.
    A planted state the classifier cannot derive is a state the product never
    actually reaches, however the data is labelled.
    """
    sim = Simulator(seed=11, outlets=8)
    world = sim.world()
    for outlet_id, state in world.items():
        for pid, pos in state.positions.items():
            drift = pos.balance - _reconciled(state, pid)
            derived = classify_feed(pos.last_feed_at, sim.now, drift)
            assert derived is pos.feed_status, (
                f"{outlet_id}/{pid} is labelled {pos.feed_status} but the model "
                f"derives {derived}")


def test_a_delayed_feed_sits_inside_the_delayed_band():
    """Late, but not stale — the rung exists only between the two thresholds."""
    sim = Simulator(seed=11, outlets=8)
    world = sim.world()
    delayed = [pos for state in world.values()
               for pos in state.positions.values()
               if pos.feed_status is FeedStatus.DELAYED]
    assert len(delayed) == 1
    age = sim.now - delayed[0].last_feed_at
    assert DELAYED_AFTER_S < age < STALE_AFTER_S, (
        f"a delayed feed must be older than {DELAYED_AFTER_S}s and younger "
        f"than {STALE_AFTER_S}s, got {age}s")


def test_a_missing_feed_has_no_timestamp_at_all():
    """Missing is read off the absence of a feed, so it must have none.

    An old-but-present stamp would classify as stale and quietly demonstrate
    the wrong rung of the ladder.
    """
    sim = Simulator(seed=11, outlets=8)
    world = sim.world()
    missing = [pos for state in world.values()
               for pos in state.positions.values()
               if pos.feed_status is FeedStatus.MISSING]
    assert len(missing) == 1
    assert missing[0].last_feed_at is None
    assert classify_feed(None, sim.now, 0.0) is FeedStatus.MISSING
