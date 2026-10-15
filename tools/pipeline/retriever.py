#!/usr/bin/env python3
"""Ostraka retriever: BM25 over a pack's FTS5 index, with snippet fetch.

The phone runs the same logic in Kotlin/SQLite; this module is the reference
implementation used by the eval harness and tested here.
"""

import re
import sqlite3
import zstandard as zstd

_dctx = zstd.ZstdDecompressor()

# FTS5 query sanitation: keep alphanumerics, drop operators the user typed.
_TOKEN_RE = re.compile(r"[^\w\s]", re.UNICODE)
_STOPWORDS = {
    "who", "what", "when", "where", "why", "how", "which", "whom", "whose",
    "is", "are", "was", "were", "be", "been", "do", "does", "did", "the",
    "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "by",
    "with", "from", "as", "it", "its", "this", "that",
}


def sanitize_query(q, max_terms=12):
    """Return an FTS5 OR-query over the content terms.

    OR (not AND): a question's words rarely all appear in one chunk; BM25
    ranking plus the title boost sorts the wheat out.
    """
    toks = [t for t in _TOKEN_RE.sub(" ", q).lower().split()
            if len(t) > 1 and t not in _STOPWORDS]
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= max_terms:
            break
    return " OR ".join(out)


class Pack:
    def __init__(self, pack_dir):
        idx_path = f"{pack_dir}/index.db"
        chunks_path = f"{pack_dir}/chunks.db"
        self.idx = sqlite3.connect(idx_path)
        self.idx.row_factory = sqlite3.Row
        self.chunks = sqlite3.connect(chunks_path)
        self.chunks.row_factory = sqlite3.Row
        # Fail loudly on missing/empty packs instead of querying ghosts.
        tables = {r[0] for r in self.idx.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        if "idx" not in tables:
            raise FileNotFoundError(f"no FTS5 index in {idx_path}")

    def search(self, query, k=40):
        """Return [(chunk_id, bm25_score, text)] best-first (lower is better)."""
        q = sanitize_query(query)
        if not q:
            return []
        rows = self.idx.execute(
            "SELECT chunk_id, bm25(idx) AS s FROM idx "
            "WHERE idx MATCH ? ORDER BY s LIMIT ?",
            (q, k)).fetchall()
        if not rows:
            return []
        ids = [r["chunk_id"] for r in rows]
        texts = {
            r["chunk_id"]: _dctx.decompress(r["text_zstd"]).decode("utf-8")
            for r in self.chunks.execute(
                f"SELECT chunk_id, text_zstd FROM chunks WHERE chunk_id IN "
                f"({','.join('?' * len(ids))})", ids)
        }
        scored = [(r["chunk_id"], r["s"], texts.get(r["chunk_id"], ""))
                  for r in rows]
        return [s for s in scored if s[2]]

    def title_boost_search(self, query, k=40):
        """BM25, then boost chunks whose article title matches query terms."""
        hits = self.search(query, k=k * 2)
        qterms = {t for t in sanitize_query(query).lower().split()
                  if t != "or"}
        boosted = []
        for cid, s, text in hits:
            title = text.split("\n", 1)[0].lower()
            overlap = len(qterms & set(re.findall(r"\w+", title)))
            boosted.append((cid, s - 2.0 * overlap, text))
        boosted.sort(key=lambda x: x[1])
        return boosted[:k]

    def close(self):
        self.idx.close()
        self.chunks.close()


def self_test():
    import os
    import tempfile
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "corpus"))
    from build_pack import build, SELF_TEST_XML
    import argparse

    d = tempfile.mkdtemp(prefix="retvtest")
    xml = os.path.join(d, "t.xml")
    open(xml, "w").write(SELF_TEST_XML)
    pack_dir = os.path.join(d, "t.pack")
    ns = argparse.Namespace(input=xml, pack_name="t", out=pack_dir,
                            max_articles=0)
    import build_pack
    build_pack.MIN_PROSE_CHARS = 50
    assert build(ns) == 0

    p = Pack(pack_dir)
    hits = p.title_boost_search("Who carved the moai of Easter Island?", k=5)
    assert hits, "no hits"
    assert "moai" in hits[0][2].lower(), hits[0][2][:120]
    # quoted phrase still works after sanitation
    hits2 = p.search('"Rano Raraku" quarry', k=5)
    assert hits2 and "rano raraku" in hits2[0][2].lower()
    # empty/garbage query degrades gracefully
    assert p.search("!!!", k=5) == []
    p.close()
    print("RETRIEVER SELF TEST PASSED:", d)


if __name__ == "__main__":
    self_test()
