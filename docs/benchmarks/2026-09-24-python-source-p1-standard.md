# CLI benchmark: python-source-p1

- Recorded: 2026-09-24T06:46:56.388713+00:00
- Reference checkout: `b473f37d3019ce3861d68a3eadc279e3fbfde1e0`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 131.74 | 126.27–134.58 | 38.73 |
| list-jsonl | 226.85 | 224.14–257.29 | 42.12 |
| head-large-jsonl | 133.13 | 130.41–144.67 | 39.16 |
| print-large-jsonl | 233.03 | 227.14–251.34 | 123.28 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
