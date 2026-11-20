#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

docker compose --profile scaffold up -d agent-canary prod-canary
trap 'docker compose --profile scaffold down --remove-orphans' EXIT

agent_container=$(docker compose ps -q agent-canary)
prod_container=$(docker compose ps -q prod-canary)
[[ -n "$agent_container" ]]
[[ -n "$prod_container" ]]

agent_networks=$(docker inspect "$agent_container" --format '{{json .NetworkSettings.Networks}}')
prod_networks=$(docker inspect "$prod_container" --format '{{json .NetworkSettings.Networks}}')
python3 - "$agent_networks" "$prod_networks" <<'PY'
import json, sys
agent=json.loads(sys.argv[1]); prod=json.loads(sys.argv[2])
assert "asdi-agent" in agent, agent
assert "asdi-prod" in prod, prod
assert not (set(agent) & set(prod)), set(agent) & set(prod)
PY

if docker exec "$agent_container" getent hosts prod-canary >/tmp/asdi-agent-resolves-prod 2>/dev/null; then
  echo 'agent resolved prod-canary; zone isolation failed' >&2
  cat /tmp/asdi-agent-resolves-prod >&2
  exit 1
fi

if docker exec "$agent_container" bash -c 'timeout 2 bash -c "exec 3<>/dev/tcp/prod-canary/80"' >/dev/null 2>&1; then
  echo 'agent connected to prod-canary; zone isolation failed' >&2
  exit 1
fi

echo 'zone isolation verified: agent cannot resolve or connect to prod'
