# Producer compatibility fixtures

`category-v3.json` preserves JSONL record 121 from the existing macOS host-category evidence store. `metadata/` preserves selected files and the original external seal from the 2021.1 condition metadata capture on e0f2d295. Original results, source-preservation facts, exact argv, and cleanup facts are unchanged. These fixtures test readers only; they grant no new branch, effect, or Fresh coverage. Paths are historical receipt data and are never executed.

`original-sources.json.gz` preserves the exact UTF-8 `scripts/run.py` and
`scripts/gateway.py` bytes from that capture's Git candidate. Their SHA-256
values must match its original plan seal before the tests write an isolated
source context. The historical code is never imported or executed. Positive
reader compatibility uses that context; the changed current Gateway is a
separate stale-equivalence negative. This fixture grants no forward evidence
reuse or product coverage.


`product/move-single-r26-2025.1/` contains four byte-identical originals from the
existing 2025.1 moveSingle public program capture on Git candidate
`3c3423ebf8a0ed8232df4ec7769e7095eb869d2b`. The committed evidence index seals
these originals and the separate `product/move-single-r26-2025.1.bindings.json`
projection. That projection changes only the original program artifact locator;
its hash, exact argv, candidate, source dependencies and assertions are retained.
Historical absolute paths are inert data, never executed or opened by the audit.
The program receipt has no nested artifact descriptors consumed by the reader.

This entry supplies a real partial product mapping, not current proof: original
program evidence is stale against changed relevant sources; native evidence is
absent. No original PASS is regraded or inherited, no equivalence is invented,
and no source seal is narrowed. The relative descriptor and common bundle base
allow default and explicit audit inputs to evaluate without the original
workstation's ignored files. Adding other producer evidence requires reviewing
its full reader artifact closure before a portable attachment is selected.
