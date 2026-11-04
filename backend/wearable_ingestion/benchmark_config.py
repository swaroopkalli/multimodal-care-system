"""Single-patient benchmark identity shared by the demo seed and wearable tools."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATIENT_ID_FILE = _REPO_ROOT / ".benchmark_patient_id"


def benchmark_patient_id() -> int | None:
    """Return the configured benchmark patient, or None when benchmark mode is unset."""
    raw = os.getenv("BENCHMARK_PATIENT_ID")
    stored = _PATIENT_ID_FILE.read_text(encoding="utf-8").strip() if _PATIENT_ID_FILE.exists() else None
    if raw is not None and stored and raw.strip() != stored:
        raise RuntimeError("BENCHMARK_PATIENT_ID does not match the patient initialized by the seed script")
    if raw is None:
        raw = stored
    if raw is None or not raw.strip():
        return None
    try:
        patient_id = int(raw)
    except ValueError as exc:
        raise RuntimeError("BENCHMARK_PATIENT_ID must be a positive integer") from exc
    if patient_id <= 0:
        raise RuntimeError("BENCHMARK_PATIENT_ID must be a positive integer")
    return patient_id
