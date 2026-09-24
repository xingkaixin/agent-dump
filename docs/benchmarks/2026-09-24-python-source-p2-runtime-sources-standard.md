# CLI benchmark: python-source-p2-runtime-sources

- Recorded: 2026-09-24T13:00:15.929772+00:00
- Reference checkout: `a42bbc6712ec8d0f53bbfa63c90782af20ef60c7`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 141.64 | 140.56–148.27 | 38.75 |
| list-jsonl | 237.99 | 235.14–240.65 | 42.27 |
| list-sqlite | 147.53 | 146.93–148.46 | 40.94 |
| list-all | 247.15 | 246.13–251.21 | 43.91 |
| head-large-jsonl | 143.62 | 142.99–144.57 | 39.28 |
| print-large-jsonl | 244.52 | 243.47–247.58 | 123.45 |
| export-large-json-md | 246.52 | 245.06–250.30 | 151.69 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
