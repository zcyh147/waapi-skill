# Semantic builder source note: property-reference, Wwise 2023.1

- family: `property-reference`
- status: `grounded`
- notebook id: `wwise-2023.1-docs`
- version target: `2023.1`
- gate evidence path: `references/semantic/2023.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_gettypes.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_getpropertyandreferencenames.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_getpropertyinfo.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_ispropertyenabled.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_getattenuationcurve.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_setname.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_setnotes.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_setproperty.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_setreference.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_setrandomizer.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_setattenuationcurve.html

## Endpoint inventory

- `ak.wwise.core.object.getTypes`
- `ak.wwise.core.object.getPropertyAndReferenceNames`
- `ak.wwise.core.object.getPropertyInfo`
- `ak.wwise.core.object.isPropertyEnabled`
- `ak.wwise.core.object.getAttenuationCurve`
- `ak.wwise.core.object.setName`
- `ak.wwise.core.object.setNotes`
- `ak.wwise.core.object.setProperty`
- `ak.wwise.core.object.setReference`
- `ak.wwise.core.object.setRandomizer`
- `ak.wwise.core.object.setAttenuationCurve`

## Required fields

- `getTypes`: no required fields.
- `getPropertyAndReferenceNames`: `classId`.
- `getPropertyInfo`: `property` and exactly one of `object` or `classId`.
- `isPropertyEnabled`: `object`, `platform`, `property`.
- `getAttenuationCurve`: `object`, `curveType`.
- `setName`: `object`, `value`.
- `setNotes`: `object`, `value`.
- `setProperty`: `object`, `property`, `value`.
- `setReference`: `object`, `reference`, `value`.
- `setRandomizer`: `object`, `property`, and at least one randomizer field such as `enabled`, `min`, or `max`.
- `setAttenuationCurve`: `object`, `curveType`, `points`, plus curve usage fields required by the endpoint.

## Optional fields

- `platform`
- additional randomizer fields when setting a partial randomizer
- property-specific fields reported by `getPropertyInfo`

## Return shape

Getters return property metadata, enabled status, names, or attenuation curve data. Setters return empty JSON objects.

## Destructive behavior

Mutating setters overwrite names, notes, properties, references, randomizers, or attenuation curves. Getter endpoints are read-only.

## Ambiguity constraints

Use explicit platform values when setting unlinked properties. `getPropertyInfo` needs exactly one identity scope, `object` or `classId`. A null GUID can unlink a reference when the endpoint permits it.

## Unsupported cases

`getPropertyNames` is deprecated and outside this 2023.1 family. `getPropertyInfo` describes metadata and does not read the current object value.

## Cited required fields

- `ak.wwise.core.object.getTypes: no required fields`
- `ak.wwise.core.object.getPropertyAndReferenceNames: classId`
- `ak.wwise.core.object.getPropertyInfo: property and exactly one of object or classId`
- `ak.wwise.core.object.isPropertyEnabled: object, platform, property`
- `ak.wwise.core.object.getAttenuationCurve: object, curveType`
- `ak.wwise.core.object.setName: object, value`
- `ak.wwise.core.object.setNotes: object, value`
- `ak.wwise.core.object.setProperty: object, property, value`
- `ak.wwise.core.object.setReference: object, reference, value`
- `ak.wwise.core.object.setRandomizer: object, property, and at least one randomizer field`
- `ak.wwise.core.object.setAttenuationCurve: object, curveType, points, plus curve usage fields`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
