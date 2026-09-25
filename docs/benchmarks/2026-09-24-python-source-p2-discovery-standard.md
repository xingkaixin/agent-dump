# CLI benchmark: python-source-p2-discovery

- Recorded: 2026-09-24T10:06:10.125388+00:00
- Reference checkout: `92bace38fef9f3f32d91d47c720ec30bb4492cf7`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 141.08 | 138.81–141.80 | 38.83 |
| list-jsonl | 236.45 | 233.84–241.67 | 42.23 |
| list-sqlite | 144.93 | 142.49–152.27 | 40.84 |
| list-all | 246.17 | 244.10–251.01 | 43.98 |
| head-large-jsonl | 142.84 | 141.79–148.73 | 39.27 |
| print-large-jsonl | 243.19 | 238.82–246.70 | 123.64 |
| export-large-json-md | 248.61 | 243.74–262.70 | 151.67 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
