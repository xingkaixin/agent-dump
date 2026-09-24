# CLI benchmark: rust-p2-discovery

- Recorded: 2026-09-24T10:06:34.565835+00:00
- Reference checkout: `92bace38fef9f3f32d91d47c720ec30bb4492cf7`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.43 | 4.19–4.96 | 2.69 |
| list-jsonl | 47.24 | 47.17–52.59 | 5.27 |
| list-sqlite | 9.34 | 9.10–9.42 | 8.12 |
| list-all | 50.77 | 50.26–51.20 | 9.41 |
| head-large-jsonl | 6.89 | 6.80–7.07 | 4.22 |
| print-large-jsonl | 45.94 | 45.55–52.59 | 54.69 |
| export-large-json-md | 79.39 | 76.01–82.45 | 53.56 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 31.82x | -93.1 |
| list-jsonl | 5.01x | -87.5 |
| list-sqlite | 15.51x | -80.1 |
| list-all | 4.85x | -78.6 |
| head-large-jsonl | 20.73x | -89.3 |
| print-large-jsonl | 5.29x | -55.8 |
| export-large-json-md | 3.13x | -64.7 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
