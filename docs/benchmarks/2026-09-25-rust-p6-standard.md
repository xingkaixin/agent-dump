# CLI benchmark: rust-p6-standard

- Recorded: 2026-09-25T00:38:12.817347+00:00
- Reference checkout: `a4fee7ba755762aaf6fc7719dc4b181646f145c0`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/dist/p6-final/native/darwin-arm64/agent-dump'`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 5; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| startup-version | 5.09 | 4.95–5.30 | 3.41 |
| startup-help | 5.32 | 4.96–5.49 | 3.58 |
| list-jsonl | 53.72 | 51.35–54.11 | 6.83 |
| list-sqlite | 11.16 | 11.08–11.51 | 10.52 |
| list-all | 56.83 | 55.98–57.60 | 12.55 |
| stats-all | 54.06 | 52.85–54.61 | 10.56 |
| head-large-jsonl | 7.92 | 7.61–8.86 | 4.98 |
| print-large-jsonl | 51.99 | 51.52–54.75 | 56.44 |
| export-large-json-md | 76.51 | 74.20–78.31 | 56.02 |
| export-batch-jsonl | 367.69 | 355.15–381.96 | 48.77 |
| reindex-empty | 1061.51 | 1016.71–1110.62 | 115.27 |
| search-cold-index | 1271.93 | 1251.89–1305.31 | 144.06 |
| search-warm-index | 306.96 | 303.29–313.69 | 113.97 |
| search-cjk-warm | 316.97 | 312.16–319.78 | 116.61 |
| search-fallback-warm | 137.14 | 133.61–167.54 | 80.45 |
| collect-dry-run | 313.19 | 305.95–323.14 | 106.03 |
| collect-emit-prompt | 66.02 | 65.19–68.68 | 12.64 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 27.79x | -91.2 |
| startup-help | 26.84x | -90.8 |
| list-jsonl | 4.64x | -83.8 |
| list-sqlite | 13.68x | -74.2 |
| list-all | 4.58x | -71.5 |
| stats-all | 4.77x | -75.9 |
| head-large-jsonl | 18.51x | -87.3 |
| print-large-jsonl | 4.77x | -54.3 |
| export-large-json-md | 3.42x | -63.0 |
| export-batch-jsonl | 2.46x | -66.1 |
| reindex-empty | 2.79x | -63.2 |
| search-cold-index | 2.58x | -54.1 |
| search-warm-index | 1.78x | -48.5 |
| search-cjk-warm | 1.74x | -49.8 |
| search-fallback-warm | 3.08x | -56.8 |
| collect-dry-run | 6.04x | -53.7 |
| collect-emit-prompt | 4.12x | -74.0 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
