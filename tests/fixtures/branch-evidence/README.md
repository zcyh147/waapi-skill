# Producer compatibility fixtures

`category-v3.json` preserves JSONL record 121 from the existing macOS host-category evidence store. `metadata/` preserves selected files and the original external seal from the 2021.1 condition metadata capture on e0f2d295. Original results, source-preservation facts, exact argv, and cleanup facts are unchanged. These fixtures test readers only; they grant no new branch, effect, or Fresh coverage. Paths are historical receipt data and are never executed.

`original-sources.json.gz` preserves the exact UTF-8 `scripts/run.py` and
`scripts/gateway.py` bytes from that capture's Git candidate. Their SHA-256
values must match its original plan seal before the tests write an isolated
source context. The historical code is never imported or executed. Positive
reader compatibility uses that context; the changed current Gateway is a
separate stale-equivalence negative. This fixture grants no forward evidence
reuse or product coverage.
