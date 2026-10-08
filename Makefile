SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

UV ?= uv
NPM ?= npm
COMPOSE ?= docker compose
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
NPM_CONFIG_CACHE ?= $(CURDIR)/.cache/npm
BUILDX_CONFIG ?= $(CURDIR)/.cache/buildx

export UV_CACHE_DIR
export NPM_CONFIG_CACHE
export BUILDX_CONFIG

.DEFAULT_GOAL := help

.PHONY: help install backend-install frontend-install lint backend-lint frontend-lint \
	typecheck backend-typecheck frontend-typecheck test backend-test frontend-test cross-test \
	frontend-build build config up up-observability down migrate seed smoke eval

help: ## Show available development commands.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "%-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: backend-install frontend-install ## Install locked backend and frontend development dependencies.

backend-install:
	cd backend && $(UV) sync --frozen --extra dev

frontend-install:
	cd frontend && $(NPM) ci

lint: backend-lint frontend-lint ## Run backend and frontend linters.

backend-lint:
	cd backend && $(UV) run --frozen ruff check .

frontend-lint:
	cd frontend && $(NPM) run lint

typecheck: backend-typecheck frontend-typecheck ## Run backend and frontend static type checks.

backend-typecheck:
	cd backend && $(UV) run --frozen mypy

frontend-typecheck:
	cd frontend && $(NPM) run typecheck

test: backend-test frontend-test cross-test ## Run all unit and cross-component tests.

backend-test:
	cd backend && $(UV) run --frozen pytest

frontend-test:
	cd frontend && $(NPM) test

cross-test:
	python3 -m unittest discover -s tests -p 'test_*.py' -v

frontend-build: ## Build the production frontend assets.
	cd frontend && $(NPM) run build

build: ## Build local API and frontend container images.
	./scripts/build-images.sh

config: ## Validate the complete Compose model, including optional observability services.
	$(COMPOSE) --profile observability config --quiet

up: build ## Start the core stack and wait for health checks.
	$(COMPOSE) up -d --no-build --wait postgres redis api worker frontend

up-observability: build ## Start the core stack plus Prometheus and Grafana.
	$(COMPOSE) --profile observability up -d --no-build --wait

down: ## Stop all services while retaining named-volume data.
	$(COMPOSE) --profile observability down --remove-orphans

migrate: build ## Apply all database migrations to the local Compose database.
	$(COMPOSE) up -d --no-build --wait postgres redis
	$(COMPOSE) run --rm --no-deps api alembic upgrade head

seed: ## Load deterministic sample documents through the running API.
	python3 scripts/seed.py

smoke: ## Exercise liveness, readiness, metrics, and a core API read.
	python3 scripts/smoke.py

eval: ## Run the deterministic retrieval evaluation suite.
	python3 evals/evaluate.py \
		--queries evals/datasets/queries.jsonl \
		--corpus evals/datasets/corpus.jsonl \
		--run evals/runs/reference.jsonl \
		--k 1,3,5

