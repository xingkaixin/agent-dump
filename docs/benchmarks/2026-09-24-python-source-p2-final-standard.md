# CLI benchmark: python-source-p2-final

- Recorded: 2026-09-24T14:52:46.643603+00:00
- Reference checkout: `d074c63213dc6849f19e661121ad9b3f3f7cbf6d`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 154.90 | 149.89–160.47 | 38.83 |
| list-jsonl | 253.03 | 250.29–258.60 | 42.34 |
| list-sqlite | 158.69 | 153.83–162.40 | 40.94 |
| list-all | 269.32 | 263.27–276.08 | 44.03 |
| head-large-jsonl | 154.62 | 153.31–155.52 | 39.23 |
| print-large-jsonl | 260.05 | 256.27–281.69 | 123.62 |
| export-large-json-md | 267.14 | 261.08–311.42 | 151.59 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
