"""MindBridge LLM Evaluation Framework.

Provides offline evaluation metrics, fixture loaders, and CLI runners
for validating clinical boundaries, crisis containment, factual grounding,
distress-adapted conciseness, and therapeutic alignment.
"""

from .dataset import EvalCase, load_fixtures
from .metrics import (
    evaluate_boundary_adherence,
    evaluate_conciseness,
    evaluate_crisis_containment,
    evaluate_factual_grounding,
    evaluate_therapeutic_tone,
)

__all__ = [
    "EvalCase",
    "load_fixtures",
    "evaluate_boundary_adherence",
    "evaluate_crisis_containment",
    "evaluate_factual_grounding",
    "evaluate_conciseness",
    "evaluate_therapeutic_tone",
]
