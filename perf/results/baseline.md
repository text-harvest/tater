# Performance run 2026-11-03-89cd836

`python -m perf.run --sizes 500,10000 --schema checkbox,realistic --filled both --spans 2 --out perf/results/` — 5 repeats per action (median), 1 per journey, 21 min.

## checkbox, short documents, empty — N = 10,000

Ratios compare N = 10,000 with N = 500; well above 1× means the cost grows with N.

| action | requests | up KB | down KB | settle ms | long tasks ms | server ms | settle × | up KB × | check | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| page_load | 11.0 | 4,906 | 1,031 | 2,228 | 1,767 | 190 | 6.6× | 19.6× |  | 6 |
| next | 9.0 | 4,905 | 1,031 | 2,301 | 1,941 | 135 | 10.7× | 19.6× |  | 6 |
| tick | 3.0 | 2,582 | 0.3 | 212 | 0.0 | 182 | 3.5× | 19.7× |  | 2 |
| type_notes | 35.0 | 30,946 | 20,606 | 1,970 | 0.0 | 1,981 | 1.8× | 13.1× |  | 9 |
| selector_search | 0.0 | 0.0 | 0.0 | 67.0 | 0.0 | 0.0 | 1.4× |  |  |  |
| annotate_next_20 | 222 | 150,803 | 20,636 | 50,540 | 41,579 | 7,009 | 9.8× | 19.6× |  | 7 |
| jump_selector | 90.0 | 49,076 | 10,318 | 37,672 | 33,456 | 1,536 | 10.7× | 19.4× |  | 5 |
| flag_then_filter | 61.0 | 41,306 | 10,314 | 13,043 | 10,599 | 1,602 | 5.9× | 19.5× |  | 7 |
| reload_resume | 26.0 | 14,983 | 2,064 | 6,490 | 3,482 | 668 | 2.8× | 19.4× | ok | 7 |
| rapid_clicks | 90.0 | 49,082 | 10,320 | 23,259 | 20,471 | 1,559 | 9.1× | 19.4× | ok | 5 |

Flags:

- **page_load**
  - save-status-text.children, save-status-text.c fired 3x
  - timing-store.data, status-store.data, metadata-store.data sent 1291 KB
  - flag-document.checked, document-notes.value sent 1030 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1291 KB
  - timing-store.data sent 1291 KB
  - timing-store.data, status-store.data, metadata-store.data returned 1030 KB
- **next**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1291 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1291 KB
  - flag-document.checked, document-notes.value sent 1030 KB
  - timing-store.data sent 1291 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1030 KB
  - flag-document.checked, document-notes.value sent 1031 KB
- **tick**
  - timing-store.data sent 1291 KB
  - status-store.data, metadata-store.data sent 1291 KB
- **type_notes**
  - metadata-store.data fired 20x
  - timing-store.data fired 9x
  - save-status-text.children, save-status-text.c fired 6x
  - metadata-store.data sent 1031 KB
  - timing-store.data sent 1291 KB
  - metadata-store.data returned 1030 KB
  - save-status-text.children, save-status-text.c fired 7x
  - timing-store.data fired 8x
  - save-status-text.children, save-status-text.c fired 8x
- **annotate_next_20**
  - status-store.data, metadata-store.data sent 1291 KB
  - timing-store.data sent 1291 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1292 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1292 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - metadata-store.data sent 1031 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB
- **jump_selector**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1292 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1292 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - timing-store.data sent 1291 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB
- **flag_then_filter**
  - metadata-store.data sent 1031 KB
  - timing-store.data sent 1291 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1292 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1292 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - metadata-store.data returned 1031 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB
- **reload_resume**
  - status-store.data, metadata-store.data sent 1291 KB
  - timing-store.data sent 1291 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1292 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1292 KB
  - timing-store.data, status-store.data, metadata-store.data returned 1031 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB
- **rapid_clicks**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1292 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1292 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - timing-store.data sent 1292 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB

## checkbox, short documents, filled — N = 10,000

Ratios compare N = 10,000 with N = 500; well above 1× means the cost grows with N.

