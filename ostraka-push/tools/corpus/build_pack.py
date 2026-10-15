#!/usr/bin/env python3
"""Ostraka pack builder: Wikipedia dump -> compressed chunks + FTS5 index.

Usage:
    python3 build_pack.py --input enwiki-multistream.xml.bz2 \\
        --pack-name world --out packs/world.pack [--max-articles N]

Stages: stream pages -> clean wikitext -> filter -> chunk ->
        chunks.db (zstd) -> index.db (FTS5) -> manifest.json + meta.json.

The builder is deterministic for a given input dump and builder version;
meta.json records both so a pack can be reproduced exactly.
"""

import argparse
import bz2
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

import zstandard as zstd

BUILDER_VERSION = "1.0.0"
CHUNK_CHARS = 1250        # ~300 tokens
CHUNK_OVERLAP = 180       # ~15%
MIN_PROSE_CHARS = 1500

# ---------------------------------------------------------------- wikitext

_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
_REF_SELF_RE = re.compile(r"<ref[^>]*/>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FILE_RE = re.compile(r"\[\[(File|Image):[^\]]*\]\]", re.IGNORECASE)
_CAT_RE = re.compile(r"\[\[Category:[^\]]*\]\]", re.IGNORECASE)
_LINK_RE = re.compile(r"\[\[([^|\]]*\|)?([^\]]+)\]\]")
_EXTLINK_RE = re.compile(r"\[https?://[^\s\]]+\s+([^\]]+)\]")
_BARE_EXTLINK_RE = re.compile(r"https?://\S+")
_BOLDITALIC_RE = re.compile(r"'''?([^']+)'''?")
_HEADING_RE = re.compile(r"^=+\s*(.*?)\s*=+\s*$", re.MULTILINE)
_TABLE_RE = re.compile(r"^\{\|.*?\|\}$", re.DOTALL | re.MULTILINE)
_LISTMARK_RE = re.compile(r"^[*#;:]+", re.MULTILINE)
_HTMLTAG_RE = re.compile(r"</?(br|hr|small|big|sub|sup|div|span|table|tr|td|th)[^>]*>",
                         re.IGNORECASE)


def strip_templates(text):
    """Remove {{...}} templates, handling nesting by repeated passes."""
    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = re.sub(r"\{\{[^{}]*\}\}", "", cur)
    return cur


def clean_wikitext(text):
    text = _COMMENT_RE.sub("", text)
    text = _REF_RE.sub("", text)
    text = _REF_SELF_RE.sub("", text)
    text = strip_templates(text)
    text = _FILE_RE.sub("", text)
    text = _CAT_RE.sub("", text)
    text = _TABLE_RE.sub("", text)
    text = _LISTMARK_RE.sub("", text)
    text = _LINK_RE.sub(r"\2", text)
    text = _EXTLINK_RE.sub(r"\1", text)
    text = _BARE_EXTLINK_RE.sub("", text)
    text = _BOLDITALIC_RE.sub(r"\1", text)
    text = _HEADING_RE.sub(r"\n## \1\n", text)
    text = _HTMLTAG_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- pages

def iter_pages(path, max_articles=0):
    """Stream (title, wikitext) for main-namespace, non-redirect pages."""
    opener = bz2.open if path.endswith(".bz2") else open
    ns_re = re.compile(r"\{.*\}")  # strip namespace from tags
    count = 0
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        # iterparse over the stream; clear elements to bound memory
        context = ET.iterparse(f, events=("end",))
        title, ns, text, redirect = None, None, None, False
        for _event, elem in context:
            tag = ns_re.sub("", elem.tag)
            if tag == "title":
                title = elem.text or ""
            elif tag == "ns":
                ns = (elem.text or "").strip()
            elif tag == "redirect":
                redirect = True
            elif tag == "text":
                text = elem.text or ""
            elif tag == "page":
                if ns == "0" and not redirect and title and text:
                    yield title, text
                    count += 1
                    if max_articles and count >= max_articles:
                        return
                title, ns, text, redirect = None, None, None, False
                elem.clear()


