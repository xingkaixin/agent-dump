# CLI benchmark: rust-p2-codex-final

- Recorded: 2026-09-24T07:25:16.354599+00:00
- Reference checkout: `1c037d3a1024460c75a7be6132330835893fb107`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.24 | 4.06–4.51 | 2.52 |
| list-jsonl | 46.51 | 46.09–46.90 | 4.56 |
| head-large-jsonl | 6.65 | 6.16–9.50 | 3.80 |
| print-large-jsonl | 43.92 | 43.03–44.66 | 54.22 |
| export-large-json-md | 84.51 | 77.13–108.72 | 53.08 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 32.76x | -93.5 |
| list-jsonl | 5.25x | -89.2 |
| head-large-jsonl | 21.54x | -90.3 |
| print-large-jsonl | 5.43x | -56.1 |
| export-large-json-md | 2.88x | -65.0 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
