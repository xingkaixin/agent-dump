# CLI benchmark: rust-p3-p5

- Recorded: 2026-09-24T17:03:03.156208+00:00
- Reference checkout: `b15f079f2e5e777aaf81a2d36e313863c39e5681`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/rust/target/release/agent-dump'`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 5; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| startup-version | 4.57 | 4.40–5.09 | 3.08 |
| startup-help | 4.46 | 4.45–4.59 | 3.20 |
| list-jsonl | 50.31 | 48.19–51.81 | 6.70 |
| list-sqlite | 9.84 | 9.82–13.73 | 10.59 |
| list-all | 52.17 | 52.01–56.04 | 12.36 |
| stats-all | 52.85 | 51.20–54.73 | 10.36 |
| head-large-jsonl | 8.07 | 7.91–8.15 | 4.81 |
| print-large-jsonl | 50.33 | 49.48–51.95 | 54.30 |
| export-large-json-md | 86.40 | 84.86–93.29 | 54.62 |
| export-batch-jsonl | 3643.98 | 3195.08–3846.14 | 47.72 |
| reindex-empty | 923.28 | 920.42–933.55 | 114.73 |
| search-cold-index | 1160.20 | 1148.08–1193.34 | 142.81 |
| search-warm-index | 291.44 | 291.04–298.80 | 113.53 |
| search-cjk-warm | 302.37 | 300.38–307.31 | 115.22 |
| search-fallback-warm | 126.41 | 125.16–131.68 | 80.17 |
| collect-dry-run | 295.90 | 292.62–303.72 | 105.91 |
| collect-emit-prompt | 62.09 | 61.35–65.42 | 12.31 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 28.40x | -92.0 |
| startup-help | 28.56x | -91.7 |
| list-jsonl | 4.45x | -84.1 |
| list-sqlite | 13.27x | -73.9 |
| list-all | 4.45x | -71.9 |
| stats-all | 4.64x | -76.3 |
| head-large-jsonl | 16.34x | -87.7 |
| print-large-jsonl | 4.48x | -55.9 |
| export-large-json-md | 2.75x | -63.9 |
| export-batch-jsonl | 0.22x | -66.9 |
| reindex-empty | 3.06x | -63.4 |
| search-cold-index | 2.65x | -54.4 |
| search-warm-index | 1.78x | -48.5 |
| search-cjk-warm | 1.74x | -50.5 |
| search-fallback-warm | 3.16x | -57.2 |
| collect-dry-run | 5.88x | -53.7 |
| collect-emit-prompt | 4.06x | -74.5 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
