# Semantic builder source note: property-reference, Wwise 2021.1

- family: `property-reference`
- status: `grounded`
- notebook id: `wwise-2021.1.14-docs`
- version target: `2021.1`
- gate evidence path: `references/semantic/2021.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_gettypes.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_getpropertyandreferencenames.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_getpropertyinfo.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_ispropertyenabled.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_getattenuationcurve.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_setname.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_setnotes.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_setproperty.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_setreference.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_setrandomizer.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_setattenuationcurve.html

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

## Optional fields

- `platform for property, reference, randomizer, and attenuation curve endpoints`
- `object or classId when the other identity field is used`
- `property-specific fields reported by getPropertyInfo`

## Return shape

Getters return type metadata, property/reference names, property metadata, enabled status, and attenuation curve data. Setters return empty JSON objects.

## Destructive behavior

Mutating setters overwrite names, notes, properties, references, randomizers, or attenuation curves.

## Ambiguity constraints

Use explicit platform values when touching platform-linked data. getPropertyInfo and getPropertyAndReferenceNames need one identity scope, object or classId.

## Unsupported cases

getPropertyNames and ak.wwise.core.plugin.getProperties are fully deprecated. getPropertyInfo describes metadata and does not read current object values.

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

## Evidence caveat

NotebookLM returned source-grounded 2021.1 details for this family from notebook `wwise-2021.1.14-docs`. Exact full URLs were not directly surfaced in the browser answer, so the URLs above are versioned public-library candidates and exact page ids; they should be treated as source evidence, not behavioral proof.
