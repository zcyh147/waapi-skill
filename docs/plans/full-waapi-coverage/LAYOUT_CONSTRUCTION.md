# Closed layout construction — #188 code batch

The existing `request-schema ak.wwise.ui.layout.setLayout` → layout Draft →
Preview/authorization/execute/verify path now constructs the reflected editor,
floating-window and position-history fields. This is code evidence. Current bounded functional acceptance follows the
2026-10-27 lightweight policy below; no native write PASS is inferred. No raw `args`, `options`, native document,
expression or code input was added.

The exact Authoring request sources are the `ak.wwise.ui.layout.setLayout`
schema and `waapi_ui_definitions.json` graph inside
`skills/waapi-skill/resources/native-catalog/{2024.1,2025.1}/wwise-authoring.json`.
Their builds are 2024.1.13.9056 and 2025.1.7.9143. The corresponding 2021.1,
2022.1 and 2023.1 catalogs contain no layout URI; those source-proven boundaries
remain unchanged. No reflection was collected for this batch.

| Native request definition | Closed business input and Gateway derivation |
| --- | --- |
| `LayoutEntity.Layout`, `Layout.Name`, optional `StackPanel` | Workspace name, optional main `root`, local `nodes`; omitted workspace name uses the separate temporary lookup name. Empty names and an omitted main panel remain distinct. |
| `StackPanel` | `stack` node, label, orientation and ordered child keys; optional width/height and type omission. Gateway generates unique frozen IDs. |
| `View` | `view` node, live view-type choice, selection channel, dimensions and optional type omission. `ViewData` is constructed from bounded typed entries, including nested object/array facts and null; a raw map is rejected. |
| `ObjectPanel` | `object_panel` node, label/dimensions, normal/maximized/minimized editor and bottom-editor state, optional priority/heights/sidebar. |
| `ObjectTabPanel` | `object_tabs` leaf with label/dimensions and generated ID. |
| `EditorPriority`, `EditorId` | Ordered editor identifiers, plug-in identifiers and effect-index strings, preserving repeats and optional `EditorId` type. These serialized preferences grant no live-view identity authority. |
| `PreferredHeights`, `PreferredHeight` | Ordered editor identifiers and height strings, preserving repeats. Gateway owns the required tag and reflected native keys. |
| `SideBar` | Width and collapse-state strings; Gateway owns the exact singular tag. The 2024 scalar `enum` spelling remains visible as a source issue. |
| `Layout.Undocked`, `ViewHolder` | Ordered `floating_windows`, optional stack root per window, closed placement fields; omitted and empty arrays remain distinct. |
| `ViewPosition` | View name plus flags, minimum/maximum coordinates and normal rectangle strings; optional normal/maximized/minimized state. Gateway owns placement keys and the required tag. |
| Eight `Layout` history arrays | `position_history.audio_devices`, `effects`, `fallback`, `last_positions`, `metadata`, `object_types`, `plugin_inner_objects`, `source_plugins`. Omission, explicit empty lists and repeated ordered entries remain selectable. |

All layout/view IDs remain Gateway-generated or live-scoped. A node belongs to
exactly one main/floating tree; shared roots, cycles and disconnected nodes are
rejected. Existing configuration binding, modification policies, immutable
Preview, execute-once and independent requested-state readback remain in place.
The existing constructor byte/result limits remain. Typed data has a disclosed
per-view 8-level/4,096-value limit, plus the shared compiled/readback limits.
Only exact validated layout constructor settings may exceed ordinary business
fact depth; malformed bindings, declaration/binding mismatch and ordinary
settings cannot claim that allowance.

## Source discrepancies, not inferred setter gaps

Both pinned request descriptions say only “Registers a new layout from a JSON
format.” The argument references `LayoutEntity` → `Layout`. Neither contains an
explicit `getLayout` round-trip promise or an additional inheritance rule.

