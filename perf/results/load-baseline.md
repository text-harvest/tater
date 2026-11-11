# Load run 2026-11-11 4a55227

`python -m perf.load ` — 120 s per scenario, server unlimited; compared with 512 MB. 28 min.

**Target FAIL** (20 users, 10,000 documents, steady): probe Next p95 338 ms (≤ 500); peak RSS 840 MB (≤ 75% of 512 MB). Memory needs an instance of about 1.5 GB.

Simulated-user rows time the server only: an action's requests, first sent to last answered. `probe:` rows are a real browser's settle time, including clientside work; `probe:type_notes` includes about 1 s of typing (20 characters, 50 ms apart). Memory per session counts from after the first session, which also pays one-time costs; with one user it's that first session's cost.

## 500 documents, 1 users, steady

Server: peak RSS 126 MB, 50.1 MB per session, peak CPU 206% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 1 | 324 | 324 | 324 | 0 |
| category | 7 | 6 | 7 | 7 | 0 |
| reviewed | 7 | 4 | 8 | 8 | 0 |
| notes | 6 | 17 | 40 | 40 | 0 |
| span | 6 | 5 | 7 | 7 | 0 |
| next | 6 | 24 | 35 | 35 | 0 |
| probe:next | 7 | 241 | 562 | 562 | 0 |
| probe:tick | 7 | 59 | 75 | 75 | 0 |
| probe:type_notes | 6 | 1103 | 1114 | 1114 | 0 |

## 500 documents, 5 users, steady

Server: peak RSS 133 MB, 2.1 MB per session, peak CPU 195% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 5 | 103 | 335 | 335 | 0 |
| category | 40 | 4 | 8 | 9 | 0 |
| reviewed | 39 | 4 | 8 | 8 | 0 |
| notes | 37 | 20 | 48 | 65 | 0 |
| span | 37 | 4 | 8 | 12 | 0 |
| next | 36 | 23 | 30 | 43 | 0 |
| probe:next | 7 | 239 | 819 | 819 | 0 |
| probe:tick | 6 | 47 | 63 | 63 | 0 |
| probe:type_notes | 6 | 1102 | 1124 | 1124 | 0 |

## 500 documents, 5 users, burst

Server: peak RSS 133 MB, 2.0 MB per session, peak CPU 199% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 5 | 88 | 342 | 342 | 0 |
| category | 30 | 4 | 8 | 11 | 0 |
| reviewed | 30 | 4 | 8 | 9 | 0 |
| notes | 30 | 19 | 67 | 93 | 0 |
| span | 30 | 4 | 11 | 22 | 0 |
| next | 27 | 79 | 266 | 275 | 0 |
| probe:next | 7 | 235 | 430 | 430 | 0 |
| probe:tick | 6 | 56 | 65 | 65 | 0 |
| probe:type_notes | 6 | 1097 | 1655 | 1655 | 0 |

## 500 documents, 20 users, steady

Server: peak RSS 156 MB, 1.7 MB per session, peak CPU 203% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 20 | 115 | 198 | 360 | 0 |
| category | 158 | 6 | 22 | 99 | 0 |
| reviewed | 154 | 6 | 21 | 41 | 0 |
| notes | 148 | 38 | 106 | 337 | 0 |
| span | 145 | 7 | 20 | 53 | 0 |
| next | 141 | 36 | 133 | 315 | 0 |
| reload | 1 | 52 | 52 | 52 | 0 |
| probe:next | 6 | 274 | 289 | 289 | 0 |
| probe:tick | 5 | 82 | 84 | 84 | 0 |
| probe:type_notes | 5 | 1112 | 1137 | 1137 | 0 |

## 500 documents, 20 users, burst

Server: peak RSS 159 MB, 1.7 MB per session, peak CPU 231% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 20 | 133 | 253 | 631 | 0 |
| category | 100 | 5 | 9 | 54 | 0 |
| reviewed | 100 | 5 | 9 | 47 | 0 |
| notes | 97 | 24 | 98 | 318 | 0 |
| span | 93 | 5 | 29 | 83 | 0 |
| next | 90 | 321 | 390 | 398 | 0 |
| probe:next | 6 | 251 | 288 | 288 | 0 |
| probe:tick | 5 | 52 | 107 | 107 | 0 |
| probe:type_notes | 5 | 1109 | 1224 | 1224 | 0 |

## 10,000 documents, 1 users, steady

