# CLI benchmark: python-p3-p5-reference

- Recorded: 2026-09-24T17:01:03.135633+00:00
- Reference checkout: `b15f079f2e5e777aaf81a2d36e313863c39e5681`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 129.66 | 125.18–135.72 | 38.58 |
| startup-help | 127.50 | 126.11–136.69 | 38.59 |
| list-jsonl | 224.00 | 222.12–252.02 | 42.25 |
| list-sqlite | 130.51 | 129.57–143.75 | 40.56 |
| list-all | 232.32 | 230.87–253.71 | 43.95 |
| stats-all | 245.19 | 235.40–258.60 | 43.77 |
| head-large-jsonl | 131.83 | 127.04–140.63 | 39.11 |
| print-large-jsonl | 225.34 | 223.57–249.34 | 123.19 |
| export-large-json-md | 237.28 | 227.82–241.30 | 151.31 |
| export-batch-jsonl | 809.42 | 793.05–834.47 | 143.95 |
| reindex-empty | 2827.45 | 2759.94–2884.89 | 313.56 |
| search-cold-index | 3074.35 | 3040.79–3096.42 | 313.23 |
| search-warm-index | 520.15 | 519.23–524.71 | 220.39 |
| search-cjk-warm | 526.68 | 524.48–545.38 | 232.97 |
| search-fallback-warm | 399.00 | 394.61–418.28 | 187.31 |
| collect-dry-run | 1738.54 | 1724.78–1751.99 | 228.91 |
| collect-emit-prompt | 252.13 | 248.28–256.01 | 48.33 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
