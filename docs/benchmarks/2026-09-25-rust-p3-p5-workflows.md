# Rust workflow extension eval

Profile: `standard`; 5 measured pairs, 1 warmup pairs.

The original P0 evaluator is unchanged. HTTP timings include a deterministic loopback service, not a real model.

| Case | Python median (ms) | Rust median (ms) | Speedup |
| --- | ---: | ---: | ---: |
| search-incremental-jsonl | 421.13 | 136.98 | 3.07× |
| search-deleted-jsonl | 478.96 | 283.37 | 1.69× |
| search-wal-sqlite | 1454.28 | 460.48 | 3.16× |
| search-four-providers | 708.07 | 359.20 | 1.97× |
| collect-http-local | 259.85 | 73.14 | 3.55× |
| collect-http-20ms | 554.38 | 339.73 | 1.63× |
