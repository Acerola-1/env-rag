#!/usr/bin/env bash
# Start / stop / inspect the two fixed LightRAG instances (air, water).
#
# Uses the Apple Container runtime already present on this machine, matching how
# LightRAG is run here; the Docker Compose equivalent lives in
# deployment/docker-compose.workspaces.yml.
#
#   scripts/wa_instances.sh start|stop|status|health|logs <air|water|all>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT/.local/workspace-access/env"
IMAGE="${LIGHTRAG_IMAGE:-ghcr.io/hkuds/lightrag:latest}"
NETWORK="${LIGHTRAG_NETWORK:-lightrag-net}"

WORKSPACES="${WA_WORKSPACES:-air water}"
port_for() { case "$1" in air) echo 9622;; water) echo 9623;; coastal) echo 9624;; *) echo "";; esac; }
key_for() {
  python3 - "$1" <<'PY'
import json, sys
from pathlib import Path
root = Path(__file__).resolve() if False else None
import os
p = Path(os.environ["ENV_DIR"]) / ".." / "instance-keys.json"
print(json.loads(p.read_text())[sys.argv[1]])
PY
}

start_one() {
  local ws="$1" port
  port="$(port_for "$ws")"
  if container list --all 2>/dev/null | awk '{print $1}' | grep -qx "lightrag-$ws"; then
    container start "lightrag-$ws" >/dev/null 2>&1 || container start "lightrag-$ws"
    echo "started existing lightrag-$ws"
    return
  fi
  container run -d --name "lightrag-$ws" --network "$NETWORK" \
    -p "127.0.0.1:${port}:9621" \
    --env-file "$ENV_DIR/lightrag-$ws.env" \
    "$IMAGE" >/dev/null
  echo "created lightrag-$ws on 127.0.0.1:${port}"
}

wait_ready() {
  local ws="$1" port key i
  port="$(port_for "$ws")"
  export ENV_DIR
  key="$(key_for "$ws")"
  for i in $(seq 1 90); do
    if curl -fsS -m 3 -H "X-API-Key: $key" "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
      echo "lightrag-$ws healthy after ${i}s"; return 0
    fi
    sleep 1
  done
  echo "lightrag-$ws did not become healthy" >&2
  container logs "lightrag-$ws" 2>&1 | tail -20 >&2 || true
  return 1
}

case "${1:-}" in
  start)
    for ws in $WORKSPACES; do start_one "$ws"; done
    for ws in $WORKSPACES; do wait_ready "$ws"; done
    ;;
  stop)
    for ws in $WORKSPACES; do container stop "lightrag-$ws" 2>/dev/null || true; done
    echo "stopped"
    ;;
  status)
    container list --all 2>/dev/null | grep -E "ID|lightrag-(air|water)" || true
    ;;
  health)
    export ENV_DIR
    for ws in $WORKSPACES; do
      port="$(port_for "$ws")"; key="$(key_for "$ws")"
      echo -n "lightrag-$ws http://127.0.0.1:${port}: "
      curl -fsS -m 5 -H "X-API-Key: $key" "http://127.0.0.1:${port}/health" && echo || echo "UNHEALTHY"
    done
    ;;
  logs)
    container logs "${2:-lightrag-air}" 2>&1 | tail -50
    ;;
  *)
    echo "usage: $0 start|stop|status|health|logs [air|water]" >&2
    exit 2
    ;;
esac
