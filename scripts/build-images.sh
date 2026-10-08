#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

secret_args=()
if [[ -n "${CUSTOM_CA_CERT:-}" ]]; then
  if [[ ! -f "$CUSTOM_CA_CERT" ]]; then
    printf 'CUSTOM_CA_CERT does not name a readable file: %s\n' "$CUSTOM_CA_CERT" >&2
    exit 1
  fi
  secret_args+=(--secret "id=proxy_ca,src=$CUSTOM_CA_CERT")
fi

docker build "${secret_args[@]}" --tag ragops-api:local --file backend/Dockerfile .
docker build "${secret_args[@]}" --tag ragops-frontend:local --file frontend/Dockerfile .

