# CLI benchmark: python-source-p2-codex

- Recorded: 2026-09-24T07:20:08.523706+00:00
- Reference checkout: `ca4b1db3f9b3b9efc9d2d00e05ef7833644634c8`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 269.57 | 206.66–371.92 | 38.94 |
| list-jsonl | 367.56 | 309.38–445.36 | 42.12 |
| head-large-jsonl | 211.50 | 186.43–241.96 | 39.42 |
| print-large-jsonl | 336.10 | 302.79–451.49 | 123.55 |
| export-large-json-md | 363.59 | 331.84–443.73 | 151.84 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
