#!/usr/bin/env bash
# Registry-driven Apple Container deployment. No fixed workspace list or port map.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m env_rag_final.access.deployment "$@"
