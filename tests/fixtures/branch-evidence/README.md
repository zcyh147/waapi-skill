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

`product/metadata-default-r47-*` contains 30 original public metadata program
captures from source candidate `d2abd4293f8391dac6d273a74a033f6269049536`.
Six existing cases per Wwise lane observe 65 exact Console `getPropertyInfo`
default-result obligations across 2021.1–2025.1: presence/absence, the selected
reference occurrence, scalar alternatives, null, empty string and both Boolean
values. The older three lanes reference `waapi_definitions.json`; the newer two
reference `common_definitions.json`. Each original preserves actual public
list/detail selection, exact native/public facts, stale-selection rejection,
all three pytest phase outcomes and 343 whole-file source seals. The portable
projection changes only its program artifact locator. Original argv and paths
remain inert data; these program receipts have no nested reader dependencies.

The reviewed policy requires `program` plus `live_metadata` for every selected
row. On the captured source all 65 program proofs pass; all 65 real metadata
proofs are missing and every row remains implemented but unverified. No native,
Fresh, other-host, descendant or whole-family proof follows. Source changes
must remain stale unless independently justified by the existing exact source
equivalence rules. Original receipts are immutable and are never relabeled as
proof for a successor. The default product ledger remains incomplete.

The default index now selects `product/metadata-default-r47r2-*`, captured after
the missing-metadata-parent reader repair on source candidate
`1d3be0862774691d78a51a5dd1bb7e0f91f9ea87`. Its 30 original nodes again observe
the same 65 facts with the same 343-file dependency membership. The first R47
bundle remains unchanged as original, now-stale evidence; neither its PASS nor
its source seals are rewritten. The new bundle is also program-only evidence.
The reader compatibility fixture that omits or nulls the metadata parent is a
controlled synthetic corruption test and grants no product metadata credit.
