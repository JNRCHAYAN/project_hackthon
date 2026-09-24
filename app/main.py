"""FastAPI application: JSON API plus the single-page dashboard.

Every number the dashboard renders comes from the snapshot this module serves.
The browser does no arithmetic on balances — it formats and displays. That keeps
one authoritative source for the figures and means the UI cannot disagree with
the analytics.

The provider boundary is enforced here as well as in the coordination layer:
a request that reaches across provider tracks gets a 403, not a silent success.
"""
from __future__ import annotations

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
    if scenario is not None and scenario not in engine.SCENARIO_COPY:
        raise HTTPException(status_code=422,
                            detail=f"unknown scenario: {scenario!r}")
    outlets = payload.get("outlets")
    if outlets is not None:
        try:
            outlets = max(1, min(60, int(outlets)))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="outlets must be an int")
    seed = payload.get("seed")
    if seed is not None:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="seed must be an int")
    demand = payload.get("demand_multiplier")
    if demand is not None:
        try:
            demand = max(0.1, min(5.0, float(demand)))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422,
                                detail="demand_multiplier must be a number")

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
    action = (payload.get("action") or "").strip()
    actor = (payload.get("actor") or "dashboard_user").strip()
    note = (payload.get("note") or "").strip()
    actor_provider = payload.get("actor_provider") or None
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
