# CLI benchmark: python-source-p2-provider-errors

- Recorded: 2026-09-24T10:45:36.338227+00:00
- Reference checkout: `99575b92353f8810d25e8b030e0e6ff3e433c907`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 148.69 | 147.33–154.01 | 38.80 |
| list-jsonl | 245.23 | 240.88–254.79 | 42.30 |
| list-sqlite | 153.80 | 146.95–156.83 | 40.97 |
| list-all | 249.61 | 246.56–270.53 | 43.89 |
| head-large-jsonl | 142.60 | 141.51–146.80 | 39.30 |
| print-large-jsonl | 244.76 | 237.95–254.96 | 123.48 |
| export-large-json-md | 247.53 | 245.05–258.22 | 151.62 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
