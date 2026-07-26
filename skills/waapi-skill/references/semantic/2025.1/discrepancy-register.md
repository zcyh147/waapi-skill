# Wwise 2025.1 semantic discrepancy register

Version target: `2025.1`

NotebookLM notebook id: `wwise-2025.1-docs`

## Recorded discrepancies and caveats

- Media Pool text-filter case: the reflected `ak.wwise.core.mediaPool.get` schema describes `contains` as case-sensitive, but a live `2025.1.7.9143` sandbox returned an uppercase-only filename for both lowercase `contains` and ordinary `matchesRegex` candidate filters. The public Skill therefore treats those server predicates as bounded candidate selection when exact case matters and applies the closed `Filename` `containsCaseSensitive` post-filter in packaged Gateway code. Reaching the 200-row raw candidate ceiling is an incomplete boundary, not a complete result.
- Hierarchy naming: NotebookLM confirmed 2025.1 labels `Containers`, `Busses`, `Devices`, and `Property Container`. Do not carry older hierarchy labels into 2025.1 source notes as proof.
- `ak.wwise.core.object.structureChanged`: use this topic as the 2025.1 hierarchy-change proof because it batches hierarchy changes by undo event. Treat granular object topics such as created, preDeleted, postDeleted, childAdded, and childRemoved as legacy compatibility notes.
- `ak.wwise.core.object.getPropertyNames`: NotebookLM reported this endpoint as deprecated and replaced by `ak.wwise.core.object.getPropertyAndReferenceNames`. Do not promote it into the property-reference endpoint inventory.
- `ak.wwise.core.object.set` slot-wrapped list data: 2025.1 list assignment must wrap list entries in inner slot objects, including ArgumentsSlot, MusicArgumentsSlot, EntryPathSlot, MetadataSlot, and PlaylistSlot. Do not pass raw object arrays for these list assignments.
- Profiler and legacy size assumptions: do not assume totalSize, mediaSize, objectSize, or structureSize values are immediately accurate from ordinary queries or topics. NotebookLM states SoundBanks must be generated first for accurate size and metadata values.
- Runtime soundengine endpoints: do not use `ak.soundengine.loadBank` or `ak.soundengine.unloadBank` as authoring semantic-builder proof for the soundbank family.
- URL caveat: NotebookLM confirmed exact public-library URL prefixes and page ids were not present in the notebook answer. The recorded `2025.1.7_6590` URL paths are evidence candidates, while the live manifest build remains `2025.1.7.9143`.
