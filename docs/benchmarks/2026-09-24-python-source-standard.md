# CLI benchmark: python-source

- Recorded: 2026-09-24T06:18:28.405736+00:00
- Reference checkout: `a3d8f1880041ff95e3e3b88523c5b3f231145372`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/.venv/bin/python' -m agent_dump`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 7; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| startup-version | 150.54 | 144.59–158.49 | 38.86 |
| startup-help | 147.01 | 140.66–152.85 | 38.80 |
| list-jsonl | 260.23 | 245.75–316.29 | 42.41 |
| list-sqlite | 171.31 | 147.79–190.24 | 40.89 |
| list-all | 264.34 | 247.57–314.35 | 43.89 |
| stats-all | 263.70 | 251.59–278.42 | 43.86 |
| head-large-jsonl | 144.35 | 137.51–150.00 | 39.19 |
| print-large-jsonl | 245.72 | 237.75–274.59 | 123.30 |
| export-large-json-md | 266.55 | 245.45–358.13 | 151.62 |
| export-batch-jsonl | 938.58 | 885.61–1007.92 | 144.12 |
| reindex-empty | 2928.99 | 2897.62–3215.57 | 313.58 |
| search-cold-index | 3167.90 | 3135.69–3236.96 | 313.61 |
| search-warm-index | 556.11 | 546.34–632.69 | 220.09 |
| search-cjk-warm | 587.53 | 568.68–694.96 | 233.05 |
| search-fallback-warm | 465.46 | 439.30–529.21 | 186.11 |
| collect-dry-run | 1795.40 | 1781.97–1825.91 | 228.53 |
| collect-emit-prompt | 263.99 | 259.92–278.97 | 48.55 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
