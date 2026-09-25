# CLI benchmark: python-p6-standard

- Recorded: 2026-09-25T00:38:12.387663+00:00
- Reference checkout: `a4fee7ba755762aaf6fc7719dc4b181646f145c0`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/.venv/bin/python' -m agent_dump`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 5; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| startup-version | 141.53 | 137.41–144.94 | 38.73 |
| startup-help | 142.81 | 141.75–146.37 | 38.84 |
| list-jsonl | 249.17 | 241.06–268.89 | 42.23 |
| list-sqlite | 152.69 | 148.71–154.34 | 40.81 |
| list-all | 260.06 | 256.49–338.62 | 44.00 |
| stats-all | 257.62 | 248.92–268.47 | 43.91 |
| head-large-jsonl | 146.52 | 143.56–151.57 | 39.27 |
| print-large-jsonl | 248.15 | 246.52–251.62 | 123.45 |
| export-large-json-md | 261.99 | 255.57–397.64 | 151.55 |
| export-batch-jsonl | 905.94 | 879.89–924.94 | 143.98 |
| reindex-empty | 2966.14 | 2935.16–3259.96 | 313.55 |
| search-cold-index | 3283.86 | 3203.15–3399.43 | 313.81 |
| search-warm-index | 545.76 | 542.51–629.60 | 221.19 |
| search-cjk-warm | 553.03 | 547.78–605.37 | 232.50 |
| search-fallback-warm | 422.62 | 421.62–433.33 | 186.28 |
| collect-dry-run | 1890.63 | 1757.12–1990.91 | 229.00 |
| collect-emit-prompt | 271.88 | 265.60–274.29 | 48.58 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