| action | requests | up KB | down KB | settle ms | long tasks ms | server ms | settle × | up KB × | check | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| page_load | 11.0 | 5,071 | 1,020 | 2,035 | 1,611 | 183 | 6.0× | 19.6× |  | 6 |
| next | 9.0 | 5,070 | 1,020 | 2,452 | 2,186 | 160 | 10.9× | 19.6× |  | 5 |
| tick | 3.0 | 2,700 | 0.4 | 226 | 0.0 | 187 | 4.0× | 19.7× |  | 2 |
| type_notes | 32.0 | 28,490 | 20,381 | 1,932 | 0.0 | 2,179 | 1.8× | 11.8× |  | 11 |
| selector_search | 0.0 | 0.0 | 0.0 | 81.9 | 0.0 | 0.0 | 1.1× |  |  |  |
| annotate_next_20 | 223 | 158,476 | 20,412 | 51,009 | 41,417 | 8,708 | 9.9× | 19.6× |  | 7 |
| jump_selector | 90.0 | 50,726 | 10,206 | 37,915 | 33,363 | 1,902 | 11.3× | 19.4× |  | 5 |
| flag_then_filter | 61.0 | 42,313 | 10,202 | 12,731 | 10,086 | 1,974 | 5.8× | 19.5× |  | 7 |
| reload_resume | 26.0 | 15,547 | 2,042 | 7,174 | 3,585 | 950 | 3.1× | 19.5× | ok | 7 |
| rapid_clicks | 90.0 | 50,731 | 10,208 | 22,926 | 20,180 | 1,831 | 9.4× | 19.4× | ok | 5 |

Flags:

- **page_load**
  - save-status-text.children, save-status-text.c fired 3x
  - timing-store.data, status-store.data, metadata-store.data sent 1350 KB
  - flag-document.checked, document-notes.value sent 1019 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1350 KB
  - timing-store.data sent 1349 KB
  - timing-store.data, status-store.data, metadata-store.data returned 1019 KB
- **next**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1350 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1350 KB
  - flag-document.checked, document-notes.value sent 1019 KB
  - timing-store.data sent 1349 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1019 KB
- **tick**
  - timing-store.data sent 1349 KB
  - status-store.data, metadata-store.data sent 1349 KB
- **type_notes**
  - metadata-store.data fired 20x
  - timing-store.data fired 7x
  - save-status-text.children, save-status-text.c fired 5x
  - metadata-store.data sent 1019 KB
  - timing-store.data sent 1350 KB
  - metadata-store.data returned 1019 KB
  - timing-store.data fired 6x
  - save-status-text.children, save-status-text.c fired 6x
  - timing-store.data fired 8x
  - save-status-text.children, save-status-text.c fired 4x
  - metadata-store.data sent 1020 KB
- **annotate_next_20**
  - status-store.data, metadata-store.data sent 1350 KB
  - timing-store.data sent 1350 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1350 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1350 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - metadata-store.data sent 1019 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB
- **jump_selector**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1351 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1350 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - timing-store.data sent 1350 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB
- **flag_then_filter**
  - metadata-store.data sent 1020 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1350 KB
  - timing-store.data sent 1350 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1350 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - metadata-store.data returned 1019 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB
- **reload_resume**
  - status-store.data, metadata-store.data sent 1350 KB
  - timing-store.data sent 1350 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1350 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1351 KB
  - timing-store.data, status-store.data, metadata-store.data returned 1020 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB
- **rapid_clicks**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 1351 KB
  - timing-store.data, status-store.data, metadata-store.data sent 1351 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - timing-store.data sent 1350 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB

## realistic, short documents, empty — N = 10,000

Ratios compare N = 10,000 with N = 500; well above 1× means the cost grows with N.

