# CLI benchmark: rust-p1

- Recorded: 2026-09-24T06:47:12.362877+00:00
- Reference checkout: `b473f37d3019ce3861d68a3eadc279e3fbfde1e0`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 3.91 | 3.63–4.09 | 2.31 |
| list-jsonl | 42.02 | 41.24–43.29 | 4.08 |
| head-large-jsonl | 6.06 | 5.78–6.53 | 3.47 |
| print-large-jsonl | 88.66 | 87.78–93.74 | 63.14 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 33.66x | -94.0 |
| list-jsonl | 5.40x | -90.3 |
| head-large-jsonl | 21.98x | -91.1 |
| print-large-jsonl | 2.63x | -48.8 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
