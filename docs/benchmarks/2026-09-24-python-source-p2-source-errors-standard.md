# CLI benchmark: python-source-p2-source-errors

- Recorded: 2026-09-24T11:11:53.829581+00:00
- Reference checkout: `0d2fc2ae1e7e0fb223556bf3a637414a9f162b5f`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 134.10 | 127.81–136.65 | 38.73 |
| list-jsonl | 228.61 | 223.40–244.88 | 42.19 |
| list-sqlite | 132.48 | 131.06–139.20 | 40.58 |
| list-all | 239.77 | 236.32–246.92 | 43.86 |
| head-large-jsonl | 136.51 | 135.14–140.36 | 39.11 |
| print-large-jsonl | 236.09 | 227.22–241.18 | 123.38 |
| export-large-json-md | 231.07 | 229.72–232.87 | 151.34 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
