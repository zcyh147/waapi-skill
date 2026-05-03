# Semantic builder source note: switchcontainer, Wwise 2021.1

- family: `switchcontainer`
- status: `grounded`
- notebook id: `wwise-2021.1.14-docs`
- version target: `2021.1`
- gate evidence path: `references/semantic/2021.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_switchcontainer_addassignment.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_switchcontainer_getassignments.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_switchcontainer_removeassignment.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_switchcontainer_assignmentadded.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_switchcontainer_assignmentremoved.html

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

getAssignments returns a return array with child and stateOrSwitch assignment pairs. addAssignment and removeAssignment return empty JSON objects. Topics publish assignment event payloads.

## Destructive behavior

Mutating for assignment changes. addAssignment appends or overrides an assignment and removeAssignment deletes the assignment link for the child and state or switch.

## Ambiguity constraints

The assigned child must belong to a Switch Container, and the state or switch must belong to the Switch Group or State Group bound to that Switch Container. addAssignment adds the child at the end of the list for each state.

## Unsupported cases

Do not use import or generic object mutation to build Switch Container assignments when ordering constraints cannot be guaranteed. No profiler, transport, soundengine, UI, CLI, remote, or debug APIs are part of this family.

## Cited required fields

- `ak.wwise.core.switchContainer.addAssignment: child, stateOrSwitch`
- `ak.wwise.core.switchContainer.getAssignments: id`
- `ak.wwise.core.switchContainer.removeAssignment: child, stateOrSwitch`
- `ak.wwise.core.switchContainer.assignmentAdded: topic payload only`
- `ak.wwise.core.switchContainer.assignmentRemoved: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded 2021.1 details for this family from notebook `wwise-2021.1.14-docs`. Exact full URLs were not directly surfaced in the browser answer, so the URLs above are versioned public-library candidates and exact page ids; they should be treated as source evidence, not behavioral proof.
