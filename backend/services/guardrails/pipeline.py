"""Bounded generate -> validate -> (corrective retry | safe fallback) loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from .output_guard import check_output
from .policy import CORRECTION_TEXT, FALLBACK_PATIENT, FALLBACK_STAFF, max_retries

log = logging.getLogger(__name__)


@dataclass
class GuardedReply:
    text: str
    action: str                      # allowed | fallback
    attempts: int = 0                # corrective retries used
    categories: list[str] = field(default_factory=list)


def correction_instruction(categories: list[str]) -> str:
    reasons = "; ".join(CORRECTION_TEXT.get(c, c) for c in dict.fromkeys(categories))
    return (
        f"SAFETY CORRECTION: your previous reply was rejected because {reasons}. "
        "Rewrite it so that it only summarises what the patient reported and what the data shows, describes "
        "patterns with appropriate uncertainty, and never tells anyone to start, stop, change or dose a "
        "medication, never names a medication or dose the patient did not mention, never states a diagnosis "
        "as fact, and suggests speaking with their doctor or pharmacist where relevant."
    )


def run_guarded(role: str, generate: Callable[[str | None], str], source_text: str = "",
                extra_drugs=(), retries: int | None = None) -> GuardedReply:
    """``generate(correction)`` returns a draft; ``correction`` is None on the first attempt.

    Unsafe text is never returned: after the bounded retries (or if the guard itself
    errors) the fixed fallback is used. LLM errors propagate to the caller.
    """
    limit = max_retries() if retries is None else max(0, min(retries, 2))
    correction = None
    categories: list[str] = []
    for attempt in range(limit + 1):
        draft = generate(correction)
        try:
            violations = check_output(draft, role, source_text, extra_drugs)
        except Exception:
            log.exception("output guard failed; failing closed")
            return GuardedReply(FALLBACK_STAFF if role == "staff" else FALLBACK_PATIENT, "fallback", attempt, ["guard_error"])
        if not violations:
            return GuardedReply(draft, "allowed", attempt)
        categories = [v.category for v in violations]
        correction = correction_instruction(categories)
    return GuardedReply(FALLBACK_STAFF if role == "staff" else FALLBACK_PATIENT, "fallback", limit, categories)