The original retained reads remain at
`.waapi-skill-state/full-coverage/layout-read-{2024,2025}-r1/evidence/catalog/08-contents.agent-result.json`,
indexed by `layout-read-native-summary.json`. They were read, not regenerated or
relabeled as write evidence.

| Discrepancy | Current treatment and remaining question |
| --- | --- |
| `Splitter` requires `@Children` but declares no such property and forbids extras; reads show only `@type`/`ID`. | An unresolved request-definition contradiction, still assigned to #188. The Gateway discloses it and does not invent a child grammar or infer an admitted childless setter from reads. |
| Reads add `ObjectTabPanel.@Children` and `ObjectPanel.SideBarLeft`/`SideBarRight`/`Visibility`; request properties omit them. | Output-only/source discrepancies, not established missing legal setter fields. The reflected tab leaf and singular sidebar are supported; extra setters are not inferred. |
| Preferred-height reads use `EditorUniqueViewId`, `EditorPluginId`, `EditorEffectIndex`; request definition uses unprefixed keys. | Requests use reflected keys. Verification recognizes those three aliases only within actual preferred-height rows, compares every requested value, and rejects conflicts. Arbitrary ViewData is never normalized this way. Alias request legality remains unproved. |
| Capital `Element.OneOf`, 2024 scalar sidebar enum and `ViewHolder.allOf` | Preserved exactly in source. Local closed constructors use the explicit named fields/tags; no global schema rewrite or native-absence claim follows. Native input/effect acceptance is not inferred; further vendor QA is not a current lightweight acceptance requirement. |

## Bounded functional closeout — 2026-10-27

Under the latest SPEC lightweight policy, Main accepts the existing disclosed
bounded Gateway interface as the delivery scope. This is not a claim that the
user individually selected its numeric caps, or that Wwise has these limits.
The named documented inputs and closed choices are wrapped: seven reads and
seven mutations on 2024.1, with close/reset added on 2025.1 (30 URI/version
rows). The matching 2021.1–2023.1 catalogs contain none of these layout URIs;
that fixed-route fact does not establish universal business absence.

The accepted interface retains 32 selected reset entries; 128 constructor
nodes/collection entries; tree depth 14; 112 KiB business/compiled layout bytes;
and per-view typed-data depth 8/4,096 values. Published string, readback and
terminal bounds also remain. These are Gateway capacity limits, not native
capacity limits or unlimited native-input parity. No cap, validator or dispatch
behavior changes for closeout. Larger construction capacity is not a new #188
completion requirement under this accepted bounded scope.

Existing code proof covers the table above, optional/empty/repeated forms,
version/host gates, scoped identity, policies, Preview, drift, one execution and
truthful bounded results. The rootless repair `3a20b0dd` checks every declared
Layout field; `57438a10` recognizes an omitted tag only at the fixed root
StackPanel reference. Component `e26a48f0`/integration `ca06efd8` and their
independent reviews cover the closed constructors. The selected ordinary
witness at `bf607638` separates the independent frontend read; its existing
fake cohort verifies nine transactions, restore/remove and final cleanup
without dispatching `getViewHandle`. No new run is claimed here.

Known preferred-height binding and sidebar/default observations, explicit-empty
history/inactive-position serialization, frontend missing response, arrangement
effects and reset default-state uncertainty remain disclosed. Reset still says
`business_state_verified=false` with result-schema-only strength. The original
R1/R2 FAILs remain FAILs; selected ordinary code proof grants no frontend or
native-effect PASS. Further native construction/window/arrangement/reset QA is
not required. The unsatisfiable pinned Splitter request definition remains an
explicit source boundary; do not invent a grammar or infer native absence.
Output-only tab children, left/right sidebars and prefixed preference aliases
are not newly admitted setter fields.

#189 remains separate. #194 retains the larger-reply Broker/archive boundary
and Fresh budget zero. #195 owns the stable combined Program/Non-live gates
and generated inventory reconciliation. These shared gates and important
CRUD/query input obligations are unchanged; no full-gate or native coverage
count is claimed by this closeout note.
