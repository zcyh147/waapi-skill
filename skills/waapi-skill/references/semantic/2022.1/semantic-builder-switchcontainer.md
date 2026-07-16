# Semantic builder source note: switchcontainer

- family: `switchcontainer`
- status: `grounded`
- notebook id: `wwise-2022.1-docs`
- version target: `2022.1`

## NotebookLM gate evidence

- Evidence path: `references/semantic/2022.1/semantic-builder-notebooklm-gate.md`
- Unlock rule: this note unlocks only when `NotebookLMGate` opens that persisted evidence file for notebook id `wwise-2022.1-docs`.

## Official/source URLs

- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_switchcontainer_addassignment.html
- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_switchcontainer_getassignments.html
- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_switchcontainer_removeassignment.html
- https://www.audiokinetic.com/en/public-library/2024.1.0_8669/?id=ak_wwise_core_switchcontainer_getassignments_example_getting_the_assignments_of_a_switch_container.html
- `resources/manifest/2022.1/schemas.json`
- NotebookLM notebook `wwise-2022.1-docs`, cited answer for Switch Container assignment endpoints.

## Endpoint list

- `ak.wwise.core.switchContainer.addAssignment`
- `ak.wwise.core.switchContainer.getAssignments`
- `ak.wwise.core.switchContainer.removeAssignment`
- `ak.wwise.core.switchContainer.assignmentAdded`
- `ak.wwise.core.switchContainer.assignmentRemoved`

## Required fields

- `addAssignment`: `child`, `stateOrSwitch`.
- `getAssignments`: `id`.
- `removeAssignment`: `child`, `stateOrSwitch`.
- `assignmentAdded` and `assignmentRemoved`: topic payload only.

## Optional fields

- `options.return`

## Return shape

`addAssignment` and `removeAssignment` return empty JSON objects; `getAssignments` returns a `return` array of child and stateOrSwitch assignment pairs.

## Destructive behavior

Mutating for `addAssignment` and `removeAssignment`. `removeAssignment` deletes the mapping between the child and the state or switch.

## Ambiguity constraints

String identifiers must use `type:name` or `Global:shortId`; the state or switch must belong to the group currently bound to the Switch Container.

## Unsupported cases

No profiler, transport, soundengine, UI, CLI, remote, or debug APIs are part of this family.

## Cited required fields

- `ak.wwise.core.switchContainer.addAssignment: child, stateOrSwitch`
- `ak.wwise.core.switchContainer.getAssignments: id`
- `ak.wwise.core.switchContainer.removeAssignment: child, stateOrSwitch`
- `ak.wwise.core.switchContainer.assignmentAdded: topic payload only`
- `ak.wwise.core.switchContainer.assignmentRemoved: topic payload only`
