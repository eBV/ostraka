#!/usr/bin/env python3
"""Ostraka answer pipeline (reference implementation).

Orchestrates: rewrite -> retrieve -> rerank -> synthesize -> verify.
The Kotlin app mirrors these stages; `llm_fn` is injectable so the eval
harness can plug in any model backend.

    llm_fn(system_prompt, user_prompt) -> str
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from prompts import REWRITE_SYSTEM, SYNTHESIZE_SYSTEM, SYNTHESIZE_USER
from retriever import Pack
from verify import verify, mark_answer


def plan(question, llm_fn):
    """Classify + emit search sub-queries. Falls back to [question]."""
    try:
        raw = llm_fn(REWRITE_SYSTEM, question)
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        subs = [s for s in data.get("subqueries", []) if s.strip()][:3]
        if subs:
            return data.get("type", "factual"), subs
    except Exception:
        pass
    return "factual", [question]


def answer(question, pack, reranker, llm_fn, k_bm25=40, k_rerank=8):
    qtype, subqueries = plan(question, llm_fn)

    # Retrieve per sub-query, merge, de-dupe.
    seen, cands = set(), []
    for sq in subqueries:
        for cid, _s, text in pack.title_boost_search(sq, k=k_bm25):
            if cid not in seen:
                seen.add(cid)
                cands.append((cid, text))

    # Rerank to the top passages.
    top = reranker.rerank(question, cands, top_k=k_rerank) if reranker else [
        (cid, 0.0, text) for cid, text in cands[:k_rerank]]

    if not top:
        from prompts import EMPTY_ANSWER
        return {"answer": EMPTY_ANSWER, "citations": [], "verified": [],
                "unverified": [], "type": qtype}

    passages = "\n\n".join(f"[{i+1}] {text}"
                           for i, (_, _, text) in enumerate(top))
    draft = llm_fn(SYNTHESIZE_SYSTEM,
                   SYNTHESIZE_USER.format(passages=passages,
                                          question=question))

    cited_texts = [text for _, _, text in top]
    verified, unverified = verify(draft, cited_texts)
    return {
        "answer": mark_answer(draft, unverified),
        "citations": [f"[{i+1}]" for i in range(len(top))],
        "verified": verified,
        "unverified": unverified,
        "type": qtype,
    }


def self_test():
    import tempfile
    import argparse
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "corpus"))
    import build_pack
    from build_pack import build, SELF_TEST_XML

    d = tempfile.mkdtemp(prefix="pipetest")
    xml = os.path.join(d, "t.xml")
    open(xml, "w").write(SELF_TEST_XML)
    pack_dir = os.path.join(d, "t.pack")
    build_pack.MIN_PROSE_CHARS = 50
    assert build(argparse.Namespace(
        input=xml, pack_name="t", out=pack_dir, max_articles=0)) == 0

    from rerank import Reranker
    try:
        reranker = Reranker()
    except FileNotFoundError:
        reranker = None

    def stub_llm(system, user):
        if "query planner" in system:
            return '{"type": "factual", "subqueries": ["moai Easter Island carved"]}'
        # synthesis stub: one true claim, one invented claim
        return ("The moai [1] were carved by the Rapa Nui between 1250 and "
                "1500. About 42 statues were painted purple by Vikings.")

    pack = Pack(pack_dir)
    res = answer("Who carved the moai?", pack, reranker, stub_llm)
    assert "Rapa Nui" in res["verified"], res
    assert res["unverified"], "invented claims must be flagged"
    assert "⚠" in res["answer"], res["answer"][-120:]
    assert "Vikings" in res["answer"]  # flagged, not removed
    pack.close()
    print("PIPELINE SELF TEST PASSED")


if __name__ == "__main__":
    self_test()
