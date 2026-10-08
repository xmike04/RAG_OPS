# Contributing to RAGOps

Thanks for improving RAGOps. Changes should preserve the project's two central
properties: the default workflow works without paid credentials, and retrieval
behavior remains inspectable.

## Development workflow

1. Read [`docs/architecture.md`](docs/architecture.md) and the guide for the area
   you plan to change.
2. Create a focused branch from `main`.
3. Copy `.env.example` to `.env`; do not commit local secrets or generated data.
4. Make the smallest coherent change and add focused tests.
5. Run the relevant component checks, then the repository quality gates.
6. Explain behavior and operational effects in the pull request.

The usual full check is:

```bash
make lint
make typecheck
make test
make build
make eval
```

Run `make smoke` as well when a running API is available or when changing API,
database, Redis, worker, or Compose behavior.

## Change expectations

- Keep API resources workspace-scoped and retain request-ID propagation.
- Use UTC timestamps, UUIDs, structured logs, and typed interfaces.
- Avoid logging document content, prompts, generated answers, credentials, or
  authorization headers.
- Keep deterministic local provider behavior stable unless the change is
  intentional and the evaluation fixture is updated with an explanation.
- Include a migration for database schema changes. Test upgrades from the prior
  schema; do not edit an already released migration.
- Update public documentation when configuration, API shape, operating behavior,
  or security assumptions change.
- Do not mix broad formatting changes with functional work.

## Tests and evaluation

Unit tests belong beside their component. Root `tests/` is for cross-component
contract and live smoke checks. Tests must not require an external model key.

Retrieval changes should include:

- a focused test for ranking or fusion behavior;
- an offline evaluation run on `evals/datasets/queries.jsonl` (or a documented,
  versioned replacement);
- before/after metrics with the exact command and configuration;
- a note about regressions, including latency and citation metrics.

Do not tune on the evaluation set and then present it as an unbiased test set.
Add development queries separately when repeated iteration is required.

## Commits and pull requests

Use conventional commit subjects such as `feat(search): expose fusion scores` or
`fix(worker): make ingestion retry idempotent`. A pull request should state:

- the problem and chosen approach;
- user-visible and API changes;
- tests actually run and their results;
- migrations, compatibility, or rollout concerns;
- screenshots only when they reflect a real UI build.

## Reporting security issues

Do not open a public issue for a suspected vulnerability. Follow
[`SECURITY.md`](SECURITY.md) instead. Participation in this project is governed
by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
