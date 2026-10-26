# Controlled mixed-query load matrix

The measurement uses 30 training-query IDs selected with a recorded seed and
round-robin requests. Warm conditions use concurrency 1, 4, and 8, 300 measured
requests each, and 30 warmups. Requests use the frozen serving corpus, a
100-chunk result window, no reranking, and matching local hash providers.
Held-out relevance results are not used to tune the load conditions.

First-search observations use fresh API processes with ready PostgreSQL/Redis
dependencies. The CLI verifies an available PID before consuming a search,
a zero search-request counter before it, the same PID/start ticks afterward,
and exactly one accepted search afterward. Invalid observations are preserved
and exit nonzero. The orchestrator must still control the restart and establish
that the observed PID serves the tested origin; the CLI flag alone is insufficient.

The five first-search observations use recorded seeded training queries and distinct
API identities: the initial API after ingestion, then four newly restarted APIs. Database and OS caches are retained. They are not host/database
cold starts or a paired estimate of cold-start penalty against the warm mix.
Five observations do not support a reliable tail-latency claim.

Throughput is closed-loop, with latency measured around each HTTP operation.
Client executor queue time is excluded from request latency. This is not an
open-loop arrival-rate study or a production capacity/SLO.

API/worker CPU is an OS tick delta over the measured request window, reported
relative to one CPU core. RSS is sampled at the window's start and end; shared
pages may be included and no peak-memory claim is made. Missing process data
is null, not zero. PostgreSQL/Redis CPU and billing are not attributed to requests.

Warmup failures retain safe categories and query IDs separately from measured
requests. A body that is empty despite a success status is a failed semantic check.
Captured provider/model metadata must agree with every measured response.

Every output records UTC time, serving revision, measurement implementation
revision/hash, seed/query mix, corpus/configuration, stage/HTTP timings,
request outcomes, and the raw process snapshots. Never overwrite a condition.
Use the exact script and a captured runtime from the same serving processes.

```bash
python3 -m benchmarks.service.load_matrix \
  --ingest-dir benchmarks/service/results/load-run \
  --runtime benchmarks/service/results/load-run/runtime.json \
  --output benchmarks/service/results/load-run/warm-c4.json \
  --concurrency 4 --requests 300 --warmup 30 \
  --api-pid <observed-api-pid> --worker-pid <observed-worker-pid>
```

A process-first observation additionally uses
`--phase first-search-after-api-restart --requests 1 --warmup 0 --concurrency 1`
after the orchestrator has started and identified the new API process.
No generation, learned inference, peak RSS, GPU usage, dollar cost, or
production reliability claim follows from this local-provider matrix.

The locked FastAPI 0.143 router exposes the included template `/search` in
Prometheus; earlier versions exposed `/v1/search`. The parser counts only these
two search labels. A real HTTP integration check verifies its counter delta.
The initial collection 40387499975 was rejected because the old parser looked
only for the prefixed label. Its raw observations are retained separately with
invalid first-search status; they are not silently promoted to valid measurements.
