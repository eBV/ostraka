#!/usr/bin/env python3
"""Ostraka cross-encoder reranker (reference implementation).

Rescores BM25 candidates with ms-marco-MiniLM-L-6-v2 (ONNX, int8),
the same model the phone runs via ONNX Runtime Mobile.

Usage:
    rerank(query, [(chunk_id, text), ...], top_k=8) -> [(chunk_id, score, text)]
"""

import os

import numpy as np

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                         "models", "ms-marco-minilm-l6-v2")
MODEL_DIR = os.path.normpath(MODEL_DIR)

MAX_LEN = 256


class Reranker:
    def __init__(self, model_dir=MODEL_DIR):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        onnx_path = os.path.join(model_dir, "model_quantized.onnx")
        tok_path = os.path.join(model_dir, "tokenizer.json")
        if not (os.path.exists(onnx_path) and os.path.exists(tok_path)):
            raise FileNotFoundError(
                f"reranker assets missing in {model_dir}")
        self.tok = Tokenizer.from_file(tok_path)
        self.tok.enable_truncation(max_length=MAX_LEN)
        self.tok.enable_padding(length=MAX_LEN)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(onnx_path, sess_options=opts,
                                         providers=["CPUExecutionProvider"])
        self.in_names = [i.name for i in self.sess.get_inputs()]

    def scores(self, query, texts):
        enc = self.tok.encode_batch([(query, t) for t in texts])
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {}
        for n in self.in_names:
            nl = n.lower()
            if "input_ids" in nl:
                feed[n] = ids
            elif "attention_mask" in nl:
                feed[n] = mask
            elif "token_type_ids" in nl:
                feed[n] = np.zeros_like(ids)
        logits = self.sess.run(None, feed)[0]
        return logits.reshape(-1).tolist()

    def rerank(self, query, candidates, top_k=8):
        """candidates: [(chunk_id, text), ...] -> top_k [(chunk_id, score, text)]."""
        if not candidates:
            return []
        sc = self.scores(query, [t for _, t in candidates])
        ranked = sorted(zip(candidates, sc),
                        key=lambda x: x[1], reverse=True)[:top_k]
        return [(cid, float(s), text) for (cid, text), s in ranked]


def self_test():
    r = Reranker()
    query = "Who carved the moai statues on Easter Island?"
    cands = [
        (0, "Moai\nThe moai are monolithic human figures carved by the Rapa "
            "Nui people on Easter Island between 1250 and 1500."),
        (1, "Moai — History\nNearly half of the moai remain at Rano Raraku, "
            "the main quarry where they were carved."),
        (2, "Penguin\nPenguins are flightless birds living in the Southern "
            "Hemisphere. They eat fish and krill."),
    ]
    out = r.rerank(query, cands, top_k=2)
    assert len(out) == 2, out
    ids = [c for c, _, _ in out]
    assert 2 not in ids, f"penguin chunk ranked in top 2: {out}"
    assert out[0][1] >= out[1][1], "not sorted"
    print(f"RERANK SELF TEST PASSED "
          f"(scores: {[round(s, 3) for _, s, _ in out]})")


if __name__ == "__main__":
    self_test()
