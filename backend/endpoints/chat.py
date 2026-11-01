"""Staff and patient chat: auth -> input guard -> budgeted context + Neo4j retrieval -> LLM -> output guard."""

import logging
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from db import get_db_connection
from endpoints.authz import current_user, resolve_patient_id, role_required
from services import budget, llm, memory
from services.context import build_context
from services.graph import retrieval
from services.graph.client import GraphUnavailable
from services.graph.outbox import enqueue
from services.guardrails import check_input, run_guarded

log = logging.getLogger(__name__)

POLICY = """MindBridge is a monitoring and diagnostic-SUPPORT tool, not a clinician.
You MUST NOT: prescribe or recommend any medication; recommend starting, stopping, skipping or changing a medication; suggest doses or amounts; give treatment plans; state a diagnosis as fact; present yourself as a doctor or a replacement for one.
You MAY: summarise what the patient reported (including medications and side effects they mention - restate them without advising on them), describe trends in the data with appropriate uncertainty, point out concerning changes, and suggest speaking with a doctor, pharmacist or other qualified professional.
Only state measurements that appear in the provided context. Data marked [SIMULATED] is synthetic test data; say so when you refer to it."""

STAFF_SYSTEM_PROMPT = f"""You are a clinical and analytical AI assistant for the medical and caretaking staff.
Provide concise, structured summaries of patient history, reported symptoms, medication adherence information, wearable trends (including EWMA-smoothed values) and detected changes, based only on the provided context.
{POLICY}
Keep responses concise, structured and analytical."""

PATIENT_SYSTEM_PROMPT = f"""You are an empathetic wellness coach AI supporting a patient.
Offer supportive conversation, stress-reduction and sleep-hygiene ideas, and help the patient understand their own sleep, activity and heart-rate trends. Maintain an encouraging, supportive tone and reply directly to the conversation.
{POLICY}
Always encourage seeking professional help when appropriate."""

# Share of the prompt budget each part may use (the system prompt takes the remainder).
SHARE_QUERY, SHARE_FACTS, SHARE_HISTORY, SHARE_RETRIEVAL = 0.25, 0.28, 0.15, 0.20


def log_chat(role, patient_id, query, response, handling="direct"):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO chatbot_logs (role, patient_id, query, response, input_handling) "
                    "VALUES (%s,%s,%s,%s,%s) RETURNING id", (role, patient_id, query, response, handling))
        row_id = cur.fetchone()["id"]
        enqueue(cur, "turn", row_id, patient_id)
        conn.commit()
        return row_id
    except Exception:
        conn.rollback()
        log.exception("failed to log chat")
        return None
    finally:
        conn.close()


def record_guardrail(patient_id, role, stage, category, action, attempts=0):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO guardrail_events (patient_id, role, stage, category, action, attempts) "
                    "VALUES (%s,%s,%s,%s,%s,%s)", (patient_id, role, stage, category, action, attempts))
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("failed to record guardrail event")
    finally:
        conn.close()


