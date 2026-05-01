# Semantic builder source note: property-reference, Wwise 2025.1

- family: `property-reference`
- status: `grounded`
- notebook id: `wwise-2025.1-docs`
- version target: `2025.1`
- gate evidence path: `references/semantic/2025.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_gettypes.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_getpropertyandreferencenames.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_getpropertynames.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_getpropertyinfo.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_ispropertyenabled.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_getattenuationcurve.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_setname.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_setnotes.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_setproperty.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_setreference.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_setrandomizer.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_setattenuationcurve.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_islinked.html

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

- `platform for property, reference, randomizer, linked, and attenuation curve endpoints`
- `object or classId when the other identity field is used`
- `property-specific fields reported by getPropertyInfo`
- `return array for propertyChanged and referenceChanged topic subscriptions`

## Return shape

Getters return type metadata, property and reference names, property metadata, enabled status, linked status, or attenuation curve data. Setters return empty JSON objects. propertyChanged publishes object, property, old value, new value, and platform when applicable. referenceChanged publishes object, reference, old reference, new reference, and platform when applicable.

## Destructive behavior

Mutating setters overwrite names, notes, properties, references, randomizers, or attenuation curves. Getter endpoints are read-only. setStateProperties was called out by NotebookLM as destructive because it removes previous state properties, but it is not part of this builder family inventory.

## Ambiguity constraints

Use explicit platform values when touching platform-linked data. getPropertyInfo and getPropertyAndReferenceNames need one identity scope, object or classId. getPropertyInfo describes metadata and does not read the current object value. 2025.1 hierarchy labels use Containers, Busses, Devices, and Property Container.

## Unsupported cases

getPropertyNames is deprecated and replaced by getPropertyAndReferenceNames. Constrained references must not be set without proving the structural setup order. Use object.get to read current property values instead of getPropertyInfo.

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

NotebookLM returned source-grounded required-field details for this family from notebook `wwise-2025.1-docs`, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
