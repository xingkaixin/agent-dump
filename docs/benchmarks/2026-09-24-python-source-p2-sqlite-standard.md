# CLI benchmark: python-source-p2-sqlite

- Recorded: 2026-09-24T09:06:52.781114+00:00
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
| startup-version | 218.65 | 188.63–425.92 | 38.86 |
| list-jsonl | 387.34 | 340.12–419.11 | 42.17 |
| list-sqlite | 249.30 | 212.36–401.82 | 40.95 |
| head-large-jsonl | 240.93 | 219.68–396.88 | 39.42 |
| print-large-jsonl | 474.70 | 384.84–547.03 | 123.81 |
| export-large-json-md | 270.67 | 255.38–303.40 | 151.66 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
