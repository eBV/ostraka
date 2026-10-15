# Ostraka — architecture (locked 2026-10-15)

Working title: **Ostraka** (rename if the user picks otherwise; package `dev.ostraka.app`).
Target: poidh mainnet bounty 31, "Build the Best Offline AI Research App for Android".
Deadline: 2026-10-31. Bar: a fully offline research tool >50% as good as internet + frontier models.

## The idea in one paragraph

Nobody has built the architecture Vitalik actually suggested: ~100B-class parameters
living on disk with <1B active per token. Ostraka does it with a real
mixture-of-experts model (Qwen3-30B-A3B class: 30.5B params, 128 experts, ~3.3B
active per token) whose weights are demand-paged from storage via mmap, so only
the experts a token routes to ever enter RAM. Knowledge lives in a second
disk-resident structure: a full-English-Wikipedia hybrid retrieval index
(BM25 + cross-encoder rerank). A citation verifier checks every name, number,
and date in the answer against the cited passages before the user reads it.
The clean build declares no `INTERNET` permission, so offline is architectural,
not a mode.

## Model tiers

| Tier | Model | File | Active params | Role |
|---|---|---|---|---|
| deep (default) | Qwen3-30B-A3B-Instruct Q4_K_M (unsloth GGUF) | ~17.3 GB | ~3.3B / token | synthesis, reasoning, hard questions |
| fast | Qwen3-8B Q4_K_M (unsloth GGUF) | ~4.9 GB | 8B dense | quick lookups, query rewrite |

RAM math (deep tier, 12 GB ceiling): always-active weights (attention, shared
experts, router, embeddings) ~2 GB hot in page cache; routed experts demand-paged
(~20 MB per layer per token, high reuse across tokens); KV cache (Q8, 4k ctx)
~1.5 GB; app + index pages ~1 GB. Expected steady RSS 5–7 GB. If free RAM is
lower at load time, the app refuses the deep tier with a reason and offers fast.

Speed expectation (honest, to be measured per device): deep tier ~2–6 tok/s
decode on flagship ARM CPUs; fast tier ~8–15 tok/s. Every answer shows its own
measured tok/s, never a vendor claim.

## Corpus packs

| Pack | Contents | Size on device | Role |
|---|---|---|---|
| world | enwiki filtered (~2–3M articles) → ~300-token chunks, zstd; FTS5 BM25 index (detail=none) | ~12–14 GB | default knowledge |
| core | Simple English Wikipedia, same pipeline | ~1 GB | small-phone fallback |
| demo | 200 hand-picked articles, same pipeline | ~40 MB | CI / Test Lab / quick start |

Build pipeline (all reproducible, in `tools/corpus/`):
`dumps.wikimedia.org` multistream bz2 (~25 GB) → WikiExtractor → filter
(drop stubs < 1.5 kB prose, lists, disambiguation, redirects) → section-aware
chunking (300 tokens, 15% overlap) → zstd chunk store (SQLite blob table) →
FTS5 index over chunk text (detail=none to control size) → pack manifest with
SHA-256 per file. Licenses: CC BY-SA 4.0 (Wikipedia), documented per pack.

Storage budget (50 GB cap): deep model 17.3 + world pack ~13 + fast model 4.9
+ core pack 1 + app 0.1 ≈ 36 GB worst case with everything installed.

## Answer pipeline

1. **Classify + rewrite** (fast tier, ~1 s): detect question type
   (factual / explanation / comparison / synthesis / reasoning); emit 1–3
   sub-queries for multi-hop; comparison questions fetch each entity.
2. **Retrieve**: FTS5 BM25 over chunks, top 40 per sub-query, title-match boost.
3. **Rerank**: cross-encoder (ms-marco-MiniLM-L-6-v2, ONNX, ~80 MB, phone CPU
   ~1–2 s for 40 pairs) → top 6–8 passages.
4. **Synthesize** (deep tier): passages injected with `[n]` ids; system prompt
   demands inline citations and forbids uncited specifics.
5. **Verify**: extract claims (named entities, numbers, dates) from the answer;
   check each against cited passages (exact/near match); anything unverifiable
   is marked ⚠, and if the corpus has nothing, the answer is ∅ with the reason,
   never a guess.

## App

- Kotlin, single-activity, Jetpack Compose UI. llama.cpp in-process via JNI
  (established pattern; arm64-v8a + x86_64 ABIs, the latter for the emulator).
- Two flavors: `clean` (no `INTERNET` permission; the submission) and `dev`
  (permission present, for corpus/model download tooling only).
- Models and packs install from Downloads via the system file picker; SHA-256
  verified on import; resumable copies.
- `:bench`-style per-device measurement on first run; config persisted.
- Airplane-mode banner: the app detects radios off and shows it in the demo.

## Proof plan

- Public X/Farcaster post: airplane-mode screen recording (Firebase Test Lab,
  physical Pixel, demo pack + fast tier to fit session limits), hard queries
  including 1B-killers, repo link, approach summary.
- poidh claim: screenshot + post link + repo link, signed by the user.
- Repo contains: full source, pack builder, eval set + scorer, CI workflow,
  per-device evidence docs, third-party attributions.

## Eval

24-question set: 6 factual, 6 explanation, 6 comparison/synthesis, 6 reasoning,
including questions a 1B model demonstrably fails. Scored by rubric (correctness,
citation faithfulness, completeness) against an online baseline, reported
honestly even if under 50%. Demo questions are the subset where we are
genuinely strong.

## Considered and declined

- **Pure n-gram LM** (Vitalik named n-grams as a direction): superb for
  autocomplete-style factual recall, but cannot do explanation, comparison, or
  synthesis. The MoE gives us the same "disk-resident parameters" property
  with general reasoning. Documented, not built.
- **Dense-vector index over all chunks**: 10M+ chunk embeddings are too slow
  to build on available hardware; BM25 + query-time cross-encoder rerank gets
  ~90% of the quality at a fraction of the build cost.
- **Speculative decoding** (0.6B draft + 30B target): real speedup, but doubles
  integration risk. Stretch goal after the core pipeline is green.
- **GPU (Vulkan) backend**: opportunistic only; the engine must answer on CPU
  alone, per the no-special-chip rule.

## Risks

1. Deep-tier decode speed on mid-range phones (mitigation: fast tier, short
   answers, honest metrics).
2. Corpus build time on 2 vCPUs (mitigation: start download now, run in
   background, stage the pipeline).
3. No Android hardware in hand (mitigation: emulator CI + Test Lab physical
   device; borrow a phone if the user can arrange it).