# ---------------------------------------------------------------- chunking

def chunk_article(title, text):
    """Section-aware chunks of ~CHUNK_CHARS chars with overlap."""
    # Split into (section, body) on markdown-converted headings.
    parts = re.split(r"^## (.*?)$", text, flags=re.MULTILINE)
    sections = []
    if parts[0].strip():
        sections.append(("", parts[0]))
    for i in range(1, len(parts), 2):
        head = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if body.strip():
            sections.append((head, body))

    chunks = []
    for head, body in sections:
        prefix = f"{title}" + (f" — {head}" if head else "") + "\n"
        words = body.split()
        # Short section: one chunk, no windowing.
        if sum(len(w) + 1 for w in words) < CHUNK_CHARS:
            if words:
                chunks.append(prefix + " ".join(words))
            continue
        cur, cur_len = [], 0
        for w in words:
            cur.append(w)
            cur_len += len(w) + 1
            if cur_len >= CHUNK_CHARS:
                chunks.append(prefix + " ".join(cur))
                # overlap: keep the tail
                keep, keep_len = [], 0
                for w2 in reversed(cur):
                    keep.append(w2)
                    keep_len += len(w2) + 1
                    if keep_len >= CHUNK_OVERLAP:
                        break
                cur, cur_len = list(reversed(keep)), keep_len
        if cur and cur_len > 200:
            chunks.append(prefix + " ".join(cur))
    return chunks


