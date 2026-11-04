"""Shared lexicons, refusal wording and policy constants for the guardrails.

Policy in one paragraph: MindBridge is diagnostic *support* only. Patients may
freely REPORT medications, doses and side effects. The AI must never recommend
starting, stopping, changing or dosing a medication, never prescribe or give a
treatment plan, never state a diagnosis as fact, and never present itself as a
replacement for a clinician.
"""

from __future__ import annotations

import os
import re

NAMED_DRUGS = {
    # antidepressants / mood
    "sertraline", "fluoxetine", "escitalopram", "citalopram", "paroxetine", "venlafaxine", "duloxetine",
    "bupropion", "mirtazapine", "trazodone", "amitriptyline", "nortriptyline", "lithium", "lamotrigine",
    "valproate", "valproic", "carbamazepine", "vortioxetine", "fluvoxamine", "clomipramine",
    # antipsychotics
    "quetiapine", "olanzapine", "risperidone", "aripiprazole", "clozapine", "haloperidol", "lurasidone",
    # anxiolytic / sleep
    "alprazolam", "lorazepam", "clonazepam", "diazepam", "zolpidem", "buspirone", "hydroxyzine",
    "propranolol", "melatonin", "temazepam", "zopiclone",
    # stimulants / ADHD
    "methylphenidate", "atomoxetine", "lisdexamfetamine", "amphetamine",
    # common OTC
    "ibuprofen", "paracetamol", "acetaminophen", "aspirin", "naproxen", "diphenhydramine",
    # brands
    "zoloft", "prozac", "lexapro", "celexa", "paxil", "effexor", "cymbalta", "wellbutrin", "remeron",
    "seroquel", "zyprexa", "risperdal", "abilify", "xanax", "ativan", "klonopin", "valium", "ambien",
    "adderall", "ritalin", "concerta", "lamictal", "tylenol", "advil", "benadryl",
}

GENERIC_MED_WORDS = (
    r"medications?|medicines?|meds?|pills?|tablets?|capsules?|doses?|dosages?|drugs?|prescriptions?|"
    r"antidepressants?|antipsychotics?|anxiolytics?|mood stabili[sz]ers?|sleeping pills?|sedatives?|"
    r"painkillers?|supplements?|ssris?|snris?|benzos?|benzodiazepines?|stimulants?|mg|milligrams?"
)

_MED_RE = re.compile(
    r"\b(?:" + GENERIC_MED_WORDS + "|" + "|".join(sorted(NAMED_DRUGS)) + r")\b", re.I
)

HEALTH_TERMS = re.compile(
    r"\b(sleep\w*|insomnia|tired|fatigue\w*|stress\w*|anxi\w+|worr\w+|panic\w*|mood|depress\w*|sad|low|"
    r"feel\w*|emotion\w*|mental|therap\w+|counsel\w+|symptom\w*|side effects?|nause\w*|dizz\w*|headache\w*|"
    r"appetite|energy|restless\w*|heart\s?rate|bpm|pulse|steps|activity|exercise|wellness|wellbeing|well-being|"
    r"health\w*|doctor|caretaker|patient|clinic\w*|medic\w+|dose|pill\w*|tablet\w*|prescri\w+|diagnos\w+|"
    r"journal\w*|check-?in|trend\w*|anomal\w+|wearable\w*|vitals?|summar\w+|notes?|screen\s?time|calm\w*|"
    r"relax\w*|breath\w*|cope|coping|lonely|angry|overwhelm\w*|motivat\w*|burn\w*out|nightmare\w*|hopeless\w*)\b",
    re.I,
)


def has_med_term(text: str, extra_drugs=()) -> bool:
    if _MED_RE.search(text):
        return True
    return any(d and re.search(rf"\b{re.escape(d.lower())}\b", text.lower()) for d in extra_drugs)


def named_drugs_in(text: str, extra_drugs=()) -> set[str]:
    found = {m.group(0).lower() for m in re.finditer(r"\b(?:" + "|".join(sorted(NAMED_DRUGS)) + r")\b", text, re.I)}
    lowered = text.lower()
    found |= {d.lower() for d in extra_drugs if d and re.search(rf"\b{re.escape(d.lower())}\b", lowered)}
    return found


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[​‌‍﻿]", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+|;\s+", text)
    return [p.strip() for p in parts if p and p.strip()]


MAX_RETRIES_DEFAULT = 1
MAX_RETRIES_CAP = 2


def max_retries() -> int:
    try:
        value = int(os.getenv("GUARD_MAX_RETRIES", str(MAX_RETRIES_DEFAULT)))
    except ValueError:
        value = MAX_RETRIES_DEFAULT
    return max(0, min(value, MAX_RETRIES_CAP))


CRISIS_MESSAGE_DEFAULT = (
    "I'm really sorry you're going through this, and I'm glad you told me. You don't have to face it alone. "
    "If you might act on these thoughts or you are in immediate danger, please contact your local emergency "
    "services or a crisis line right now, or reach out to someone you trust and stay with them. "
    "Please also let your doctor or caretaker know how you're feeling today."
)


def crisis_message() -> str:
    return os.getenv("GUARD_CRISIS_MESSAGE", "").strip() or CRISIS_MESSAGE_DEFAULT


REFUSALS = {
    "medication_request": (
        "I can't recommend, prescribe or adjust medication or doses, and I can't advise on starting, stopping or "
        "changing it. Your doctor or pharmacist is the right person for that. I'm happy to note anything you've "
        "experienced (including side effects) so you can raise it with them."
    ),
    "treatment_request": (
        "I can't provide a treatment plan or tell you how to treat a condition. A qualified clinician can do that. "
        "I can help you track how you're feeling and prepare notes for your next appointment."
    ),
    "off_topic": (
        "I'm here for mental-health monitoring and wellbeing support, so I can't help with that request. "
        "You can ask me about your mood, sleep, stress, symptoms, side effects or your wearable trends."
    ),
    "policy_override": (
        "I can't change how I work or act as a doctor. I can support monitoring, explain trends in your data, "
        "and help you prepare for talking with your care team."
    ),
    "cross_patient": (
        "I can only discuss the patient you are currently working with. I can't share or compare information "
        "about other people."
    ),
}

FALLBACK_PATIENT = (
    "I wasn't able to put together a response that meets MindBridge's safety rules. I can summarise what you've "
    "told me, describe your sleep and activity trends, or help you prepare questions for your doctor. "
    "For anything about medications, doses or treatment, please speak with your doctor or pharmacist."
)
FALLBACK_STAFF = (
    "The generated summary was withheld because it did not pass MindBridge's safety checks (no medication, "
    "dosage or treatment recommendations and no definitive diagnoses are allowed). Please rephrase the request "
    "or review the patient's records directly."
)

CORRECTION_TEXT = {
    "directive_medication": "it told the user to start, stop, change or take a medication",
    "dosage": "it contained a dose or amount that the patient did not report",
    "medication_suggestion": "it named a medication the patient never mentioned",
    "treatment_plan": "it gave or implied a prescription or treatment plan",
    "definitive_diagnosis": "it stated a diagnosis as fact",
    "clinician_replacement": "it presented itself as, or as a replacement for, a clinician",
    "unsupported_claim": "it stated measurements that are not in the provided context",
    "context_wrapper_leak": "it exposed internal context boundary markup",
}
