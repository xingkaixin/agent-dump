# CLI benchmark: python-source-p2-codex-final

- Recorded: 2026-09-24T07:24:46.404207+00:00
- Reference checkout: `1c037d3a1024460c75a7be6132330835893fb107`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 138.94 | 134.26–162.76 | 38.86 |
| list-jsonl | 244.11 | 234.96–312.37 | 42.33 |
| head-large-jsonl | 143.14 | 141.41–148.15 | 39.23 |
| print-large-jsonl | 238.71 | 236.63–241.22 | 123.52 |
| export-large-json-md | 243.20 | 240.54–250.61 | 151.61 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
