# CLI benchmark: rust-p2-runtime-sources

- Recorded: 2026-09-24T13:00:46.927839+00:00
- Reference checkout: `a42bbc6712ec8d0f53bbfa63c90782af20ef60c7`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/rust/target/release/agent-dump'`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 7; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| startup-version | 4.66 | 4.27–5.03 | 2.69 |
| list-jsonl | 47.73 | 47.32–48.20 | 5.30 |
| list-sqlite | 9.11 | 9.01–9.64 | 8.03 |
| list-all | 50.94 | 50.75–53.86 | 9.42 |
| head-large-jsonl | 7.02 | 6.69–7.14 | 4.17 |
| print-large-jsonl | 45.42 | 45.10–46.04 | 54.83 |
| export-large-json-md | 77.79 | 75.51–77.95 | 53.67 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 30.39x | -93.1 |
| list-jsonl | 4.99x | -87.5 |
| list-sqlite | 16.20x | -80.4 |
| list-all | 4.85x | -78.5 |
| head-large-jsonl | 20.46x | -89.4 |
| print-large-jsonl | 5.38x | -55.6 |
| export-large-json-md | 3.17x | -64.6 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