| action | requests | up KB | down KB | settle ms | long tasks ms | server ms | settle × | up KB × | check | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| page_load | 12.0 | 9,007 | 1,031 | 2,237 | 1,665 | 230 | 5.5× | 19.7× |  | 7 |
| next | 15.0 | 15,949 | 1,032 | 2,681 | 2,276 | 533 | 8.6× | 19.8× |  | 11 |
| tick | 3.0 | 4,502 | 0.4 | 273 | 66.0 | 243 | 4.3× | 19.8× |  | 2 |
| type_notes | 33.0 | 40,871 | 20,606 | 2,504 | 178 | 3,032 | 2.3× | 12.3× |  | 11 |
| type_text | 41.0 | 90,038 | 5.2 | 4,494 | 1,671 | 10,154 | 4.2× | 19.8× |  | 4 |
| add_span | 3.0 | 4,503 | 0.4 | 293 | 79.0 | 302 | 3.3× | 19.8× |  | 2 |
| selector_search | 0.0 | 0.0 | 0.0 | 74.8 | 0.0 | 0.0 | 1.5× |  |  |  |
| annotate_next_20 | 323 | 410,158 | 20,651 | 60,137 | 47,725 | 16,910 | 8.7× | 19.7× |  | 10 |
| jump_selector | 150 | 159,556 | 10,326 | 44,096 | 37,240 | 5,734 | 11.3× | 19.6× |  | 9 |
| flag_then_filter | 90.0 | 101,350 | 10,319 | 15,290 | 11,603 | 3,880 | 8.5× | 19.6× |  | 11 |
| reload_resume | 32.0 | 33,975 | 2,066 | 7,416 | 4,275 | 1,516 | 3.0× | 19.6× | ok | 10 |
| rapid_clicks | 133 | 148,113 | 10,326 | 28,734 | 22,888 | 5,163 | 0.9× | 22.4× | ok | 9 |

Flags:

- **page_load**
  - save-status-text.children, save-status-text.c fired 3x
  - timing-store.data, status-store.data, metadata-store.data sent 2251 KB
  - flag-document.checked, document-notes.value sent 1030 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 1221 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 2251 KB
  - timing-store.data sent 2251 KB
  - timing-store.data, status-store.data, metadata-store.data returned 1030 KB
- **next**
  - save-status-text.children, save-status-text.c fired 3x
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 2251 KB
  - timing-store.data, status-store.data, metadata-store.data sent 2251 KB
  - flag-document.checked, document-notes.value sent 1030 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 1221 KB
  - {hl-select}.value sent 1220 KB
  - timing-store.data sent 2251 KB
  - {hl-select-relay}.data sent 1220 KB
  - status-store.data, metadata-store.data sent 2251 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1030 KB
  - flag-document.checked, document-notes.value sent 1031 KB
- **tick**
  - timing-store.data sent 2251 KB
  - status-store.data, metadata-store.data sent 2251 KB
- **type_notes**
  - metadata-store.data fired 20x
  - timing-store.data fired 9x
  - save-status-text.children, save-status-text.c fired 4x
  - metadata-store.data sent 1031 KB
  - timing-store.data sent 2251 KB
  - metadata-store.data returned 1030 KB
  - save-status-text.children, save-status-text.c fired 6x
  - timing-store.data fired 11x
  - timing-store.data fired 8x
  - save-status-text.children, save-status-text.c fired 5x
  - timing-store.data fired 7x
- **type_text**
  - timing-store.data fired 20x
  - status-store.data, metadata-store.data fired 20x
  - timing-store.data sent 2251 KB
  - status-store.data, metadata-store.data sent 2251 KB
- **add_span**
  - status-store.data, metadata-store.data sent 2251 KB
  - timing-store.data sent 2251 KB
- **annotate_next_20**
  - status-store.data, metadata-store.data sent 2252 KB
  - timing-store.data sent 2252 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 2252 KB
  - timing-store.data, status-store.data, metadata-store.data sent 2252 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 1221 KB
  - {hl-select}.value sent 1221 KB
  - metadata-store.data sent 1031 KB
  - {hl-select-relay}.data sent 1221 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB
- **jump_selector**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 2252 KB
  - timing-store.data, status-store.data, metadata-store.data sent 2252 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 1221 KB
  - {hl-select}.value sent 1221 KB
  - timing-store.data sent 2252 KB
  - {hl-select-relay}.data sent 1221 KB
  - status-store.data, metadata-store.data sent 2252 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB
- **flag_then_filter**
  - metadata-store.data sent 1031 KB
  - timing-store.data sent 2252 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 2252 KB
  - timing-store.data, status-store.data, metadata-store.data sent 2252 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 1221 KB
  - {hl-select}.value sent 1221 KB
  - {hl-select-relay}.data sent 1221 KB
  - status-store.data, metadata-store.data sent 2252 KB
  - metadata-store.data returned 1031 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB
