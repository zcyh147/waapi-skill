# Semantic builder source note: property-reference, Wwise 2024.1

- family: `property-reference`
- status: `grounded`
- notebook id: `wwise-2024.1-docs`
- version target: `2024.1`
- gate evidence path: `references/semantic/2024.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_gettypes.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_getpropertyandreferencenames.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_getpropertyinfo.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_ispropertyenabled.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_getattenuationcurve.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_setname.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_setnotes.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_setproperty.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_setreference.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_setrandomizer.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_setattenuationcurve.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_islinked.html

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
- `ak.wwise.core.object.isLinked`

## Required fields

- `ak.wwise.core.object.getTypes: no required fields`
- `ak.wwise.core.object.getPropertyAndReferenceNames: exactly one of object or classId`
- `ak.wwise.core.object.getPropertyInfo: property and exactly one of object or classId`
- `ak.wwise.core.object.isPropertyEnabled: object, platform, property`
- `ak.wwise.core.object.getAttenuationCurve: object, curveType`
- `ak.wwise.core.object.setName: object, value`
- `ak.wwise.core.object.setNotes: object, value`
- `ak.wwise.core.object.setProperty: object, property, value`
- `ak.wwise.core.object.setReference: object, reference, value`
- `ak.wwise.core.object.setRandomizer: object, property, and at least one of enabled, min, or max`
- `ak.wwise.core.object.setAttenuationCurve: object, curveType, use, points`
- `ak.wwise.core.object.isLinked: object, property, platform`

## Optional fields

- `platform for property, reference, randomizer, and attenuation curve endpoints`
- `object or classId when the other identity field is used`
- `property-specific fields reported by getPropertyInfo`

## Return shape

Getters return type metadata, property and reference names, property metadata, enabled status, linked status, or attenuation curve data. Setters return empty JSON objects.

## Destructive behavior

Mutating setters overwrite names, notes, properties, references, randomizers, or attenuation curves. Getter endpoints are read-only.

## Ambiguity constraints

Use explicit platform values when touching platform-linked data. getPropertyInfo and getPropertyAndReferenceNames need one identity scope, object or classId. getPropertyInfo describes metadata and does not read the current object value.

## Unsupported cases

Constrained references must not be set without proving the structural setup order. Use object.get to read current property values instead of getPropertyInfo.

## Cited required fields

- `ak.wwise.core.object.getTypes: no required fields`
- `ak.wwise.core.object.getPropertyAndReferenceNames: exactly one of object or classId`
- `ak.wwise.core.object.getPropertyInfo: property and exactly one of object or classId`
- `ak.wwise.core.object.isPropertyEnabled: object, platform, property`
- `ak.wwise.core.object.getAttenuationCurve: object, curveType`
- `ak.wwise.core.object.setName: object, value`
- `ak.wwise.core.object.setNotes: object, value`
- `ak.wwise.core.object.setProperty: object, property, value`
- `ak.wwise.core.object.setReference: object, reference, value`
- `ak.wwise.core.object.setRandomizer: object, property, and at least one of enabled, min, or max`
- `ak.wwise.core.object.setAttenuationCurve: object, curveType, use, points`
- `ak.wwise.core.object.isLinked: object, property, platform`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family from the Wwise 2024.1 notebook, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
