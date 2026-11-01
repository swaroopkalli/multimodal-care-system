"""Independent output validation. Pure functions: no LLM, no database.

A draft is checked sentence by sentence. Medication or dose mentions are fine
when they merely restate what the patient/context said; they fail when they
direct the reader to act, introduce a dose or drug that was never reported, form
a treatment plan, assert a diagnosis as fact, or replace a clinician.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .policy import has_med_term, named_drugs_in, normalize, sentences

_VERBS = (
    r"start|stop|begin|discontinue|quit|skip|increase|decrease|reduce|double|halve|taper|switch|change|adjust|"
    r"raise|lower|take|add|cut|resume|swap|replace|combine|mix|come off|go off|stop taking|keep taking"
)
_DIRECTIVE = re.compile(
    rf"\byou\s+(?:should|must|need\s+to|ought\s+to|have\s+to|had\s+better|can|could|may|might\s+want\s+to|might\s+consider|will\s+want\s+to)\s+(?:\w+\s+){{0,2}}?(?:{_VERBS})\b"
    rf"|\bi\s+(?:would\s+|'d\s+|strongly\s+|highly\s+)*(?:recommend|suggest|advise|urge|propose)\b"
    rf"|^\W*(?:please\s+|just\s+|also\s+|then\s+|now\s+|never\s+|do\s+not\s+|don'?t\s+)?(?:{_VERBS})\b"
    rf"|\b(?:consider|try|let's|let us)\s+(?:\w+\s+){{0,2}}?(?:{_VERBS})(?:ing)?\b"
    rf"|\b(?:it'?s|it\s+is)\s+(?:best|better|advisable|recommended|wise)\s+(?:to|that\s+you)\s+(?:\w+\s+){{0,2}}?(?:{_VERBS})\b"
)

_CLIN = (r"(?:doctor|prescriber|psychiatrist|pharmacist|clinician|physician|healthcare\s+(?:professional|provider)|"
         r"health\s+care\s+(?:professional|provider)|therapist|gp|medical\s+professional|care\s+team|nurse)")
_REFERRAL = re.compile(
    rf"\b(?:talk|speak|discuss|check|consult|ask|tell|contact|see|call|raise|mention|bring\s+(?:it|this)\s+up|let|inform|reach\s+out)\b.{{0,60}}\b{_CLIN}\b"
    rf"|\b{_CLIN}\b.{{0,40}}\b(?:can|will|is\s+best|should|would)\b.{{0,30}}\b(?:advise|decide|help|review|assess|adjust|determine|evaluate|guide)\b"
)
_ADHERENCE = re.compile(r"\bas\s+(?:prescribed|directed|instructed)\b|\bprescribed\s+by\b")
_CHANGING = re.compile(r"\b(?:stop|discontinue|quit|skip|increase|decrease|reduce|double|halve|taper|switch|change|adjust|raise|lower|begin|start|add|cut|swap|replace)\b")

_DOSE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:mg|mcg|µg|ug|ml|milligrams?|micrograms?|iu|units?)\b"
    r"|\b(?:\d+|two|three|four|five|half|double|twice)\s+(?:pills?|tablets?|capsules?|drops?)\b"
)

_TREATMENT_PLAN = re.compile(
    r"\b(?:here(?:'s| is)|this is|i(?:'ll| will)?\s+(?:suggest|propose|recommend))\s+(?:a\s+|your\s+|the\s+)?(?:treatment|therapy|medication|dosing)\s+(?:plan|regimen|schedule|protocol)\b"
    r"|\byour\s+(?:treatment|medication|dosing)\s+(?:plan|regimen|schedule)\s+(?:is|should|will|would)\b"
    r"|\bi\s+(?:prescribe|am\s+prescribing|will\s+prescribe|'m\s+prescribing)\b"
)

_DX = (r"(?:depress\w+|bipolar\w*|anxiety\s+disorder|generalized\s+anxiety|panic\s+disorder|ptsd|post-traumatic\w*|"
       r"schizophren\w*|adhd|ocd|obsessive\w*|psychosis|psychotic|borderline\s+personality|eating\s+disorder|"
       r"major\s+depressive|mdd|\w+\s+disorder|mental\s+illness)")
_DEFINITIVE = [
    re.compile(rf"\byou\s+(?:have|has|are\s+suffering\s+from|suffer\s+from|are\s+diagnosed\s+with|'?ve\s+got|are\s+living\s+with)\s+(?:\w+\s+){{0,3}}?{_DX}\b"),
    re.compile(r"\byou\s+(?:are|'re)\s+(?:clinically\s+|definitely\s+|certainly\s+|likely\s+)?(?:depressed|bipolar|schizophrenic|psychotic|mentally\s+ill)\b"),
    re.compile(r"\b(?:i|we)\s+(?:diagnose|am\s+diagnosing|can\s+confirm)\b"),
    re.compile(rf"\b(?:this|that|it)\s+(?:is|confirms|means\s+you\s+have|indicates\s+you\s+have)\s+(?:clinical\s+|major\s+)?{_DX}\b"),
    re.compile(r"\bthe\s+diagnosis\s+(?:is|:)"),
]
_HEDGE = re.compile(
    r"\b(?:may|might|could|possibly|perhaps|potentially|consistent\s+with|suggest(?:s|ing)?|sign\s+of|signs\s+of|"
    r"appears?|seems?|if\s+you|whether|ask\s+your|reported|mention(?:ed)?|you\s+said|you\s+told|"
    r"can'?t\s+diagnose|cannot\s+diagnose|unable\s+to\s+diagnose|not\s+a\s+diagnosis|not\s+able\s+to\s+diagnose|"
    r"clinician\s+can|doctor\s+can|professional\s+can)\b"
)

_REPLACE = [
    re.compile(r"\bas\s+your\s+(?:doctor|psychiatrist|therapist|physician)\b"),
    re.compile(r"\bi\s*(?:am|'m)\s+(?:a\s+|your\s+)?(?:doctor|psychiatrist|therapist|physician|licensed|clinician|medical\s+professional)\b"),
    re.compile(r"\byou\s+(?:don'?t|do\s+not)\s+need\s+(?:a|to\s+see\s+a|to\s+consult|your)\s+(?:doctor|therapist|professional|clinician|psychiatrist)\b"),
    re.compile(r"\bno\s+need\s+(?:to|for)\s+(?:see|consult|visit|talk\s+to|a)\s+(?:a\s+|your\s+)?(?:doctor|therapist|professional|clinician|psychiatrist)\b"),
    re.compile(r"\binstead\s+of\s+(?:seeing|consulting|visiting)\s+(?:a|your)\s+(?:doctor|therapist|professional|clinician|psychiatrist)\b"),
    re.compile(r"\b(?:i|this\s+app)\s+can\s+replace\s+(?:your|a)\s+(?:doctor|therapist|clinician)\b"),
]

_MEASURE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(bpm|beats\s+per\s+minute|steps)\b")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class Violation:
    category: str
    sentence: str


def _norm_dose(token: str) -> str:
    return re.sub(r"\s+", "", token.lower().replace(",", "."))


def _numbers(text: str) -> list[float]:
    out = []
    for n in _NUMBER.findall(text):
        try:
            out.append(float(n.replace(",", "")))
        except ValueError:
            pass
    return out


def check_output(text: str, role: str = "patient", source_text: str = "", extra_drugs=()) -> list[Violation]:
    """Return violations (empty list = safe). ``source_text`` = everything the model was legitimately given."""
    violations: list[Violation] = []
    norm = normalize(text or "")
    if not norm:
        return [Violation("empty", "")]
    source = normalize(source_text or "").lower()
    source_doses = {_norm_dose(m.group(0)) for m in _DOSE.finditer(source)}
    source_drugs = named_drugs_in(source, extra_drugs)
    source_numbers = _numbers(source)

    for raw in sentences(norm):
        s = raw.lower()
        referral = bool(_REFERRAL.search(s))
        doses = [m.group(0) for m in _DOSE.finditer(s)]
        meds = has_med_term(s, extra_drugs) or bool(doses)

        # 1. directing the reader to start/stop/change/take medication
        if meds and _DIRECTIVE.search(s) and not referral:
            adherence_only = _ADHERENCE.search(s) and not _CHANGING.search(s)
            if not adherence_only:
                violations.append(Violation("directive_medication", raw))

        # 2. doses that the patient/context never supplied
        for token in doses:
            if _norm_dose(token) not in source_doses and not referral:
                violations.append(Violation("dosage", raw))
                break

        # 3. naming a drug the patient never mentioned (a de-facto suggestion)
        if not referral:
            new = named_drugs_in(s, extra_drugs) - source_drugs
            if new:
                violations.append(Violation("medication_suggestion", raw))

        # 4. prescribing / treatment plan
        if _TREATMENT_PLAN.search(s):
            violations.append(Violation("treatment_plan", raw))

        # 5. definitive diagnosis (hedged, attributed wording is allowed)
        if any(p.search(s) for p in _DEFINITIVE) and not _HEDGE.search(s):
            violations.append(Violation("definitive_diagnosis", raw))

        # 6. presenting as / replacing a clinician
        if any(p.search(s) for p in _REPLACE):
            violations.append(Violation("clinician_replacement", raw))

        # 7. staff summaries: measurements must come from the supplied context
        if role == "staff":
            for m in _MEASURE.finditer(s):
                try:
                    value = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if not any(abs(value - n) <= 1.0 for n in source_numbers):
                    violations.append(Violation("unsupported_claim", raw))
                    break

    seen, unique = set(), []
    for v in violations:
        key = (v.category, v.sentence)
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique
