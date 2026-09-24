"""FastAPI application: JSON API plus the single-page dashboard.

Every number the dashboard renders comes from the snapshot this module serves.
The browser does no arithmetic on balances — it formats and displays. That keeps
one authoritative source for the figures and means the UI cannot disagree with
the analytics.

The provider boundary is enforced here as well as in the coordination layer:
a request that reaches across provider tracks gets a 403, not a silent success.
"""
from __future__ import annotations

import math
import threading
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import SETTINGS
from app.engine import Engine

_engine: Engine | None = None
_lock = threading.Lock()
STATIC_DIR = SETTINGS["root"] / "static"


def _as_int(raw, field: str, low: int | None = None,
            high: int | None = None) -> int:
    """Coerce a request field to an int, optionally clamped, or raise 422.

    ``int()`` inside an ``except (TypeError, ValueError)`` looks like it covers
    everything and does not. A JSON number too large for a float parses to
    infinity, and ``int(inf)`` raises ``OverflowError`` — a subclass of neither
    — so ``{"outlets": 1e400}`` answered 500. A list raises ``TypeError``, which
    is caught, but a bool is an int subclass and would sail through as 1 or 0.
    Every one of these is the caller sending the wrong shape, which is a 422:
    a 500 blames the server for the client's mistake and hides the real faults
    in the logs.

    Bounds are optional so that a field with no meaningful range (the seed) is
    validated without also being silently clamped — quietly replacing a
    caller's number with a different one is its own kind of wrong answer.
    """
    if isinstance(raw, bool):
        raise HTTPException(status_code=422, detail=f"{field} must be an int")
    # A float is accepted only when it is a whole number. JSON encoders are not
    # obliged to distinguish 12 from 12.0, so a client that arrived at a count by
    # arithmetic may send either and both name the same quantity. 12.7 names no
    # outlet count, and ``int()`` would quietly make it 12 — the caller would get
    # back a different number from the one they sent and nothing would say so.
    # Non-finite values fall here too: neither infinity nor NaN is a whole
    # number, so they are refused before ``int()`` can raise ``OverflowError``.
    if isinstance(raw, float) and not raw.is_integer():
        raise HTTPException(status_code=422, detail=f"{field} must be an int")
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=422, detail=f"{field} must be an int")
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def _bounded_float(raw, low: float, high: float, field: str) -> float:
    """Coerce a request field to a finite float in ``[low, high]``, or raise 422.

    Infinity and NaN are rejected rather than clamped. ``min``/``max`` with a
    NaN operand return whichever argument the comparison happened to favour, so
    ``{"demand_multiplier": NaN}`` was silently becoming 5.0 — a number the
    caller never asked for, presented as their own input.
    """
    if isinstance(raw, bool):
        raise HTTPException(status_code=422, detail=f"{field} must be a number")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=422,
                            detail=f"{field} must be a number")
    if not math.isfinite(value):
        raise HTTPException(status_code=422,
                            detail=f"{field} must be a finite number")
    return max(low, min(high, value))


def _text(raw, field: str, default: str = "") -> str:
    """Coerce a request field to a stripped string, or raise 422.

    ``(payload.get("action") or "").strip()`` reads as though it handles every
    input, but a list or a number reaches ``.strip`` and raises
    ``AttributeError``, which surfaced as a 500.
    """
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise HTTPException(status_code=422, detail=f"{field} must be a string")
    return raw.strip()


