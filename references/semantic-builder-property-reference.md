# Semantic builder source note: property-reference

- family: `property-reference`
- status: `grounded`
- notebook id: `wwise-2022.1-docs`
- version target: `2022.1`

## NotebookLM gate evidence

- Evidence path: `references/semantic-builder-notebooklm-gate.md`
- Unlock rule: this note unlocks only when `NotebookLMGate` opens that persisted evidence file for notebook id `wwise-2022.1-docs`.

## Official/source URLs

- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_object_setproperty.html
- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_object_setreference.html
- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_object_setrandomizer.html
- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_object_setattenuationcurve.html
- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_object_getpropertyinfo.html
- `resources/manifest/2022.1/schemas.json`
- NotebookLM notebook `wwise-2022.1-docs`, cited answer for property/reference endpoints.

## Endpoint list

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
- `setProperty`: `object`, `property`, `value`
- `setReference`: `object`, `reference`, `value`
- `setRandomizer`: `object`, `property`, and one of `enabled`, `min`, `max`
- `setAttenuationCurve`: `object`, `curveType`, `use`, `points`

## Optional fields

- `platform` for setting commands.
- `setRandomizer` may include `enabled`, `min`, and `max` together.

## Return shape

Setters return empty JSON objects. `getPropertyInfo` returns property metadata such as type, default, supports, display, dependencies, restrictions, and UI metadata.

## Destructive behavior

Mutating setters overwrite properties, references, randomizers, or attenuation curves. `getPropertyInfo` is read-only.

## Ambiguity constraints

Object names must use `type:name` or `Global:shortId` when strings are used. `getPropertyInfo` requires exactly one identity scope, `object` or `classId`.

## Unsupported cases

`getPropertyInfo` does not read the current property value; use `ak.wwise.core.object.get` for value readback instead.

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
- `ak.wwise.core.object.setRandomizer: object, property, and one of enabled, min, max`
- `ak.wwise.core.object.setAttenuationCurve: object, curveType, use, points`
