#!/usr/bin/env bash
# Entrypoint forwarding to scripts/run_evals.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/scripts/run_evals.sh" "$@"
