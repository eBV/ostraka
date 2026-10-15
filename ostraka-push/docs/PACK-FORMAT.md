# Pack format v1

A *pack* is a self-contained knowledge collection: compressed text chunks plus a
search index. Packs are built reproducibly by `tools/corpus/build_pack.py` and
installed on the phone from Downloads via the system file picker.

## Files

```
<name>.pack/
  manifest.json        # pack metadata + SHA-256 of every file
  chunks.db            # SQLite: chunk_id INTEGER PK, article TEXT, section TEXT,
                       #         text_zstd BLOB (zstd-compressed chunk text)
  index.db             # SQLite FTS5 (detail=none): chunk_id, text
                       #         (external-content-less; text duplicated for speed)
  meta.json            # source dump id + date, article count, chunk count,
                       #         license, builder version
```

## Manifest

```json
{
  "pack": "world",
  "version": "1.0.0",
  "source": "enwiki-20261001-pages-articles-multistream",
  "articles": 2871344,
  "chunks": 9120441,
  "license": "CC BY-SA 4.0",
  "files": {"chunks.db": {"sha256": "…", "bytes": 0}, "index.db": {"sha256": "…", "bytes": 0}}
}
```

## Install verification

On import, the app recomputes SHA-256 of each file against the manifest and
refuses the pack on mismatch, naming the bad file. Partial copies are deleted.

## Chunking

Section-aware, ~300 tokens per chunk, 15% overlap, article title prepended to
each chunk for context. Stubs (<1.5 kB prose), lists, disambiguation pages, and
redirects are dropped at build time.
