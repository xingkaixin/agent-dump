# CLI benchmark: python-source-p2-message-conversion

- Recorded: 2026-09-24T12:13:39.302702+00:00
- Reference checkout: `fa39040f15a4fa8ca064e161e15305cb9fd9df17`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 194.30 | 181.20–211.89 | 38.98 |
| list-jsonl | 376.84 | 341.29–513.82 | 42.33 |
| list-sqlite | 203.58 | 189.13–237.04 | 40.86 |
| list-all | 256.68 | 249.87–302.20 | 44.09 |
| head-large-jsonl | 145.37 | 143.00–150.59 | 39.19 |
| print-large-jsonl | 245.96 | 242.10–260.37 | 123.44 |
| export-large-json-md | 252.59 | 247.28–273.17 | 151.59 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
