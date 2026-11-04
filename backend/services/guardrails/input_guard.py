"""Independent input validation. Pure functions: no LLM, no database.

Allowed:  reporting a medication, dose, history or side effect ("I take 50 mg of
          sertraline and feel nauseous").
Refused:  asking the AI to recommend / prescribe / dose / start / stop / change a
          medication, asking for a treatment plan, policy override attempts,
          cross-patient requests, unrelated tasks.
Crisis:   self-harm language from a patient gets a fixed supportive response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .policy import HEALTH_TERMS, REFUSALS, crisis_message, has_med_term, normalize, sentences

ACTION = (
    r"stop|quit|skip|start|begin|take|increase|decrease|double|halve|reduce|cut|switch|change|taper|lower|raise|"
    r"add|mix|combine|miss|resume|continue|try|use|drop|swap|replace|adjust|come off|go off|get off|up"
)
_MED_NOUN = (
    r"medications?|medicines?|meds?|drugs?|pills?|tablets?|capsules?|antidepressants?|antipsychotics?|"
    r"sedatives?|painkillers?|supplements?|ssris?|benzos?|sleeping pills?"
)

_REQUEST_PATTERNS = [
    re.compile(rf"\b(?:should|can|could|may|shall|must|ought|do|would|will)\s+i\s+(?:\w+\s+){{0,2}}?(?:{ACTION})\b"),
    re.compile(rf"\b(?:is it|would it be)\s+(?:ok|okay|safe|fine|alright|acceptable|wise|a good idea|better)\s+(?:for me\s+)?to\s+(?:{ACTION})\b"),
    re.compile(r"\b(?:what|which)\s+(?:dose|dosage|strength|amount)\b"),
    re.compile(r"\bhow\s+(?:much|many)\b.{0,30}\b(?:mg|milligrams?|ml|pills?|tablets?|capsules?|doses?|drops?|take)\b"),
    re.compile(r"\bwhat(?:'s| is)?\s+(?:the\s+)?(?:right|correct|best|safe|normal|usual|recommended|maximum|max|minimum|proper|ideal)\s+(?:dose|dosage|amount)\b"),
    re.compile(r"\b(?:prescribe|prescribing)\b|\bwrite\s+(?:me\s+)?a\s+prescription\b"),
    re.compile(rf"\b(?:recommend|suggest|advise|give|offer)\s+(?:me\s+)?(?:a|an|some|any|the)?\s*(?:\w+\s+){{0,2}}(?:{_MED_NOUN})\b"),
    re.compile(rf"\bwhich\s+(?:\w+\s+){{0,2}}(?:{_MED_NOUN})\b.{{0,40}}\b(?:should|best|better|recommend|take|try|work)"),
    re.compile(rf"\bwhat\s+(?:{_MED_NOUN})\b.{{0,30}}\b(?:should|can|could|do you|would you|is best|is better)\b"),
    re.compile(rf"\b(?:tell|help)\s+me\s+(?:to\s+)?(?:what|which|how)\b.{{0,40}}\b(?:take|dose|{_MED_NOUN})\b"),
    re.compile(rf"\b(?:can you|could you|please|i want you to|i need you to|tell me to|let me|you should|allow me to)\b.{{0,30}}\b(?:{ACTION})\b.{{0,25}}\b(?:my|the)\b.{{0,15}}(?:{_MED_NOUN}|dose|dosage|prescription)"),
]

# Asking the AI to prescribe is a request even when no drug is named.
_PRESCRIBE_REQUEST = re.compile(
    r"\b(?:you|please|can|could|would|just|want|need)\b.{0,25}\bprescribe\b|^\W*prescribe\b|\bwrite\s+(?:me\s+)?a\s+prescription\b"
)

_TREATMENT = re.compile(
    r"\b(?:how\s+(?:do|can|should|would)\s+i\s+(?:treat|cure|fix|heal)\b|give\s+me\s+a\s+treatment\s+plan|"
    r"treatment\s+plan\s+for\s+(?:me|my)|what\s+treatment\s+(?:should|do|would)|what\s+therapy\s+should\s+i\s+(?:start|take))"
)

_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|your\s+|the\s+|previous\s+|prior\s+|above\s+)+(?:instructions|rules|guidelines|prompt)|"
    r"\b(?:act|pretend|behave|respond|roleplay|role-play)\s+(?:as|like|to be)\s+(?:a|an|my|the)\s+(?:doctor|psychiatrist|physician|pharmacist|clinician|therapist)|"
    r"\byou\s+are\s+(?:now\s+)?(?:a|my)\s+(?:doctor|psychiatrist|physician|pharmacist)|"
    r"\b(?:reveal|show|print|repeat)\s+(?:me\s+)?(?:your\s+)?(?:system\s+)?(?:prompt|instructions)|"
    r"\bjailbreak\b|\bdeveloper mode\b|\bdan mode\b"
)

_CROSS_PATIENT = re.compile(
    r"\b(?:other|another|different|all|every|any\s+other)\s+(?:patients?|users?|people|persons?)\b|"
    r"\bsomeone\s+else'?s\b|\blist\s+(?:of\s+)?(?:all\s+)?patients\b|\bcompare\s+(?:\w+\s+){0,3}with\s+(?:other|another)\b"
)

_OFF_TOPIC = re.compile(
    r"\b(?:write|debug|fix|generate|create)\s+(?:me\s+)?(?:a\s+|an\s+|some\s+)?(?:\w+\s+){0,2}"
    r"(?:code|script|program|function|python|javascript|java|sql|essay|poem|story|song|email|cover letter|resume|website)\b|"
    r"\b(?:python|javascript|java|c\+\+|html|css|sql|regex)\b.{0,20}\b(?:code|function|script|program|error|bug)\b|"
    r"\b(?:solve|calculate|integrate|differentiate)\b.{0,30}\b(?:equation|integral|derivative|problem|homework)\b|"
    r"\b(?:translate|translation)\b|\b(?:recipe|weather|forecast|stock|stocks|crypto|bitcoin|lottery|horoscope|"
    r"football|cricket|nba|score|movie|movies|lyrics|joke|jokes|riddle|trivia|capital of|president of|"
    r"flight|flights|hotel|visa|tax|taxes|homework|essay|hack|hacking|password|ssn)\b"
)

# Basic arithmetic and calculator prompts are common out-of-domain probes but
# do not contain any of the topic words covered by _OFF_TOPIC.
_MATH_QUESTION = re.compile(
    r"\b(?:what\s+is|calculate|compute|solve)\s+-?\d+(?:\s*(?:\+|-|\*|/|×|÷)\s*-?\d+)+"
    r"(?:\s*=\s*-?\d+)?\s*[?!.]?"
)

_CRISIS = re.compile(
    r"\b(?:kill(?:ing)?\s+myself|suicid\w*|end(?:ing)?\s+(?:my\s+life|it\s+all)|take\s+my\s+(?:own\s+)?life|"
    r"want(?:ed)?\s+to\s+die|wanna\s+die|better\s+off\s+dead|don'?t\s+want\s+to\s+(?:live|be\s+alive|exist)|"
    r"no\s+reason\s+to\s+live|hurt(?:ing)?\s+myself|harm(?:ing)?\s+myself|self[- ]?harm\w*|cut(?:ting)?\s+myself|"
    r"not\s+worth\s+living|overdose\s+on\s+purpose)\b"
)


@dataclass(frozen=True)
class InputDecision:
    action: str            # allow | refuse | crisis
    category: str = "ok"
    message: str | None = None

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


def _medication_request(text: str, extra_drugs) -> bool:
    for sentence in sentences(text):
        if not has_med_term(sentence, extra_drugs):
            continue
        if any(p.search(sentence) for p in _REQUEST_PATTERNS):
            return True
    return False


def check_input(text: str, role: str = "patient", extra_drugs=()) -> InputDecision:
    """Decide whether a user message is in scope. ``extra_drugs``: the patient's own medication names."""
    if not isinstance(text, str) or not text.strip():
        return InputDecision("refuse", "off_topic", REFUSALS["off_topic"])
    lowered = normalize(text).lower()

    if role == "patient" and _CRISIS.search(lowered):
        return InputDecision("crisis", "crisis", crisis_message())
    if _OVERRIDE.search(lowered):
        return InputDecision("refuse", "policy_override", REFUSALS["policy_override"])
    if _CROSS_PATIENT.search(lowered):
        return InputDecision("refuse", "cross_patient", REFUSALS["cross_patient"])
    if _medication_request(lowered, extra_drugs) or _PRESCRIBE_REQUEST.search(lowered):
        return InputDecision("refuse", "medication_request", REFUSALS["medication_request"])
    if _TREATMENT.search(lowered):
        return InputDecision("refuse", "treatment_request", REFUSALS["treatment_request"])
    if (_OFF_TOPIC.search(lowered) or _MATH_QUESTION.search(lowered)) and not HEALTH_TERMS.search(lowered):
        return InputDecision("refuse", "off_topic", REFUSALS["off_topic"])
    return InputDecision("allow")