Server: peak RSS 206 MB, 98.1 MB per session, peak CPU 230% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 1 | 784 | 784 | 784 | 0 |
| category | 7 | 3 | 7 | 7 | 0 |
| reviewed | 7 | 7 | 7 | 7 | 0 |
| notes | 6 | 20 | 43 | 43 | 0 |
| span | 6 | 7 | 9 | 9 | 0 |
| next | 6 | 25 | 28 | 28 | 0 |
| probe:next | 7 | 285 | 451 | 451 | 0 |
| probe:tick | 6 | 67 | 99 | 99 | 0 |
| probe:type_notes | 6 | 1120 | 1128 | 1128 | 0 |

## 10,000 documents, 5 users, steady

Server: peak RSS 354 MB, 38.0 MB per session, peak CPU 230% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 5 | 381 | 586 | 586 | 0 |
| category | 39 | 6 | 81 | 112 | 0 |
| reviewed | 38 | 5 | 22 | 90 | 0 |
| notes | 37 | 26 | 90 | 175 | 0 |
| span | 37 | 5 | 22 | 23 | 0 |
| next | 36 | 42 | 110 | 121 | 0 |
| probe:next | 7 | 312 | 767 | 767 | 0 |
| probe:tick | 6 | 66 | 78 | 78 | 0 |
| probe:type_notes | 6 | 1127 | 1599 | 1599 | 0 |

## 10,000 documents, 5 users, burst

Server: peak RSS 363 MB, 41.7 MB per session, peak CPU 226% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 5 | 765 | 1080 | 1080 | 0 |
| category | 30 | 5 | 34 | 40 | 0 |
| reviewed | 30 | 6 | 25 | 30 | 0 |
| notes | 30 | 22 | 129 | 220 | 0 |
| span | 29 | 4 | 20 | 32 | 0 |
| next | 27 | 84 | 378 | 386 | 0 |
| probe:next | 6 | 284 | 886 | 886 | 0 |
| probe:tick | 6 | 56 | 83 | 83 | 0 |
| probe:type_notes | 6 | 1121 | 1634 | 1634 | 0 |

## 10,000 documents, 20 users, steady

Server: peak RSS 840 MB, 33.4 MB per session, peak CPU 232% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 20 | 310 | 612 | 680 | 0 |
| category | 158 | 4 | 10 | 369 | 0 |
| reviewed | 154 | 4 | 9 | 86 | 0 |
| notes | 147 | 21 | 79 | 704 | 0 |
| span | 145 | 4 | 8 | 328 | 0 |
| next | 141 | 25 | 57 | 566 | 0 |
| reload | 1 | 64 | 64 | 64 | 0 |
| probe:next | 6 | 294 | 338 | 338 | 0 |
| probe:tick | 5 | 60 | 70 | 70 | 0 |
| probe:type_notes | 5 | 1123 | 1642 | 1642 | 0 |

## 10,000 documents, 20 users, burst

Server: peak RSS 815 MB, 32.3 MB per session, peak CPU 230% (100% = one core).

| action | count | p50_ms | p95_ms | max_ms | errors |
|---|---:|---:|---:|---:|---:|
| start | 20 | 306 | 603 | 714 | 0 |
| category | 100 | 4 | 12 | 142 | 0 |
| reviewed | 100 | 4 | 17 | 233 | 0 |
| notes | 97 | 21 | 80 | 259 | 0 |
| span | 93 | 4 | 8 | 108 | 0 |
| next | 90 | 283 | 326 | 342 | 0 |
| probe:next | 6 | 276 | 440 | 440 | 0 |
| probe:tick | 5 | 61 | 76 | 76 | 0 |
| probe:type_notes | 5 | 1105 | 1150 | 1150 | 0 |

### Session start, 500 documents

- 1 at once: start p50 387 ms, max 387 ms; RSS +50 MB after, peak +50 MB during; errors 0
- 5 at once: start p50 319 ms, max 333 ms; RSS +11 MB after, peak +11 MB during; errors 0

### Session limit (cache of 3, 5 users 10 s apart, users 2 and 3 idle after starting), 500 documents

- user 0: no errors
- user 1: no errors
- user 2 (idle): no errors
- user 3 (idle): no errors
- user 4: no errors

Working users dropped: none.

Memory: 72 MB at start, 130 MB with 3 sessions after the run, 131 MB once 3 new sessions had replaced them.


### Session start, 10,000 documents

- 1 at once: start p50 651 ms, max 651 ms; RSS +98 MB after, peak +98 MB during; errors 0
- 5 at once: start p50 1665 ms, max 1715 ms; RSS +224 MB after, peak +224 MB during; errors 0

### Session limit (cache of 3, 5 users 10 s apart, users 2 and 3 idle after starting), 10,000 documents

- user 0: no errors
- user 1: no errors
- user 2 (idle): no errors
- user 3 (idle): no errors
- user 4: no errors

Working users dropped: none.

Memory: 72 MB at start, 288 MB with 3 sessions after the run, 302 MB once 3 new sessions had replaced them.


