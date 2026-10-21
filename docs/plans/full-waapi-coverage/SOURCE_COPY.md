# Exact Synth Source copy and Save observations

These are scoped #180 business observations, separate from generated branch
credit. The public Gateway copied an existing Wwise Synth One Source graph,
using separately authorized destination creation, baseline Save, copy and final
Save transactions. Original native receipts and diagnostic flags remain unchanged.

| Console build | Original candidate | Native terminal | Exact topology |
| --- | --- | --- | --- |
| 2021.1.14.8108 | `6d4a35471bda04f76a4501e3b29a3a19cf5b4132` | PASS, 16.06s | Native-loaded synthetic two-property graph, seven roles, four ordered points |
| 2022.1.19.8584 | `411e8173949020bad26e4302f1e9428a21bcac7d` | PASS, 15.91s | Existing Synth Source, one RTPC, ModulatorLfo, Curve, two ordered points |
| 2023.1.19.8928 | `411e8173949020bad26e4302f1e9428a21bcac7d` | PASS, 17.50s | Same exact version-matched original graph |
| 2024.1.13.9056 | `411e8173949020bad26e4302f1e9428a21bcac7d` | PASS, 16.00s | Same exact version-matched original graph |
| 2025.1.7.9143 | `411e8173949020bad26e4302f1e9428a21bcac7d` | PASS, 16.32s | Same exact version-matched original graph |

All five observations have zero ObjectRefs. Independent collector oracles
compare original and copied GUID mappings, exact typed values, references,
ordered points, notes and saved XML. Modern observations use the same MIDI
destination, one standalone WorkUnit file and independent original-root order
checks. Exact native notes are preserved; CRLF equivalence applies only when
comparing native notes with parsed XML Comments. Each modern Root review checked
1001 archive hashes and four native writes. The 2021 Root review checked 1076
archive files. Source hashes/tree/mtime stayed unchanged, passing sandboxes were
deleted and scoped processes were absent. Eight retained object.get
unknown_object responses per run are distinguished from successful writes.

The raw collector values remain `diagnostic_only=true` and
`business_effect_verified=false`; modern coverage wording remains
`none; exact modern fixture requires native copy/Save oracle`. Root separately
assesses the exact copied/saved effect as supported by the independent oracle
and native writes. This assessment changes no raw verdict, category or flag.

## Original locators and receipt SHA-256s

2021 Root review is
`.waapi-skill-state/full-coverage/r57-repeated-native-root-review.json`.
Its original receipt is in `/tmp/waapi-r57-source-graph/`, beneath
`.waapi-skill-state/full-coverage/r57-repeated-source-6d4a3547-2021-r1/pytest/gateway-workflows-2021-10/state/repeated-source-copy-save-children.json`.
Its exact node is `test_source_copy_repeated_native_donor_saved_graph` in
`tests/destructive/test_gateway_workflow_transaction_matrix.py`. The pinned
native donor bytes and origin are recorded in
`tests/fixtures/source-copy/2021-native-donor.json`.

Modern Root reviews are in `/tmp/waapi-r58-modern-source-collector/`, beneath
`.waapi-skill-state/full-coverage/r58-modern-source-411e8173-YEAR-r1/root-review.json`.
Each locates its original `modern-source-copy-save-children.json`, native packets,
model images and final cleanup evidence. The exact modern node is
`test_modern_source_copy_generated_save_children_console_oracle` in the same
module. Root's aggregate
`.waapi-skill-state/full-coverage/r58-modern-native-root-review.json` is an index
to those originals.

| Version | Original collector receipt SHA-256 |
| --- | --- |
| 2021.1 | `aa3151da06f49425a467e474cf23ce61e52d1401390a8d47098cc85b04524495` |
| 2022.1 | `4175d925f328238ab94a445a0eea5fab7747753e58c184b18b920883bc81c0ca` |
| 2023.1 | `ea546abe76f4069d47a4bf5fa81e6c4037bbc636fcf57175de89804170834036` |
| 2024.1 | `e6d1c439477bf0f84f3dc0ab2fec4d92de6fbbfe271c783eaedf20edfac1a8b1` |
| 2025.1 | `e2b448af5ca6156f5aafed8a48130c8f5d057128b173011147ea4c00dff3966d` |

## Required remaining integration and variants

The existing Topic/metadata import does not map these Source collector contracts
to exact generated branch assertions. #180 still requires a reviewed adapter in
the existing audit/finalizer lane: original collector/native/category locators,
exact per-branch input/observation pointers and native shapes/reference chains,
source/candidate bridges, and portable evidence descriptors. Candidate seams are
`tests/destructive/test_gateway_workflow_transaction_matrix.py` (producer),
`tests/support/exact_evidence_finalization.py` (finalizer), and
`tests/maintenance/branch_audit_completion.py` plus
`tests/maintenance/branch_coverage_audit.py` (admission/index). Extend the existing
contract; never reinterpret diagnostic flags or count a whole URI as covered.

This is required same-parent implementation, not a documentation exception or
completion of #180. No generated Source native-PASS count follows yet. Other
Source classes, sharedObjectRef arrangements, arbitrary repeated topology,
constructors, Voice/media/audio effects, history, Windows and Fresh remain open.