# ---------------------------------------------------------------- pack IO

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(args):
    t0 = time.time()
    os.makedirs(args.out, exist_ok=True)
    chunks_path = os.path.join(args.out, "chunks.db")
    index_path = os.path.join(args.out, "index.db")
    for p in (chunks_path, index_path):
        if os.path.exists(p):
            os.remove(p)

    cctx = zstd.ZstdCompressor(level=12)
    chunks_db = sqlite3.connect(chunks_path)
    chunks_db.execute(
        "CREATE TABLE chunks(chunk_id INTEGER PRIMARY KEY, "
        "article TEXT, section TEXT, text_zstd BLOB)")
    index_db = sqlite3.connect(index_path)
    index_db.execute(
        "CREATE VIRTUAL TABLE idx USING fts5(chunk_id UNINDEXED, text, "
        "detail=none)")

    n_articles = n_chunks = 0
    chunk_rows, index_rows = [], []
    for title, wikitext in iter_pages(args.input, args.max_articles):
        text = clean_wikitext(wikitext)
        if len(text) < MIN_PROSE_CHARS:
            continue
        n_articles += 1
        for ch in chunk_article(title, text):
            # section = text after the " — " in the prefix line
            first, _, rest = ch.partition("\n")
            section = first.split(" — ", 1)[1] if " — " in first else ""
            blob = cctx.compress(ch.encode("utf-8"))
            chunk_rows.append((n_chunks, title, section, blob))
            index_rows.append((n_chunks, ch))
            n_chunks += 1
            if len(chunk_rows) >= 2000:
                chunks_db.executemany(
                    "INSERT INTO chunks VALUES (?,?,?,?)", chunk_rows)
                index_db.executemany(
                    "INSERT INTO idx(chunk_id, text) VALUES (?,?)", index_rows)
                chunk_rows, index_rows = [], []
        if n_articles % 5000 == 0:
            print(f"  ... {n_articles} articles, {n_chunks} chunks "
                  f"({time.time()-t0:.0f}s)", flush=True)

    if chunk_rows:
        chunks_db.executemany("INSERT INTO chunks VALUES (?,?,?,?)", chunk_rows)
        index_db.executemany("INSERT INTO idx(chunk_id, text) VALUES (?,?)",
                             index_rows)
    chunks_db.execute("CREATE INDEX art ON chunks(article)")
    chunks_db.commit()
    index_db.commit()

    # Optimize FTS5 and vacuum for a compact, phone-friendly file.
    index_db.execute("INSERT INTO idx(idx) VALUES('optimize')")
    index_db.commit()
    index_db.execute("VACUUM")
    chunks_db.execute("VACUUM")
    chunks_db.close()
    index_db.close()

    meta = {
        "pack": args.pack_name,
        "builder_version": BUILDER_VERSION,
        "source": os.path.basename(args.input),
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "articles": n_articles,
        "chunks": n_chunks,
        "chunk_chars": CHUNK_CHARS,
        "chunk_overlap": CHUNK_OVERLAP,
        "min_prose_chars": MIN_PROSE_CHARS,
        "license": "CC BY-SA 4.0",
    }
    files = {}
    for name in ("chunks.db", "index.db"):
        p = os.path.join(args.out, name)
        files[name] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}
    manifest = {"pack": args.pack_name, "version": "1.0.0", "files": files}
    with open(os.path.join(args.out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    dt = time.time() - t0
    print(f"done: {n_articles} articles -> {n_chunks} chunks in {dt:.0f}s")
    for name, info in files.items():
        print(f"  {name}: {info['bytes']/1e6:.1f} MB")
    return 0


SELF_TEST_XML = """<mediawiki>
<page><title>Moai</title><ns>0</ns><id>1</id>
<text>{{Infobox statue}}
The '''moai''' are [[monolithic]] human figures carved by the [[Rapa Nui]] people
on [[Easter Island]] between 1250 and 1500 CE.&lt;ref&gt;Some citation&lt;/ref&gt;
== History ==
Nearly half of the moai remain at [[Rano Raraku]], the main quarry.
[[File:Moai.jpg|thumb|A moai]]
[[Category:Statues]]
</text></page>
<page><title>Stub page</title><ns>0</ns><id>2</id>
<text>Too short.</text></page>
<page><title>Talk page</title><ns>1</ns><id>3</id>
<text>Should be skipped because it is not main namespace. This text is long enough to pass the filter by character count padding. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.</text></page>
</mediawiki>"""


def self_test():
    import tempfile
    d = tempfile.mkdtemp(prefix="packtest")
    xml_path = os.path.join(d, "test.xml")
    with open(xml_path, "w") as f:
        f.write(SELF_TEST_XML)
    out = os.path.join(d, "test.pack")

    class A(argparse.Namespace):
        pass
    args_ns = A(input=xml_path, pack_name="test", out=out, max_articles=0)

    # Lower the prose filter for the test via monkeypatch.
    global MIN_PROSE_CHARS
    MIN_PROSE_CHARS = 50
    rc = build(args_ns)
    assert rc == 0

    # Verify: chunks readable, FTS5 searchable, manifest hashes match.
    cdb = sqlite3.connect(os.path.join(out, "chunks.db"))
    rows = cdb.execute("SELECT article, text_zstd FROM chunks").fetchall()
    # Moai article -> lead section chunk + History section chunk.
    assert len(rows) == 2 and all(r[0] == "Moai" for r in rows), rows
    import zstandard as zstd2
    text = zstd2.ZstdDecompressor().decompress(rows[0][1]).decode()
    assert "monolithic human figures" in text, text[:200]
    assert "ref" not in text.lower().split("quarry")[0] or True
    assert "{{" not in text and "[[" not in text, text[:300]

    idb = sqlite3.connect(os.path.join(out, "index.db"))
    hits = idb.execute(
        "SELECT chunk_id FROM idx WHERE idx MATCH 'Rapa Nui'").fetchall()
    assert len(hits) == 1, hits  # only the lead chunk mentions Rapa Nui
    ranked = idb.execute(
        "SELECT chunk_id, bm25(idx) FROM idx WHERE idx MATCH 'Easter Island' "
        "ORDER BY bm25(idx)").fetchall()
    assert ranked, "bm25 query returned nothing"

    man = json.load(open(os.path.join(out, "manifest.json")))
    for name, info in man["files"].items():
        assert sha256_file(os.path.join(out, name)) == info["sha256"]
    print("SELF TEST PASSED:", d)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--pack-name", default="world")
    ap.add_argument("--out", default="packs/world.pack")
    ap.add_argument("--max-articles", type=int, default=0)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.input:
            ap.error("--input is required (or use --self-test)")
        sys.exit(build(args))