- **reload_resume**
  - status-store.data, metadata-store.data sent 2252 KB
  - timing-store.data sent 2252 KB
  - timing-store.data, status-store.data, metadata-store.data sent 2252 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 1221 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 2252 KB
  - {hl-select}.value sent 1221 KB
  - {hl-select-relay}.data sent 1221 KB
  - timing-store.data, status-store.data, metadata-store.data returned 1031 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB
- **rapid_clicks**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 2252 KB
  - timing-store.data, status-store.data, metadata-store.data sent 2252 KB
  - flag-document.checked, document-notes.value sent 1031 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 1221 KB
  - {hl-select}.value sent 1221 KB
  - timing-store.data sent 2252 KB
  - {hl-select-relay}.data sent 1221 KB
  - status-store.data, metadata-store.data sent 2252 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1031 KB

## realistic, short documents, filled — N = 10,000

Ratios compare N = 10,000 with N = 500; well above 1× means the cost grows with N.

| action | requests | up KB | down KB | settle ms | long tasks ms | server ms | settle × | up KB × | check | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| page_load | 12.0 | 17,342 | 1,023 | 2,780 | 1,953 | 538 | 6.4× | 19.9× |  | 7 |
| next | 15.0 | 32,641 | 1,022 | 3,971 | 3,231 | 1,421 | 10.5× | 19.9× |  | 11 |
| tick | 3.0 | 8,669 | 0.4 | 646 | 142 | 718 | 8.6× | 19.9× |  | 2 |
| type_notes | 27.0 | 42,065 | 20,384 | 5,337 | 1,118 | 7,569 | 4.9× | 7.8× |  | 8 |
| type_text | 41.0 | 173,385 | 5.3 | 10,394 | 3,222 | 43,028 | 9.5× | 19.9× |  | 4 |
| add_span | 3.0 | 8,670 | 0.4 | 590 | 150 | 664 | 6.1× | 19.9× |  | 2 |
| selector_search | 0.0 | 0.0 | 0.0 | 76.8 | 0.0 | 0.0 | 1.3× |  |  |  |
| annotate_next_20 | 324 | 829,365 | 20,472 | 81,908 | 61,194 | 43,072 | 9.5× | 19.9× |  | 10 |
| jump_selector | 150 | 326,471 | 10,235 | 50,831 | 42,198 | 13,365 | 10.9× | 19.8× |  | 9 |
| flag_then_filter | 87.0 | 195,113 | 10,218 | 19,673 | 15,201 | 11,873 | 9.5× | 20.0× |  | 11 |
| reload_resume | 32.0 | 67,335 | 2,047 | 9,774 | 4,938 | 3,141 | 3.6× | 19.8× | ok | 10 |
| rapid_clicks | 131 | 293,832 | 10,232 | 34,602 | 27,352 | 11,838 | 10.0× | 21.4× | ok | 9 |

Flags:

- **page_load**
  - save-status-text.children, save-status-text.c fired 3x
  - timing-store.data, status-store.data, metadata-store.data sent 4335 KB
  - flag-document.checked, document-notes.value sent 1019 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 3316 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 4335 KB
  - timing-store.data sent 4334 KB
  - timing-store.data, status-store.data, metadata-store.data returned 1019 KB
- **next**
  - save-status-text.children, save-status-text.c fired 3x
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 4335 KB
  - timing-store.data, status-store.data, metadata-store.data sent 4335 KB
  - flag-document.checked, document-notes.value sent 1019 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 3316 KB
  - {hl-select}.value sent 3315 KB
  - timing-store.data sent 4334 KB
  - {hl-select-relay}.data sent 3315 KB
  - status-store.data, metadata-store.data sent 4334 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1019 KB
  - flag-document.checked, document-notes.value sent 1020 KB
- **tick**
  - status-store.data, metadata-store.data sent 4334 KB
  - timing-store.data sent 4334 KB
- **type_notes**
  - metadata-store.data fired 20x
  - timing-store.data fired 4x
  - save-status-text.children, save-status-text.c fired 3x
  - metadata-store.data sent 1020 KB
  - timing-store.data sent 4334 KB
  - metadata-store.data returned 1019 KB
  - timing-store.data fired 5x
  - timing-store.data sent 4335 KB
