#!/usr/bin/env bash
# ==============================================================================
# MindBridge LLM Evaluation Suite Runner
# ==============================================================================
# Usage:
#   ./run_evals.sh                  # Live evaluation against NVIDIA NIM LLM
#   ./run_evals.sh --curl           # Live evaluation showing curl commands in logs
#   ./run_evals.sh -v               # Verbose mode with detailed case-by-case trace
#   ./run_evals.sh --mock           # Fast offline dry-run without API calls
# ==============================================================================

set -euo pipefail

# Determine project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/backend/app.py" ]]; then
    PROJECT_ROOT="${SCRIPT_DIR}"
elif [[ -f "${SCRIPT_DIR}/../backend/app.py" ]]; then
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    PROJECT_ROOT="$(pwd)"
fi

cd "${PROJECT_ROOT}"

# Activate virtual environment if present
if [[ -f "venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
elif [[ -f ".venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# Map friendly flags
ARGS=()
for arg in "$@"; do
    case "${arg}" in
        --mock)
            ARGS+=("--mock-llm")
            ;;
        *)
            ARGS+=("${arg}")
            ;;
    esac
done

export PYTHONPATH="${PROJECT_ROOT}/backend:${PYTHONPATH:-}"

echo "========================================================================"
echo "Running MindBridge LLM Evaluation Suite..."
echo "Project root: ${PROJECT_ROOT}"
echo "========================================================================"

python3 -m services.evals.run_evals ${ARGS[@]+"${ARGS[@]}"}
