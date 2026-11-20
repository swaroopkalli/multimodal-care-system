"""Dataset loader and schema for MindBridge LLM evaluation benchmarks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvalCase:
    """A single evaluation benchmark case."""
    id: str
    query: str
    role: str = "patient"                         # "patient" or "staff"
    context: str = ""                             # Context bundle / clinical history
    tags: list[str] = field(default_factory=list) # e.g. ["crisis"], ["boundary"], ["grounding"], ["distress"]
    expected_action: str = "allow"                # "allow", "crisis", "refuse"
    expected_category: str | None = None
    extra_drugs: list[str] = field(default_factory=list)
    ground_truth_numbers: list[float] = field(default_factory=list)
    max_sentences: int = 3
    max_tokens: int = 120

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCase:
        return cls(
            id=str(data.get("id", "")),
            query=str(data.get("query", "")),
            role=str(data.get("role", "patient")),
            context=str(data.get("context", "")),
            tags=list(data.get("tags", [])),
            expected_action=str(data.get("expected_action", "allow")),
            expected_category=data.get("expected_category"),
            extra_drugs=list(data.get("extra_drugs", [])),
            ground_truth_numbers=[float(x) for x in data.get("ground_truth_numbers", [])],
            max_sentences=int(data.get("max_sentences", 3)),
            max_tokens=int(data.get("max_tokens", 120)),
        )


def load_fixtures(file_path: str | Path) -> list[EvalCase]:
    """Load benchmark cases from a JSONL file."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Fixture file not found: {path}")

    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                data = json.loads(line)
                cases.append(EvalCase.from_dict(data))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON on line {line_no} of {path}: {exc}") from exc

    return cases