- **type_text**
  - status-store.data, metadata-store.data fired 20x
  - timing-store.data fired 20x
  - status-store.data, metadata-store.data sent 4335 KB
  - timing-store.data sent 4335 KB
- **add_span**
  - status-store.data, metadata-store.data sent 4335 KB
  - timing-store.data sent 4335 KB
- **annotate_next_20**
  - timing-store.data sent 4335 KB
  - status-store.data, metadata-store.data sent 4335 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 4336 KB
  - timing-store.data, status-store.data, metadata-store.data sent 4336 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 3316 KB
  - {hl-select}.value sent 3316 KB
  - metadata-store.data sent 1020 KB
  - {hl-select-relay}.data sent 3316 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB
- **jump_selector**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 4336 KB
  - timing-store.data, status-store.data, metadata-store.data sent 4336 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 3316 KB
  - {hl-select}.value sent 3316 KB
  - timing-store.data sent 4335 KB
  - {hl-select-relay}.data sent 3316 KB
  - status-store.data, metadata-store.data sent 4335 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB
- **flag_then_filter**
  - metadata-store.data sent 1020 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 4336 KB
  - timing-store.data sent 4335 KB
  - timing-store.data, status-store.data, metadata-store.data sent 4336 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 3316 KB
  - {hl-select}.value sent 3316 KB
  - {hl-select-relay}.data sent 3316 KB
  - status-store.data, metadata-store.data sent 4335 KB
  - metadata-store.data returned 1020 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB
- **reload_resume**
  - status-store.data, metadata-store.data sent 4335 KB
  - timing-store.data sent 4335 KB
  - timing-store.data, status-store.data, metadata-store.data sent 4336 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 3316 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 4336 KB
  - {hl-select}.value sent 3316 KB
  - {hl-select-relay}.data sent 3316 KB
  - timing-store.data, status-store.data, metadata-store.data returned 1020 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB
- **rapid_clicks**
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data sent 4336 KB
  - timing-store.data, status-store.data, metadata-store.data sent 4336 KB
  - flag-document.checked, document-notes.value sent 1020 KB
  - {repeater-store}.data, {repeater-items}.children, {repeater-change}.data, {repeater-ann-relay}.data sent 3316 KB
  - {hl-select}.value sent 3316 KB
  - timing-store.data sent 4336 KB
  - {hl-select-relay}.data sent 3316 KB
  - status-store.data, metadata-store.data sent 4336 KB
  - current-doc-id.data, timing-store.data, metadata-store.data, status-store.data returned 1020 KB

## Server (no browser)

| N | length | schema | filled | startup ms | save ms | file MB | RSS MB | project MB |
|---:|---|---|---|---:|---:|---:|---:|---:|
| 500 | short | checkbox | False | 9.5 | 4.0 | 0.11 | 119 | 1.0 |
| 10,000 | short | checkbox | False | 87.9 | 89.1 | 2.23 | 137 | 16.4 |
| 500 | short | checkbox | True | 11.9 | 5.0 | 0.13 | 119 | 1.2 |
| 10,000 | short | checkbox | True | 116 | 91.5 | 2.52 | 154 | 29.5 |
| 500 | short | realistic | False | 11.7 | 7.4 | 0.18 | 119 | 0.9 |
| 10,000 | short | realistic | False | 104 | 116 | 3.67 | 138 | 17.8 |
| 500 | short | realistic | True | 16.2 | 13.7 | 0.4 | 121 | 2.6 |
| 10,000 | short | realistic | True | 296 | 266 | 7.91 | 201 | 75.0 |

Hosted mode, server memory growth with sessions open:

| N | schema | 1 session MB | 5 sessions MB | 20 sessions MB | per extra session MB |
|---:|---|---:|---:|---:|---:|
| 500 | checkbox | 47.6 | 51.9 | 68.0 | 1.1 |
| 10,000 | checkbox | 67.9 | 155 | 480 | 21.7 |
| 500 | realistic | 48.8 | 58.2 | 94.0 | 2.4 |
| 10,000 | realistic | 93.1 | 281 | 985 | 47.0 |