def get_engine() -> Engine:
    """One engine per process, rebuilt in place on demand."""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = Engine()
    return _engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Build the first snapshot before the first request, so the dashboard
    never opens on an empty frame."""
    get_engine()
    yield


app = FastAPI(title="Super Agent Liquidity & Risk Intelligence Platform",
              version="1.0.0",
              lifespan=lifespan,
              description=("Agent-network liquidity, data-quality and "
                           "coordination intelligence. All data is synthetic."))


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/state")
def state() -> dict:
    """The whole dashboard, in one response.

    One request rather than a dozen: the snapshot is internally consistent by
    construction, and parallel calls could otherwise render a torn view where
    the headline total and the outlet list disagree.
    """
    return get_engine().snapshot


@app.get("/api/metrics")
def metrics() -> dict:
    return get_engine().snapshot.get("metrics", {})


@app.post("/api/simulate")
def simulate(payload: dict = Body(default={})) -> dict:
    """Rebuild the world: scenario, network size, seed, or a demand what-if.

    Changing the world discards the previous alerts, so any case a human had
    already actioned is re-created with its status preserved.
    """
    engine = get_engine()
    scenario = payload.get("scenario")
    # `scenario not in <dict>` raises TypeError on an unhashable value, so the
    # type is checked before the membership test rather than instead of it.
    if scenario is not None:
        if not isinstance(scenario, str) or scenario not in engine.SCENARIO_COPY:
            raise HTTPException(status_code=422,
                                detail=f"unknown scenario: {scenario!r}")
    outlets = payload.get("outlets")
    if outlets is not None:
        outlets = _as_int(outlets, "outlets", low=1, high=60)
    seed = payload.get("seed")
    if seed is not None:
        seed = _as_int(seed, "seed")
    demand = payload.get("demand_multiplier")
    if demand is not None:
        demand = _bounded_float(demand, 0.1, 5.0, "demand_multiplier")

    with _lock:
        snapshot = engine.rebuild(scenario=scenario, outlets=outlets, seed=seed,
                                  demand_multiplier=demand)
    return snapshot


@app.get("/api/alerts/{alert_id}")
def alert_detail(alert_id: str) -> dict:
    engine = get_engine()
    alert = engine.alerts.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    payload = Engine._alert_payload(alert)
    payload["history"] = engine.history(alert_id)
    return payload


@app.post("/api/alerts/{alert_id}/action")
def alert_action(alert_id: str, payload: dict = Body(default={})) -> dict:
    """Acknowledge, escalate, resolve or note a case.

    Two guardrails live behind this endpoint: an unsupported verb is rejected
    with 422, and an action that crosses a provider boundary is rejected with
    403. Neither can be bypassed from the browser, because neither is decided
    in the browser.
    """
    engine = get_engine()
    action = _text(payload.get("action"), "action")
    actor = _text(payload.get("actor"), "actor", "dashboard_user") \
        or "dashboard_user"
    note = _text(payload.get("note"), "note")
    actor_provider = payload.get("actor_provider")
    if actor_provider is not None:
        # Stripped before it is compared, so " nagad" is treated as the same
        # declaration as "nagad" rather than as a different, foreign track.
        actor_provider = _text(actor_provider, "actor_provider") or None
    try:
        return engine.act(alert_id, action, actor, note, actor_provider)
    except KeyError:
        raise HTTPException(status_code=404, detail="alert not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except PermissionError as exc:
        return JSONResponse(status_code=403,
                            content={"detail": str(exc),
                                     "boundary": "provider tracks are separate; "
                                                 "coordinate through the "
                                                 "approved channel"})


@app.get("/api/cases")
def cases(alert_id: str | None = None) -> list[dict]:
    return get_engine().history(alert_id)


@app.get("/api/export")
def export() -> JSONResponse:
    """Download the full snapshot as an evidence pack.

    Everything needed to reproduce a finding — thresholds, projections, feed
    status, classification, rejected hypotheses — travels in one file, so a
    reviewer does not have to take the dashboard's word for anything.
    """
    engine = get_engine()
    payload = dict(engine.snapshot)
    payload["thresholds"] = {k: v for k, v in SETTINGS.items()
                             if k != "root" and not hasattr(v, "__fspath__")}
    payload["case_history"] = engine.history()
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition":
                 'attachment; filename="liquidity-risk-evidence.json"'})


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))
