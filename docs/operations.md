# Operations runbook

## First response

1. Confirm the incident time range and affected environment/workspaces.
2. Check `/health`, then `/ready`; preserve the response `X-Request-ID`.
3. Check request rate, error rate, p50/p95 latency, and ingestion queue depth.
4. Correlate API and worker structured logs by request, job, or trace ID.
5. Determine whether the fault is API, PostgreSQL, Redis/queue, provider, worker,
   or client specific before restarting anything.

Do not copy document text, prompts, answers, credentials, or authorization
headers into incident channels.

## Signals

| Signal | Interpretation | Next check |
| --- | --- | --- |
| `/health` fails | Process unavailable or wedged | Container state, crash loop, resource pressure |
| `/health` passes; `/ready` fails | Required dependency unavailable | Database/Redis connectivity and migrations |
| Queue depth grows | Workers slow, stopped, or retrying | Worker replicas, provider latency, failure categories |
| API p95 rises; queue stable | Search/generation or DB path slow | Stage latency in query traces |
| Error rate rises for one provider | Provider-specific failure | Timeouts, quota, safe fallback policy |
| No new metrics | Scrape path or service unavailable | Prometheus target status and `/metrics` |

Prometheus labels must stay bounded. Use logs/traces—not high-cardinality metric
labels—for workspace, document, query, request, and job identifiers.

## Common procedures

### Readiness failure

Check API logs for the failing dependency, then validate PostgreSQL and Redis
independently from the same network boundary as the API. Verify configuration
names and migration state. A liveness restart will not fix a dependency outage.

### Stalled ingestion

Compare pending/running job age with queue depth and worker heartbeats. Inspect a
representative job's safe error category. Restore the dependency or worker first;
then retry only jobs whose processing is idempotent. Do not mark jobs successful
or edit chunk rows manually.

### Elevated query latency

Use trace stage timings to separate embedding, lexical, vector, fusion,
reranking, and generation. Check database query plans and index health for
retrieval regressions. If one optional provider is failing, apply the documented
fail-open policy; do not silently change answer semantics during an incident.

### Bad or irrelevant answers

Capture query/trace IDs, configuration revision, and affected document IDs—not
sensitive content in general logs. Inspect retrieved chunks before generation.
If evidence is absent, investigate ingestion/retrieval. If evidence is present
but the answer is unsupported, investigate generation and citation validation.
Run the offline evaluation before and after a candidate fix.

## Backup and recovery

PostgreSQL contains durable application state and requires scheduled, encrypted
backups with retention and access controls. Redis is treated as reconstructable
queue/cache state, but recovery procedures must account for accepted pending jobs.

A backup is not proven until restoration is tested. A recovery exercise should:

1. restore into an isolated environment;
2. run migrations in the supported direction;
3. verify representative document, chunk, job, and trace counts;
4. submit and retrieve a new document;
5. record recovery time and data-loss window.

## Deployments and migrations

- Back up before a destructive or hard-to-reverse migration.
- Prefer expand/migrate/contract changes compatible with adjacent versions.
- Run schema migration as one controlled job, not in every API replica.
- Gate traffic on readiness and observe errors/latency after rollout.
- Roll back application code only when its schema compatibility is known.

## Capacity and alerting

Set thresholds from measured baselines, not the example repository. Useful alerts
cover sustained readiness failure, server-error ratio, queue age/depth, worker
absence, PostgreSQL saturation, disk growth, and provider timeout/error rate.
Alert on symptoms that require action; dashboards can carry exploratory signals.

## Incident closeout

Document impact, time line, detection gap, root cause, contributing factors,
mitigation, and durable follow-ups. Link request/job/trace identifiers and metric
snapshots that do not expose document contents. Add a regression test or runbook
change when it would have shortened diagnosis or prevented recurrence.
