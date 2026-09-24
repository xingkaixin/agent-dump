# CLI benchmark: rust-p2-desktop

- Recorded: 2026-09-24T09:43:22.628702+00:00
- Reference checkout: `a884907ffda3cb849663c67dbac859ca66ec2660`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.57 | 4.43–4.99 | 2.67 |
| list-jsonl | 47.87 | 46.60–50.76 | 5.42 |
| list-sqlite | 9.35 | 8.93–9.92 | 7.92 |
| head-large-jsonl | 7.11 | 6.84–7.69 | 4.19 |
| print-large-jsonl | 45.66 | 44.65–47.47 | 54.67 |
| export-large-json-md | 79.13 | 76.56–80.21 | 55.34 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 31.46x | -93.1 |
| list-jsonl | 5.12x | -87.2 |
| list-sqlite | 15.94x | -80.6 |
| head-large-jsonl | 20.56x | -89.3 |
| print-large-jsonl | 5.52x | -55.7 |
| export-large-json-md | 3.38x | -63.5 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
