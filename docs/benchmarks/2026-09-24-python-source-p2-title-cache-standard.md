# CLI benchmark: python-source-p2-title-cache

- Recorded: 2026-09-24T11:55:38.223967+00:00
- Reference checkout: `768e4baeb2c57a55f6961309a6a5b39990eb6aa6`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 142.38 | 141.05–149.21 | 38.89 |
| list-jsonl | 243.39 | 241.70–253.18 | 42.33 |
| list-sqlite | 148.86 | 147.25–157.69 | 40.88 |
| list-all | 253.62 | 250.22–278.77 | 43.91 |
| head-large-jsonl | 144.72 | 143.46–146.28 | 39.25 |
| print-large-jsonl | 245.07 | 241.64–248.03 | 123.58 |
| export-large-json-md | 248.25 | 246.07–263.63 | 151.62 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
