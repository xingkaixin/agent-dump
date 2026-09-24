# CLI benchmark: python-native

- Recorded: 2026-09-24T06:20:39.966346+00:00
- Reference checkout: `a3d8f1880041ff95e3e3b88523c5b3f231145372`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/dist/agent-dump'`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 7; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| startup-version | 495.06 | 457.82–510.94 | 45.47 |
| startup-help | 505.94 | 493.80–542.38 | 45.36 |
| list-jsonl | 605.53 | 584.15–614.94 | 48.12 |
| list-sqlite | 486.34 | 471.55–516.23 | 47.55 |
| list-all | 609.34 | 596.24–617.33 | 49.23 |
| stats-all | 608.00 | 593.60–635.77 | 49.30 |
| head-large-jsonl | 496.82 | 480.53–506.97 | 45.80 |
| print-large-jsonl | 605.85 | 590.47–618.11 | 129.83 |
| export-large-json-md | 604.56 | 595.53–615.06 | 158.12 |
| export-batch-jsonl | 1189.75 | 1161.28–1210.48 | 149.59 |
| reindex-empty | 3366.96 | 3269.36–3601.26 | 321.44 |
| search-cold-index | 3566.76 | 3482.61–3806.92 | 319.20 |
| search-warm-index | 923.36 | 917.67–949.54 | 224.72 |
| search-cjk-warm | 925.85 | 896.86–946.58 | 237.89 |
| search-fallback-warm | 785.43 | 768.92–822.25 | 191.34 |
| collect-dry-run | 2192.33 | 2146.93–2283.82 | 234.08 |
| collect-emit-prompt | 637.47 | 623.04–658.39 | 53.33 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 0.30x | +17.0 |
| startup-help | 0.29x | +16.9 |
| list-jsonl | 0.43x | +13.5 |
| list-sqlite | 0.35x | +16.3 |
| list-all | 0.43x | +12.2 |
| stats-all | 0.43x | +12.4 |
| head-large-jsonl | 0.29x | +16.9 |
| print-large-jsonl | 0.41x | +5.3 |
| export-large-json-md | 0.44x | +4.3 |
| export-batch-jsonl | 0.79x | +3.8 |
| reindex-empty | 0.87x | +2.5 |
| search-cold-index | 0.89x | +1.8 |
| search-warm-index | 0.60x | +2.1 |
| search-cjk-warm | 0.63x | +2.1 |
| search-fallback-warm | 0.59x | +2.8 |
| collect-dry-run | 0.82x | +2.4 |
| collect-emit-prompt | 0.41x | +9.8 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
