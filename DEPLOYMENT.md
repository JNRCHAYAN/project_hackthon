# Deployment

**Live prototype:** _not yet deployed — see "Deploy your own" below._

## Host

Render, free tier, Python runtime, **Singapore** region — the closest Render
region to Bangladesh, which matters for dashboard latency. The deployment is
declarative: `render.yaml` in this repository is the whole configuration, so the
host reads it rather than requiring anyone to click through settings.

No database server, no cache server, no queue, no object storage. One web service
serving one process.

## Deploy your own

The repository is deploy-ready; creating the service needs your Render account, so
it is a two-minute manual step:

1. Push this repository to GitHub (already configured: `origin` →
   `https://github.com/JNRCHAYAN/project_hackthon.git`).
2. In the Render dashboard: **New → Blueprint**, and point it at the repository.
   Render reads `render.yaml` and proposes the service.
3. Render will prompt for `ANTHROPIC_AUTH_TOKEN` because the blueprint marks it
   `sync: false`. **Paste it to enable LLM narration, or leave it blank** — the
   application works fully either way (see Configuration).
4. Confirm the build. First build takes a few minutes.
5. Open the URL, and click through all four scenarios to confirm the deployed
   instance behaves like the local one.

Free-tier services sleep after 15 minutes of inactivity. That is worth reading
about before a live demo.

## Cold start — read this before demoing

A sleeping free-tier instance takes roughly **50 seconds** to answer its first
request, because the container is restarted and the engine builds its first
snapshot during startup.

**Warm it up before presenting.** Run this five minutes beforehand, and again if
more than fifteen minutes have passed with no traffic:

```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" https://<your-app>.onrender.com/healthz
```

The first call returns `200` after the cold start; subsequent calls are fast. An
external monitor (UptimeRobot, cron-job.org) pinging `/healthz` every 10 minutes
will also keep it awake, but note that Render's free tier is *designed* to sleep —
check that this is acceptable to you before relying on it.

## Configuration

| Variable | Purpose | Where |
|---|---|---|
| `ANTHROPIC_AUTH_TOKEN` | Enables LLM-generated narration phrasing | Render dashboard only — never committed |
| `PYTHON_VERSION` | Pins the runtime | `render.yaml` |
| `PYTHONUNBUFFERED` | Makes logs stream promptly | `render.yaml` |

**The application is fully functional without a token.** Narration falls back to
the deterministic Bengali/English template assembler, which produces a complete
alert — situation, evidence, uncertainty, and next steps — for every case. Only
the phrasing is less natural. Nothing else changes.

Two safety properties hold either way, and are worth stating explicitly because
they are the reason the LLM is optional rather than load-bearing:

- **No numeric value in any alert ever comes from the language model.** Balances,
  rates, intervals, and confidence figures are rendered directly from the analytics
  layer. The model supplies phrasing only, so it is structurally incapable of
  displaying a wrong number.
- **Forbidden vocabulary is rejected.** Model output is linted for `fraud`,
  `cheating`, `criminal`, `প্রতারণা`, `অপরাধ` and their equivalents before display.
  A response that fails the lint is discarded in favour of the template.

## Ephemeral storage

The free tier has **no persistent disk**. Two things live on disk and are therefore
recreated on every restart, redeploy, or wake from sleep:

- `data/audit.sqlite` — the append-only case-event log.
- `data/narrations/*.json` — the LLM narration cache.

**What this means.** Case history does not survive a redeploy: acknowledgements,
escalations, notes, and resolutions taken during a demo are lost when the instance
sleeps and restarts. Every value the application generates is recomputed from the
seed on startup, so the dashboard always renders correctly — but the *coordination
record* is transient.

This is acceptable for a prototype and is called out honestly rather than hidden.
In any real deployment the audit trail is a compliance artifact, and the same
design would require a managed Postgres instance with the append-only table
replicated off the ephemeral container. That change is one connection string in
`app/config.py`; it is a deployment decision, not an architectural one.

The narration cache is harmless to lose — it is a performance optimisation, and a
miss simply regenerates the phrasing.

## Limitations

- **Single instance.** No autoscaling, no redundancy, no failover. A restart is a
  brief outage.
- **No SLA.** Free tier, no uptime guarantee. Sleeps on idle by design.
- **Public URL, no authentication.** Anyone with the link sees the dashboard. This
  is safe only because every byte of data is synthetic — there is nothing private
  to protect. It would not be acceptable with real data.
- **Synthetic data only.** No provider system, wallet, or real balance is
  connected, and no financial transaction is possible from this application.
- **Demo-grade persistence.** See "Ephemeral storage" above.

## Verify a deployment

```bash
BASE=https://<your-app>.onrender.com

curl -s -o /dev/null -w "health  %{http_code}\n" $BASE/healthz
curl -s -o /dev/null -w "index   %{http_code}\n" $BASE/
curl -s -o /dev/null -w "state   %{http_code}\n" $BASE/api/state
curl -s $BASE/api/state | grep -cE "NaN|Infinity" || echo "no non-finite values"
curl -s $BASE/api/export -o evidence.json && echo "evidence pack downloaded"
```

Then confirm in the browser that the language toggle switches Bengali ↔ English,
that the scenario selector changes the world, and that acknowledging a case
appends to the case history. Finally, attempt a cross-provider case action and
confirm the boundary notice appears rather than a silent success.
