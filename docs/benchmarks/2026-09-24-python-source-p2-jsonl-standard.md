# CLI benchmark: python-source-p2-jsonl

- Recorded: 2026-09-24T08:07:03.895203+00:00
- Reference checkout: `366954255f7cdb38841f3dbd2950121a418e69e3`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 138.57 | 134.56–156.15 | 38.81 |
| list-jsonl | 238.69 | 235.53–257.44 | 42.20 |
| head-large-jsonl | 142.34 | 140.00–148.18 | 39.19 |
| print-large-jsonl | 238.43 | 237.18–256.30 | 123.52 |
| export-large-json-md | 241.28 | 237.29–253.31 | 151.69 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
