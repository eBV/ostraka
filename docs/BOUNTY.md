# Bounty 31 compliance — requirement to evidence

Each requirement from https://poidh.xyz/mainnet/bounty/31, mapped to where it
is proven. Status is updated as the build lands.

| # | Requirement | Evidence | Status |
|---|---|---|---|
| 1 | Runs on Android and compatible GrapheneOS hardware | `app/` Kotlin app, minSdk 26, arm64-v8a; CI emulator smoke test; Test Lab physical-device run | scaffold |
| 2 | Operates within a maximum 12GB RAM environment | RAM budget in ARCHITECTURE.md; `nativeInit` refuses models that do not fit free RAM; per-device bench | scaffold |
| 3 | <= 50GB total for app, weights, indexes, databases | Storage budget ~36GB worst case (deep 17.3 + world ~13 + fast 4.9 + core 1 + app) | planned |
| 4 | Works completely offline once installed | `clean` flavor declares no `INTERNET` permission (`aapt2 dump permissions`); airplane-mode demo video | scaffold |
| 5 | No API calls, remote inference, web searches, or network requests during use | clean flavor cannot open sockets (OS-enforced); static analysis in CI | planned |
| 6 | No Google Play Services for core offline functionality | Zero GMS dependencies in `app/app/build.gradle` | done |
| 7 | Handles explanation, comparison, synthesis, reasoning | Answer pipeline (classify -> retrieve -> rerank -> synthesize -> verify); eval set covers all four | scaffold |
| 8 | Usable speeds for real lookups | Per-answer measured tok/s in UI; `:bench` per-device config | planned |
| 9 | Published in a public GitHub repository | (pending user GitHub connection) | blocked |
| 10 | All code, assets, dependencies, instructions to reproduce | Pack builder, eval set, CI, docs; models/packs via documented downloads | in progress |
| 11 | Documents models, datasets, indexes, resources | ARCHITECTURE.md, docs/PACK-FORMAT.md, docs/MODELS.md (to write) | in progress |
| 12 | Real-device requirement | Test Lab physical Pixel run + video; install instructions for any Android 8+ arm64 device | planned |
| 13 | Public demo on X/Farcaster: offline run, example queries incl. 1B-killers, repo link, approach | Demo video + thread (user posts) | planned |
| 14 | poidh claim: screenshot + post link + repo link; repo holds submitted version | Claim prep (user signs) | planned |

Winner bar: useful, fully offline research tool >50% as good as internet +
frontier models. Our edge: the disk-streamed MoE architecture Vitalik
suggested (neither competitor built it), full-Wikipedia retrieval, verified
citations, honest measured metrics.
