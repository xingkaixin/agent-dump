# CLI benchmark: python-source-p2-record-warnings

- Recorded: 2026-09-24T11:32:06.562450+00:00
- Reference checkout: `dd9582193bb905c14d75eb02249fbe8d742cd5c5`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 143.93 | 140.20–149.74 | 38.89 |
| list-jsonl | 246.73 | 239.03–252.11 | 42.34 |
| list-sqlite | 149.36 | 143.43–150.79 | 40.94 |
| list-all | 246.92 | 245.36–251.39 | 43.20 |
| head-large-jsonl | 164.53 | 151.35–179.94 | 39.16 |
| print-large-jsonl | 257.62 | 249.24–269.33 | 123.41 |
| export-large-json-md | 276.68 | 255.55–284.58 | 151.45 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
