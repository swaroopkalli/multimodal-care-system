"""8. Context-window handling and long-input behaviour."""

from unittest.mock import patch

from .framework import MARK, check, world


@check("8. Context window / long input")
def budget_is_80_percent_of_the_context_with_a_response_reserve():
    from services.llm import context_settings
    import os
    with patch.dict(os.environ, {"NVIDIA_NUM_CTX": "8192", "NVIDIA_PROMPT_BUDGET_RATIO": "0.8", "NVIDIA_MAX_TOKENS": ""}):
        s = context_settings()
    assert s["prompt_budget"] == 6553 and s["response_reserve"] == 1639 and s["num_predict"] == 1639, s


@check("8. Context window / long input")
def nvidia_request_respects_the_configured_response_reserve():
    import json
    from services import llm
    captured = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 1},
            }).encode()

    def fake(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return Resp()
    with patch("services.llm.urlopen", fake):
        out = llm.chat_ex([{"role": "user", "content": "hi"}], 0.2)
    assert captured["body"]["max_tokens"] == llm.context_settings()["num_predict"]
    assert out.prompt_tokens == 12 and out.truncated is False


@check("8. Context window / long input")
def long_text_is_chunked_without_losing_any_content():
    from services.budget import estimate_tokens, split_into_chunks
    text = ("I have felt low and exhausted. " * 60 + "I take sertraline 50mg daily.\n\n") * 8
    chunks = split_into_chunks(text, 300)
    assert len(chunks) > 3 and all(estimate_tokens(c) <= 300 for c in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(text.split()), "chunking must not drop or alter text"
    assert split_into_chunks("x" * 5000, 200), "an unbroken run must still be split"


@check("8. Context window / long input")
def condensing_preserves_medication_facts_and_never_truncates_silently():
    from services.budget import InputTooLong, condense_long_message, estimate_tokens
    text = ("I have been feeling very low. " * 120) + " I take sertraline 50mg daily and feel nauseous."
    out, passes = condense_long_message(text, 500, lambda chunk: "I feel low and nauseous.")
    assert estimate_tokens(out) <= 500 + 40 and passes >= 1
    assert "sertraline" in out and "50mg" in out, "drug and dose must survive condensing"
    try:
        condense_long_message(text, 5, lambda chunk: chunk)
    except InputTooLong:
        pass
    else:
        raise AssertionError("an impossible budget must raise InputTooLong, not truncate")
    try:
        condense_long_message("x " * 30000, 500, lambda c: c)
    except InputTooLong:
        pass
    else:
        raise AssertionError("over-limit input must be rejected")


@check("8. Context window / long input")
def lru_cache_evicts_least_recently_used_and_supports_per_patient_invalidation():
    from services.budget import LRUCache
    c = LRUCache(maxsize=2)
    c.put((1, "a"), "A"); c.put((2, "a"), "B"); c.get((1, "a")); c.put((3, "a"), "C")
    assert c.get((2, "a")) is None and c.get((1, "a")) == "A" and c.get((3, "a")) == "C"
    c.invalidate_prefix(1)
    assert c.get((1, "a")) is None and c.get((3, "a")) == "C", "invalidation is scoped to one patient"
    import time
    t = LRUCache(maxsize=4, ttl=0.05); t.put("k", 1); time.sleep(0.08)
    assert t.get("k") is None, "TTL expiry"


@check("8. Context window / long input", needs=("postgres",))
def history_keeps_the_newest_turns_that_fit_the_budget():
    from db import get_db_connection
    from services import memory
    from services.budget import estimate_tokens
    with world() as (w, _):
        conn = get_db_connection(); cur = conn.cursor()
        for i in range(12):
            cur.execute("INSERT INTO chatbot_logs (role, patient_id, query, response) VALUES ('patient',%s,%s,%s)",
                        (w.patient_a, f"question {i}", f"answer {i}"))
        conn.commit(); conn.close()
        history, ids = memory.load_history(w.patient_a, "patient", 10_000)
        assert [h["parts"][0] for h in history][-2:] == ["question 11", "answer 11"], "newest turn must be last"
        assert len(history) == 24, "everything fits a large budget"
        small, _ = memory.load_history(w.patient_a, "patient", 2 * (estimate_tokens("question 11") + estimate_tokens("answer 11")) + 1)
        assert [h["parts"][0] for h in small] == ["question 10", "answer 10", "question 11", "answer 11"], \
            "a small budget keeps the NEWEST turns (old code kept the oldest 5)"


def _capture_llm(captured):
    from services.llm import LLMResult

    def fake_resp(system, context, query, temperature=0.4):
        captured.append(("staff", system, context, query))
        return LLMResult("Here is a neutral summary of the patient's records.", 100, 20, "stop")

    def fake_chat(system, history, query, context=None, temperature=0.6):
        captured.append(("patient", system, context or "", query))
        return LLMResult("It sounds like a hard week; speaking with your doctor may help.", 100, 20, "stop")
    return patch("services.llm.generate_response_ex", fake_resp), patch("services.llm.generate_chat_response_ex", fake_chat)


@check("8. Context window / long input", needs=("postgres",))
def prompt_never_exceeds_the_budget_even_with_huge_context_and_long_messages():
    from services.budget import estimate_tokens, prompt_budget
    captured = []
    p1, p2 = _capture_llm(captured)
    with world() as (w, client):
        for i in range(5):                                           # large pinned doctor notes
            r = client.post("/api/doctor_notes", json={"patient_id": w.patient_a, "note": f"note {i} " + "history detail " * 500},
                            headers={"Authorization": f"Bearer {w.tokens['doctor']}"})
            assert r.status_code == 201
        long_msg = ("I have been struggling with sleep and my mood. " * 400)          # ~18k chars, over the query share
        with p1, p2, patch("endpoints.chat._summarize", lambda chunk: "I struggle with sleep and low mood."):
            r = client.post("/api/staff/chat", json={"patient_id": w.patient_a, "query": "Summarise this patient."},
                            headers={"Authorization": f"Bearer {w.tokens['doctor']}"})
            assert r.status_code == 200, r.get_json()
            r2 = client.post("/api/patient/chat", json={"query": long_msg}, headers={"Authorization": f"Bearer {w.tokens['patient_a']}"})
            assert r2.status_code == 200, r2.get_json()
            assert r2.get_json()["input_handling"] == "condensed"
    for _, system, context, query in captured:
        total = estimate_tokens(system) + estimate_tokens(context) + estimate_tokens(query)
        assert total <= prompt_budget(), f"prompt of ~{total} tokens exceeds the {prompt_budget()} budget"


@check("8. Context window / long input", needs=("postgres",))
def long_messages_keep_the_original_text_and_oversized_ones_are_rejected_transparently():
    from db import get_db_connection
    captured = []
    p1, p2 = _capture_llm(captured)
    with world() as (w, client):
        tok = {"Authorization": f"Bearer {w.tokens['patient_a']}"}
        long_msg = ("My sleep has been poor and I feel stressed. " * 300) + "I take sertraline 50mg."
        with p1, p2, patch("endpoints.chat._summarize", lambda chunk: "I sleep poorly and feel stressed."):
            r = client.post("/api/patient/chat", json={"query": long_msg}, headers=tok)
        assert r.status_code == 200 and r.get_json()["input_handling"] == "condensed"
        sent = captured[-1][3]
        assert len(sent) < len(long_msg) and "sertraline" in sent and "50mg" in sent, "condensed text keeps drug and dose"
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT query, input_handling FROM chatbot_logs WHERE patient_id=%s", (w.patient_a,))
        row = cur.fetchone(); conn.close()
        assert row["query"] == long_msg and row["input_handling"] == "condensed", "the ORIGINAL must be preserved"
        too_big = client.post("/api/patient/chat", json={"query": "x " * 30000}, headers=tok)
        assert too_big.status_code == 413 and too_big.get_json()["input_handling"] == "rejected"


@check("8. Context window / long input", needs=("postgres",))
def failed_condensing_returns_a_clear_error_instead_of_truncating():
    from services.llm import LLMError
    captured = []
    p1, p2 = _capture_llm(captured)
    with world() as (w, client):
        def boom(chunk):
            raise LLMError("model down")
        with p1, p2, patch("endpoints.chat._summarize", boom):
            r = client.post("/api/patient/chat", json={"query": "I feel low. " * 1500},
                            headers={"Authorization": f"Bearer {w.tokens['patient_a']}"})
        assert r.status_code == 503 and not captured, "must not call the model with a truncated message"
