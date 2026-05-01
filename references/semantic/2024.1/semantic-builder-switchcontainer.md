# Semantic builder source note: switchcontainer, Wwise 2024.1

- family: `switchcontainer`
- status: `grounded`
- notebook id: `wwise-2024.1-docs`
- version target: `2024.1`
- gate evidence path: `references/semantic/2024.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_switchcontainer_addassignment.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_switchcontainer_getassignments.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_switchcontainer_removeassignment.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_switchcontainer_assignmentadded.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_switchcontainer_assignmentremoved.html

## Endpoint inventory

- `ak.wwise.core.switchContainer.getAssignments`
- `ak.wwise.core.switchContainer.addAssignment`
- `ak.wwise.core.switchContainer.removeAssignment`
- `ak.wwise.core.switchContainer.assignmentAdded`
- `ak.wwise.core.switchContainer.assignmentRemoved`

## Required fields

- `ak.wwise.core.switchContainer.addAssignment: child, stateOrSwitch`
- `ak.wwise.core.switchContainer.getAssignments: id`
- `ak.wwise.core.switchContainer.removeAssignment: child, stateOrSwitch`
- `ak.wwise.core.switchContainer.assignmentAdded: topic payload only`
- `ak.wwise.core.switchContainer.assignmentRemoved: topic payload only`

## Optional fields

- `options.return`
- `topic subscription return fields`

## Return shape

getAssignments returns a return array with child and stateOrSwitch assignment pairs. addAssignment and removeAssignment return empty JSON objects. Topics publish switchContainer, child, and stateOrSwitch objects.

## Destructive behavior

Mutating for assignment changes. removeAssignment unlinks the child from the state or switch.

## Ambiguity constraints

The assigned child must belong to the Switch Container, and the state or switch must belong to the group bound to that Switch Container. addAssignment appends the child to the end of the assignment list for that state.

## Unsupported cases

Do not use import or generic object mutation to build Switch Container assignments when ordering constraints cannot be guaranteed. No profiler, transport, soundengine, UI, CLI, remote, or debug APIs are part of this family.

## Cited required fields

- `ak.wwise.core.switchContainer.addAssignment: child, stateOrSwitch`
- `ak.wwise.core.switchContainer.getAssignments: id`
- `ak.wwise.core.switchContainer.removeAssignment: child, stateOrSwitch`
- `ak.wwise.core.switchContainer.assignmentAdded: topic payload only`
- `ak.wwise.core.switchContainer.assignmentRemoved: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family from the Wwise 2024.1 notebook, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
