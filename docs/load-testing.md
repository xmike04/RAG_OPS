# HTTP load testing

This guide measures the live RAGOps stack under controlled concurrent traffic.
It does not establish retrieval relevance, and one laptop run does not establish
production capacity.

## Scope and workload identity

Each report must identify the endpoint mix and provider profile. At minimum,
separate these profiles rather than combining their numbers:

- deterministic local providers, useful for application/database overhead;
- learned local embedding and reranking models, useful for CPU/GPU inference;
- remote generation, which includes provider/network behavior and may incur cost.

The runner's resolved workload belongs in the retained environment/summary
artifacts: request method/path, payload template or query-set checksum, endpoint
weights, concurrency, warmup, measured duration, timeouts, and success criteria.
Do not include secrets or sensitive document/query text.

## Dataset provenance and state

The default smoke corpus from `scripts/seed.py` is deterministic demonstration
data, not a representative production corpus. For a release load run, record:

- corpus generator or source, license/classification, immutable revision, and
  normalization steps;
- document, chunk, and indexed-byte counts plus a corpus checksum;
- query workload source/revision and checksum;
- database migration revision, index definitions, and PostgreSQL statistics
  state;
- whether caches and model weights are cold or warm.

Use an isolated environment. Reusing a volume after repeated seeding changes the
corpus and invalidates a comparison unless that state is explicitly recorded.

## Reproduce the baseline

Start, migrate, and seed the credential-free stack, then run the standard
30-second profile after ten warmup requests:

```bash
make up
make migrate
make seed
python3 benchmarks/load/run.py \
  --duration 30 \
  --concurrency 8 \
  --warmup 10 \
  --hardware-note '<machine/CPU/RAM>' \
  --output-dir benchmarks/load/results
```

Replace the hardware note with an exact, non-sensitive description. The runner
writes machine-readable artifacts:

```text
benchmarks/load/results/
├── environment.json
├── requests.jsonl
└── summary.json
```

- `environment.json` records git revision, resolved test configuration, platform,
  and the supplied hardware note.
- `requests.jsonl` contains the stable request-ID order and outcome for every
  measured request, including errors.
- `summary.json` reports request counts, throughput, latency
  p50/p95/p99/min/max, and error information.

Generated results are ignored by version control. Copy the reviewed release run
to immutable release storage, retain its checksums, and link that location from
the release notes. Never edit a summary without also invalidating its checksum.

## Hardware and environment record

The hardware note is not enough on its own. Before publication, verify the
environment artifact captures or accompanies:

- host/cloud instance type, CPU model and allocated cores, RAM, storage type;
- GPU model/count, driver/runtime, power mode, and dtype when applicable;
- operating system/kernel, Docker/Compose, image digests, and resource limits;
- PostgreSQL/Redis versions and effective memory/connection settings;
- API/worker replica counts and process concurrency;
- network placement and latency to remote providers;
- background load, monitoring profile, and test UTC interval;
- provider/model IDs and immutable revisions.

For remote providers, record rate limits, region, retries, and cost-accounting
method without recording credentials.

## Measurement validity

Warm model weights, database connections, and indexes according to the declared
policy, then exclude only the explicit warmup phase. Count HTTP failures,
timeouts, and invalid responses; a run with hidden failures is not a throughput
result. Check client CPU and network saturation so the load generator is not the
bottleneck.

Repeat the run at least three times for a release comparison and retain each raw
artifact. Report the median run with the observed range, or pool raw requests
only when the environment and workload are identical. Increase concurrency in
separate steps to locate saturation; do not extrapolate linearly beyond measured
points.

## Results placeholder

No live load result is claimed until a reviewed `summary.json` and matching
environment artifact exist. Root release preparation replaces only the nulls
below from retained artifacts.

```json
{
  "status": "pending_measurement",
  "summary_artifact": "benchmarks/load/results/summary.json",
  "environment_artifact": "benchmarks/load/results/environment.json",
  "git_revision": null,
  "workload_checksum": null,
  "hardware_fingerprint": null,
  "provider_profile": null,
  "measured_results": null
}
```

## Production implications

Treat throughput and latency as bounds for the recorded topology, workload, data
size, and provider profile. Production sizing must also account for ingestion,
tenant skew, larger corpora, long queries/documents, remote-provider variance,
deployments, backups, failover, and observability overhead.

Use p95/p99 and error rate—not throughput alone—for capacity decisions. Leave
headroom below the first saturation point, load-test the failure policy, and set
alerts from a production-representative baseline. Run the retrieval benchmark
separately to ensure a faster configuration did not trade away quality.
