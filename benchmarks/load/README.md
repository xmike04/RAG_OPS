# Search HTTP load benchmark

This dependency-light benchmark uses Python's standard library to send bounded,
concurrent `POST /v1/search` requests. Search is a read-only operation even
though its structured request body uses POST. The checked-in
`search-workload.json` records the canonical steady workload.

Prepare the credential-free local stack and its demo corpus:

```bash
make up
make migrate
make seed
```

Run the canonical 30-second workload and record the machine description used to
interpret the result:

```bash
python3 benchmarks/load/run.py \
  --duration 30 \
  --concurrency 8 \
  --warmup 10 \
  --hardware-note '8 vCPU, 16 GiB RAM, local Docker' \
  --output-dir benchmarks/load/results
```

For a fixed-size run, replace `--duration 30` with `--requests 500`. Other useful
controls are `--base-url`, `--workspace-id`, `--query`, `--top-k`, `--no-rerank`,
and `--timeout`. If API authentication is enabled, set `RAGOPS_API_KEY`; the key
is sent as `X-API-Key` but is never written to output.

The output directory contains:

- `environment.json`: full Git SHA and dirty flag, effective non-secret config,
  Python/platform details, logical CPU count, and the hardware note.
- `requests.jsonl`: one stable request-ID-ordered row per measured request, with
  status, error category, and latency but no response or document content.
- `summary.json`: environment/config plus warmup and measured success/error
  counts, throughput, status/error categories, and successful-request latency
  min/p50/p95/p99/max.

Latency uses a nearest-rank percentile. Throughput counts every completed request
over measured wall time. Latency percentiles include successful measured requests
only; failures remain visible in the counters and raw request artifact. The tool
returns a nonzero status when any measured request fails.