def _patient_medications(patient_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM medications WHERE patient_id = %s", (patient_id,))
        return [r["name"] for r in cur.fetchall()]
    finally:
        conn.close()


def _summarize(chunk: str) -> str:
    return llm._ollama_chat([{"role": "system", "content": budget.CONDENSE_SYSTEM},
                             {"role": "user", "content": chunk}], 0.1)


def _fit_sections(sections, token_budget):
    """Whole sections by priority; priority-0 sections are always kept."""
    chosen, used = [], 0
    for s in sorted(sections, key=lambda s: s["priority"]):
        cost = budget.estimate_tokens(s["text"])
        if s["priority"] == 0 or used + cost <= token_budget:
            chosen.append(s)
            used += cost
    return chosen


def _run_chat(role, patient_id, query):
    pb = budget.prompt_budget()
    system = STAFF_SYSTEM_PROMPT if role == "staff" else PATIENT_SYSTEM_PROMPT
    meds = _patient_medications(patient_id)

    # 1. independent input validation on the ORIGINAL text
    decision = check_input(query, role, meds)
    if not decision.allowed:
        record_guardrail(patient_id, role, "input", decision.category,
                         "crisis" if decision.action == "crisis" else "refused")
        return jsonify({"response": decision.message,
                        "guardrail": {"action": "crisis" if decision.action == "crisis" else "refused",
                                      "category": decision.category, "stage": "input"},
                        "input_handling": "direct"}), 200

    # 2. long input: condense with fact preservation, never truncate; the original is what gets stored
    handling, message = "direct", query
    query_limit = int(pb * SHARE_QUERY)
    if budget.estimate_tokens(query) > query_limit or len(query) > budget.max_input_chars():
        try:
            message, _ = budget.condense_long_message(query, query_limit, _summarize)
            handling = "condensed"
        except budget.InputTooLong as exc:
            return jsonify({"error": f"{exc}. Please shorten or split your message.", "input_handling": "rejected"}), 413
        except llm.LLMError:
            log.exception("could not condense a long message")
            return jsonify({"error": "Your message is long and the model is unavailable to condense it right now. "
                                     "Nothing was truncated; please try again shortly or send it in parts.",
                            "input_handling": "rejected"}), 503

    # 3. pinned facts (whole sections), history, retrieval - each within its share of the budget
    bundle = build_context(patient_id, role)
    facts = _fit_sections(bundle.sections, int(pb * SHARE_FACTS))
    facts_text = "\n\n".join(s["text"] for s in facts)

    history, history_ids = ([], set())
    if role == "patient":
        history, history_ids = memory.load_history(patient_id, "patient", int(pb * SHARE_HISTORY))

    retrieval_meta, retrieved_text, retrieved = {"status": "skipped", "used": 0}, "", []
    try:
        kinds = retrieval.KINDS_STAFF if role == "staff" else retrieval.KINDS_PATIENT
        items = retrieval.retrieve(patient_id, message, kinds=kinds, k=4)
        recent_cut = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        items = [i for i in items if not (i["kind"] == "window" and (i["created"] or "") >= recent_cut)
                 and not (i["kind"] == "turn" and i["id"] in history_ids)]
        retrieved = retrieval.select_within_budget(items, int(pb * SHARE_RETRIEVAL))
        retrieved_text = "\n".join(i["text"] for i in retrieved)
        retrieval_meta = {"status": "ok", "used": len(retrieved)}
    except GraphUnavailable as exc:
        log.warning("retrieval unavailable: %s", exc)
        retrieval_meta = {"status": "unavailable", "used": 0}

    context = facts_text + (f"\n\nRelevant earlier information:\n{retrieved_text}" if retrieved_text else "")

    # 4. final guard against overflow: shed retrieval, then history, then low-priority facts
    def estimate():
        return (budget.estimate_tokens(system) + budget.estimate_tokens(context) + budget.estimate_tokens(message)
                + sum(budget.estimate_tokens(h["parts"][0]) for h in history) + 300)
    while estimate() > pb and retrieved:
        retrieved.pop()
        retrieved_text = "\n".join(i["text"] for i in retrieved)
        context = facts_text + (f"\n\nRelevant earlier information:\n{retrieved_text}" if retrieved_text else "")
    while estimate() > pb and len(history) >= 2:
        history = history[2:]
    while estimate() > pb and len([s for s in facts if s["priority"] > 0]) > 0:
        facts.remove(max((s for s in facts if s["priority"] > 0), key=lambda s: s["priority"]))
        facts_text = "\n\n".join(s["text"] for s in facts)
        context = facts_text + (f"\n\nRelevant earlier information:\n{retrieved_text}" if retrieved_text else "")

    source_text = "\n".join([context, query] + [h["parts"][0] for h in history])
    usage = {}

    def generate(correction):
        sys_prompt = system if not correction else f"{system}\n\n{correction}"
        if role == "staff":
            result = llm.generate_response_ex(sys_prompt, context, message)
        else:
            result = llm.generate_chat_response_ex(sys_prompt, history, message, context=context)
        usage["prompt_tokens"], usage["done_reason"] = result.prompt_tokens, result.done_reason
        budget.record_usage(len(sys_prompt) + len(context) + len(message), result.prompt_tokens)
        return result.content

    try:
        reply = run_guarded(role, generate, source_text, meds)
    except llm.LLMError:
        log.exception("LLM unavailable")
        return jsonify({"error": "The language model is currently unavailable. Please try again shortly."}), 503

    if reply.action == "fallback":
        record_guardrail(patient_id, role, "output", ",".join(sorted(set(reply.categories)))[:48] or "unknown",
                         "fallback", reply.attempts)
    elif reply.attempts:
        record_guardrail(patient_id, role, "output", "retried_ok", "retried", reply.attempts)

    if reply.action == "allowed":                      # only vetted exchanges become memory / retrievable
        log_chat(role, patient_id, query, reply.text, handling)

    return jsonify({
        "response": reply.text,
        "guardrail": {"action": reply.action, "retries": reply.attempts, "stage": "output"},
        "input_handling": handling,
        "retrieval": retrieval_meta,
        "usage": {"prompt_tokens": usage.get("prompt_tokens"), "prompt_budget": pb,
                  "truncated": usage.get("done_reason") == "length"},
    }), 200


def _query_from_request():
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    query = data.get("query")
    if not isinstance(query, str) or not query.strip():
        return data, None
    return data, query.strip()


@role_required("doctor", "caretaker")
def staff_chat():
    data, query = _query_from_request()
    if query is None:
        return jsonify({"error": "query is required"}), 400
    patient_id, error = resolve_patient_id(data.get("patient_id"))
    if error:
        return error
    return _run_chat("staff", patient_id, query)


@role_required("patient")
def patient_chat():
    _, query = _query_from_request()
    if query is None:
        return jsonify({"error": "query is required"}), 400
    patient_id, _ = current_user()
    return _run_chat("patient", patient_id, query)
