"""Project-wide configuration.

Values live here rather than in scattered literals so that the analytics
thresholds — which are analytical judgement calls, not constants of nature —
are visible in one place and auditable.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SETTINGS = {
    "root": ROOT,
    "db_path": ROOT / "data" / "audit.sqlite",

    # --- LLM narration -----------------------------------------------------
    # Only these parameters are known to work against this endpoint.
    "llm_base_url": "https://agentrouter.org",
    "llm_model": "deepseek-v4-flash",
    # A reasoning model emits a `thinking` block before its answer; below
    # roughly 2000 tokens the visible response is truncated away entirely.
    "llm_max_tokens": 2000,
    "llm_timeout_s": 8.0,

    # --- Liquidity ---------------------------------------------------------
    "trailing_window_minutes": 60,

    # --- Anomaly -----------------------------------------------------------
    "burst_window_minutes": 12,
    "burst_amount_tolerance": 0.02,
    "burst_max_accounts": 5,
    "reconcile_tolerance": 0.01,

    # --- Context classification -------------------------------------------
    # Thresholds separating an ordinary demand spike from a pattern that
    # needs review. These are judgement calls; see RESPONSIBLE_DESIGN.md.
    "demand_spike_account_floor": 8,
    "narrow_spread_ratio": 0.05,

    # --- Alerts ------------------------------------------------------------
    "alert_horizon_hours": 6.0,
    # An alert is an assertion that somebody should act, so it needs more to
    # stand on than a number. Below these floors the projection is still shown
    # on the outlet card, but it raises no alert: a steep slope fitted through
    # three noisy points is not a finding, and flooding the top of the queue
    # with those would cost an analyst the real ones.
    "min_alert_confidence": 0.5,
    "min_alert_points": 5,

    # --- Network / hotspot -------------------------------------------------
    "hotspot_min_outlets": 2,
    "network_min_shared_accounts": 3,

    # --- Calendar context --------------------------------------------------
    # Eid-ul-Fitr 2026 falls around 20 March. Eid is the scenario the problem
    # statement describes, so the demo clock is placed on the afternoon before
    # it (15:20 Dhaka time) rather than on an arbitrary date. This matters:
    # the context classifier is only worth having if the demo exercises it.
    # Both values live here so the clock and the window cannot drift apart —
    # they once did, and the classifier went silent without anything failing.
    "eid_ul_fitr_2026": 1_773_964_800.0,        # 2026-03-20T00:00Z
    "eid_window_days": 3.0,                     # +/- band treated as context
    "demo_clock": 1_773_912_000.0,              # 2026-03-19T09:20Z = 15:20 Dhaka
}
