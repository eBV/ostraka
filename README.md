# Ostraka

**Offline research on an Android phone, in airplane mode.** Ask hard questions,
get cited answers, no network, no cloud, no permission prompts. Every number,
date, and name is checked against its cited passage before you read it.

Built for [poidh mainnet bounty 31](https://poidh.xyz/mainnet/bounty/31):
*Build the Best Offline AI Research App for Android*, inspired by
[Vitalik Buterin's post](https://x.com/VitalikButerin/status/2100695863026954698)
on a casual info-lookup tool that is >50% as good as internet + frontier models
and works on a fully offline phone.

## Why "Ostraka"

*Ostraka* (Greek, plural of *ostrakon*) are broken pieces of pottery. In ancient
Athens, citizens scratched votes onto potsherds; the word *ostracism* comes from
it. Outside election day, ostraka were the ancient world's scratch paper: tax
receipts, letters, school exercises, thousands of which survive because pottery
is free, everywhere, and lasts forever. No servers, no cloud, no permission.

That is the product metaphor and the architecture at once: knowledge shattered
into durable fragments, each one citable, reassembled into answers. Broken
pieces that together reconstruct the whole.

## The bet

Vitalik suggested *extreme MoE*: ~100B params living on disk, <1B activated per
token. Ostraka pairs that with the biggest knowledge base in the bounty: a
full-English-Wikipedia hybrid retrieval index (BM25 FTS5 + cross-encoder
rerank), not a curated subset. A claim verifier checks every name, number, and
date against its cited passage before the answer renders. Two inference tiers
(Qwen3-30B-A3B class deep tier, Qwen3-8B class fast tier), demand-paged from
storage so only the experts each token routes to ever enter RAM.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the locked design.

## Status

2026-10-15: architecture locked; corpus pipeline and Android build in progress.
Target submission: 2026-10-31.

## Layout

- `app/` — Android app (Kotlin + JNI, llama.cpp in-process). Two flavors:
  `clean` (no `INTERNET` permission; the submission) and `dev` (download tooling).
- `tools/corpus/` — reproducible pack builder: dump → text → chunks → FTS5 index.
- `tools/pipeline/` — reference answer pipeline: retrieval, rerank, synthesis,
  claim verification.
- `tools/eval/` — frozen 24-question eval set + rubric scorer.
- `docs/` — requirement-to-evidence mapping, device notes, model cards.
- `.github/workflows/` — CI: build APK, emulator install + Q&A smoke test.

## Build

Corpus pack (needs ~30 GB free, several hours):

```bash
python3 tools/corpus/build_pack.py --dump enwiki-latest-pages-articles-multistream.xml.bz2 --out packs/enwiki-v1
```

Android app (needs JDK 17, Android SDK, NDK, CMake):

```bash
cd app && ./gradlew :app:assembleCleanRelease
```

Model weights (reranker, LLM) are fetched by script, not vendored; see
`docs/` for the exact revisions and checksums.

## License

MIT. See [LICENSE](LICENSE).
