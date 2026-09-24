# CLI benchmark: python-source-p2-sqlite-repeat

- Recorded: 2026-09-24T09:07:59.291985+00:00
- Reference checkout: `aec8b471ca9e4dc0a686ae0b0616145361621757`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 161.35 | 144.05–198.04 | 38.95 |
| list-jsonl | 242.49 | 229.75–310.23 | 42.23 |
| list-sqlite | 148.94 | 147.33–152.60 | 40.75 |
| head-large-jsonl | 148.36 | 142.50–150.81 | 39.19 |
| print-large-jsonl | 244.65 | 242.51–246.89 | 123.52 |
| export-large-json-md | 248.94 | 245.77–253.13 | 151.64 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
