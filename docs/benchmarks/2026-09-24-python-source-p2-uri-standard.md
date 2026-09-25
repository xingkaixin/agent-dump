# CLI benchmark: python-source-p2-uri

- Recorded: 2026-09-24T10:25:38.532780+00:00
- Reference checkout: `f3af42a497ebdce43eb72b96c3198d4df390f532`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 145.76 | 142.38–147.20 | 38.88 |
| list-jsonl | 249.42 | 244.72–262.84 | 42.34 |
| list-sqlite | 153.18 | 152.22–159.13 | 40.94 |
| list-all | 257.45 | 252.36–276.74 | 44.05 |
| head-large-jsonl | 148.51 | 147.35–152.02 | 39.30 |
| print-large-jsonl | 249.41 | 245.37–312.65 | 123.53 |
| export-large-json-md | 253.94 | 252.54–256.38 | 151.58 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
