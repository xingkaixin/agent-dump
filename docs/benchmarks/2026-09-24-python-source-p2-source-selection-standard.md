# CLI benchmark: python-source-p2-source-selection

- Recorded: 2026-09-24T12:34:47.432836+00:00
- Reference checkout: `3e599a98efc7460dbf4c6aff547a70c10a5a9853`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 149.91 | 147.69–153.20 | 38.81 |
| list-jsonl | 247.47 | 244.78–249.28 | 42.22 |
| list-sqlite | 153.16 | 152.44–155.71 | 40.98 |
| list-all | 255.18 | 254.01–258.00 | 43.89 |
| head-large-jsonl | 148.30 | 147.22–152.40 | 39.28 |
| print-large-jsonl | 250.67 | 247.23–258.60 | 123.52 |
| export-large-json-md | 253.58 | 247.79–275.16 | 151.59 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
