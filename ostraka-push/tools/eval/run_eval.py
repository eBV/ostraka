#!/usr/bin/env python3
"""Ostraka eval harness: run the frozen question set through the pipeline.

    python3 run_eval.py --pack packs/demo.pack --out results/run1.json [--llm stub|echo]

`llm` backends:
  stub  - deterministic canned answers (validates harness plumbing only)
  echo  - returns the top passage verbatim (retrieval-only baseline)

A real model backend plugs in as llm_fn(system, user) -> str.
Scoring is rubric-based and human; this harness records everything the
scorer needs: question, draft, citations, verified/unverified lists,
timings, and the passages used.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from pipeline import answer, plan
from retriever import Pack


def stub_llm(system, user):
    if "query planner" in system:
        q = user.split("Question:", 1)[-1].strip()
        return json.dumps({"type": "factual", "subqueries": [q]})
    return ("STUB ANSWER. [1] The relevant facts are in the cited passage. "
            "About 42 unverified things happened in 1999.")


def echo_llm(system, user):
    if "query planner" in system:
        q = user.split("Question:", 1)[-1].strip()
        return json.dumps({"type": "factual", "subqueries": [q]})
    # retrieval-only baseline: first passage verbatim
    start = user.index("Passages:") + len("Passages:")
    end = user.index("Question:")
    first = user[start:end].strip().split("\n\n")[0]
    return first + "\n\n[1]"


LLMS = {"stub": stub_llm, "echo": echo_llm}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--llm", default="stub", choices=list(LLMS))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    questions = json.load(open("questions-v1.json"))["questions"]
    if args.limit:
        questions = questions[:args.limit]
    llm_fn = LLMS[args.llm]

    try:
        from rerank import Reranker
        reranker = Reranker()
    except Exception as e:
        print(f"reranker unavailable ({e}); using BM25 order")
        reranker = None

    pack = Pack(args.pack)
    results = []
    t0 = time.time()
    for i, q in enumerate(questions):
        qt0 = time.time()
        try:
            res = answer(q["question"], pack, reranker, llm_fn)
            err = None
        except Exception as e:  # noqa: BLE001 - harness must not die mid-run
            res = {"answer": "", "citations": [], "verified": [],
                   "unverified": [], "type": "error"}
            err = repr(e)
        results.append({
            "id": q["id"],
            "category": q["category"],
            "killer": q["killer"],
            "question": q["question"],
            "reference": q["reference"],
            "answer": res["answer"],
            "citations": res["citations"],
            "verified": res["verified"],
            "unverified": res["unverified"],
            "type": res["type"],
            "seconds": round(time.time() - qt0, 2),
            "error": err,
            # score fields filled by the human/LLM judge afterwards
            "score_correctness": None,   # 0-2
            "score_citations": None,     # 0-2
            "score_completeness": None,  # 0-1
        })
        print(f"[{i+1}/{len(questions)}] {q['id']} "
              f"v={len(res['verified'])} u={len(res['unverified'])} "
              f"{time.time()-qt0:.1f}s", flush=True)
    pack.close()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({
            "pack": args.pack,
            "llm": args.llm,
            "questions": len(results),
            "total_seconds": round(time.time() - t0, 1),
            "results": results,
        }, f, indent=2)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
