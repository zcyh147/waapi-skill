# WAAPI operate lane

Use this reference for project-changing work. The only normal execution path is the packaged transaction CLI. Do not import builders or planners from inline Python, create a helper script, construct a raw WAAPI mutation, or use the generic `call` command for live mutation. Run each reference read and each gateway command as its own shell tool call; never combine a read and gateway invocation with `&&`, `;`, pipes, command substitution, or another multi-command shell string.

## Choose the transaction phase first

An existing transaction continuation outranks the named-operation rule because its immutable preview already seals the request schema, target, value, endpoint, and artifact hash.

- **Existing transaction:** the user confirms, checks, rejects, executes, or verifies an already previewed transaction, and its transaction id is available from the message or conversation. A transaction id is required: an artifact hash alone is not a lookup key and is insufficient for continuation. Ask for the transaction id and stop; do not search transaction files or state directories. With the id, continue as a transaction. The first gateway command is `transaction-show <transaction-id> --summary-only`. Do not call `operations`, `operation-schema`, or `preview` first.
- **New change request:** no transaction exists yet. Run `operation-schema <name>` directly, construct its closed request, and call `preview`. Do not call `operations` first: that command is only for broad capability-inventory questions and returns a compact inventory by default.

The user's current intent authorizes actions; the returned transaction state only constrains which actions are legal and never authorizes an action by itself:

- A status or check request stops after `transaction-show`; report the returned state without calling `confirm`, `execute`, `verify`, or `reject`.
- An explicit rejection may call `reject` after the show and then stops.
- A clear confirmation to execute may continue from `awaiting_confirmation` through `confirm`, `execute`, and `verify`; from `confirmed` through `execute` and `verify`; or from `executed_unverified` through `verify` only.
- An explicit verify-only request may call `verify` only from an applicable executed state; it never calls `execute`.
- Terminal states are reported without another mutation.

Use `operations --detail` only for an explicit audit of every nested request contract. A named unsupported operation must resolve in one offline `operation-schema` call and be reported as the structured boundary; do not probe a second route.

## Closed transaction flow

Derive the absolute Skill directory from the injected absolute `SKILL.md` locator and invoke its absolute `scripts/run.py` path in every actual tool call. The snippets below retain `scripts/run.py` only as readable shorthand; never execute that relative spelling in an automated agent run.

In ordinary agent use, omit `--state-dir` on every gateway command and let the caller or broker inject the transaction store implicitly. Never run `env`, `printenv`, shell expansion, or another environment-inspection command to discover `WAAPI_SKILL_STATE_DIR`; do not read, guess, or search for its value. Pass `--state-dir` only when the user or trusted caller explicitly supplied a trusted absolute path, and then reuse that exact path unchanged. If no implicit store is available, let the gateway return its structured state-directory error or boundary, report it, and stop without probing the environment or filesystem.

For a new transaction:

```bash
python scripts/run.py gateway.py operation-schema <operation-name>
python scripts/run.py gateway.py preview --request-json '<request-v1-json>'
```

The `preview` command performs read-only live identity/metadata preflight, binds the current endpoint/project and packaged runtime, writes an immutable artifact, and returns `awaiting_confirmation`. Summarize the transaction id, full artifact hash, `awaiting_confirmation` state, every requested target/value, pre-state, verification plan, cleanup, expiry, and risks for the user. State explicitly that nothing was executed or changed. Do not execute yet.

On a successful preview, `agent_result` is the compact machine-result projection bound directly to the immutable artifact request. If the user requires a machine-readable result, serialize that object exactly; do not retype or rebuild its request, transaction id, hash, state, or flags.

Only after a later user message clearly confirms that preview, start the continuation by showing the stored transaction, then run the commands allowed by its returned state:

```bash
python scripts/run.py gateway.py transaction-show <transaction-id> --summary-only
python scripts/run.py gateway.py confirm <transaction-id> --artifact-hash <artifact-hash>
python scripts/run.py gateway.py execute <transaction-id>
python scripts/run.py gateway.py verify <transaction-id>
```

Never run `confirm` merely because the original request used an imperative verb. Preview and explicit confirmation are separate turns. If the user changes the target or requested value, reject or abandon the old transaction and create a fresh preview.

## Request v1

`preview` accepts one JSON object and no arbitrary Python kwargs:

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "object.create",
  "arguments": {
    "parent": {"kind": "path", "value": "\\Actor-Mixer Hierarchy\\Default Work Unit\\WAAPI Sandbox"},
    "type": "ActorMixer",
    "name": "New Actor Mixer",
    "notes": "Created through the WAAPI Skill transaction gateway"
  }
}
```

All request levels are closed: unknown fields fail. Identity shapes are exactly:

- `{"kind":"id","value":"{GUID}"}`
- `{"kind":"path","value":"\\Exact\\Wwise\\Path"}`
- `{"kind":"waql","value":"from ..."}`
- `{"kind":"scoped-name","name":"Name","type":"Sound","parent":{"kind":"id","value":"{GUID}"}}`

Never supply identity rows, `property_info`, `reference_info`, schema objects, dispatcher args/options, or a WAAPI URI. The runtime obtains those from live read-only preflight and versioned packaged resources.

If the requested target is not a valid direct writable parent for that object type, do not silently retarget the mutation. Report the structured container-suitability evidence and ask the user to confirm the intended writable child container before creating a new preview.

## Currently executable closed operations

- `object.create`: `parent`, `type`, `name`, optional `notes`; conflict behavior is fixed to `fail`, and source-control auto-add is explicitly disabled across versions.
- `object.delete`: one non-protected `object`; Project roots and default work units are rejected.
- `object.setName`: one `object` and non-empty `value`.
- `object.setNotes`: one `object` and string `value`.
- `object.setProperty`: one `object`, `property`, and `value`; property metadata is queried live. Platform-specific values are not yet accepted.
- `object.setReference`: one source `object`, `reference`, and `target`; reference metadata and both identities are queried live. Platform-specific references and null-reference clearing are not yet accepted.
- `audio.import`: one or more closed import rows containing `object_path` and an absolute regular `audio_file`, plus optional `object_type` and `notes`. The operation is fixed to `createNew`; source-control add/checkout is disabled; target absence, file hash, returned GUID/path/type/notes, live readback, and version-specific result/log shape are verified. `import_language` and `originals_subfolder` remain outside the closed surface until their cross-version artifact readbacks are deterministic.
- `soundbank.setInclusions`: one live `soundbank`, `mode` (`add`, `remove`, or `replace`), and inclusion rows containing one live `object` and unique `filters` from `events`, `structures`, and `media`. `add` upserts the requested object's complete filter row while preserving other objects; it does not union filters with an existing row. `remove` is accepted only when the requested filter row exactly matches live state, then removes that object inclusion. `replace` sets the complete list and may use an empty list for an exact clear. Preview captures the complete normalized state; execution and verification require exact full-state transitions.
- `switchContainer.addAssignment` and `switchContainer.removeAssignment`: one live `switch_container`, direct `child`, and `state_or_switch`. Preview proves the container type, direct-child relation, bound Switch/State Group, group membership, and complete assignment pre-state; verification proves the exact complete assignment post-state, unchanged group reference, and unchanged object relationships. The closed add policy rejects a child that already has any assignment instead of guessing whether reassignment was intended.

Run `operation-schema <name>` directly for a named operation instead of relying on this list. Use compact `operations` only when the user asks for the broad operation inventory; use `operations --detail` only when the entire nested catalog is itself the requested artifact. The catalog reports `object.set`, `object.copy`, `object.move`, `audio.importTabDelimited`, `soundbank.generate`, `soundbank.convertExternalSources`, and `soundbank.processDefinitionFiles` as explicit boundaries until their partial-success, artifact, output-containment, and cleanup verifiers are closed. Do not bridge those gaps with generated code.

### Closed workflow request shapes

Obtain the exact machine-readable nested fields from `operation-schema`; these examples show the intended level of input, not an invitation to add raw WAAPI fields.

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "audio.import",
  "arguments": {
    "imports": [{
      "object_path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\<Sound>Footstep",
      "audio_file": "/absolute/path/Footstep.wav",
      "object_type": "Sound",
      "notes": "Imported through the WAAPI Skill transaction gateway"
    }]
  }
}
```

For Wwise `2025.1`, authored audio lives below `\\Containers`; for `2021.1` through `2024.1`, use `\\Actor-Mixer Hierarchy`. `\\Interactive Music Hierarchy` remains a separate authored-music root. Do not translate one root into another silently.

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "soundbank.setInclusions",
  "arguments": {
    "soundbank": {"kind": "path", "value": "\\SoundBanks\\Default Work Unit\\Main"},
    "mode": "replace",
    "inclusions": [{
      "object": {"kind": "id", "value": "{OBJECT-GUID}"},
      "filters": ["structures", "media"]
    }]
  }
}
```

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "switchContainer.addAssignment",
  "arguments": {
    "switch_container": {"kind": "id", "value": "{CONTAINER-GUID}"},
    "child": {"kind": "id", "value": "{CHILD-GUID}"},
    "state_or_switch": {"kind": "id", "value": "{SWITCH-GUID}"}
  }
}
```

## Invariants enforced by the runtime

- A preview artifact is write-once and SHA-256 bound to confirmation.
- Confirmation accepts a transaction id and the exact stored artifact hash; it does not accept replacement JSON.
- Execution reloads the immutable dispatch, checks preview expiry, verifies the live Wwise version/project/endpoint, verifies the packaged implementation digest, and re-reads every canonical GUID role before mutation.
- A target, project, runtime, or pre-state drift becomes `repreview_required` before any mutation.
- The public generic `call` route cannot execute a mutation, even with `--allow-destructive` or `WWISE_DESTRUCTIVE=1`.
- Once state reaches `executing`, the mutation is never automatically retried. A lost/ambiguous result becomes terminal `indeterminate`.
- Successful dispatch becomes `executed_unverified`; it is not success until `verify` reaches `verified`.
- Verification uses operation-specific readback. A transient read-only verification error returns `verification_deferred`, keeps `executed_unverified`, and permits a later manual `verify`; it never re-executes the mutation.
- The `verify` payload is the terminal authority for the requested mutation because it already contains the operation-specific live readbacks and assertions. After any terminal verification response, stop. Never append `query-object`, generic `call`, or another gateway command to double-check the same result.
- Successful preview and successful `verified` responses expose `agent_result`. For a machine-readable answer, serialize only that exact object without reconstruction or an extra command. Failure, `verification_deferred`, `verification_failed`, `repreview_required`, and `indeterminate` responses do not expose a successful projection; never fabricate one. Natural-language reporting still uses the complete gateway payload and its evidence rather than discarding readback, assertions, risks, or cleanup details.

For `object.create`, verification uses the GUID returned by execution, not a name search. Delete proves GUID absence. Rename proves the same GUID, new name/path, unchanged parent, and old-path absence. Notes are exact. Numeric properties use typed tolerance. References must normalize to the target identity or return an explicit indeterminate boundary.

For `audio.import`, every input file is bound by absolute canonical path, size, and SHA-256 at preview and is re-hashed before execution; every canonical target must remain absent. For Wwise 2023.1 and later, the returned `log`, `files`, and `objects` shape is validated and any error/fatal log is a failed postcondition. Older versions use their reflected `objects` result shape. SoundBank inclusion and Switch assignment operations re-read their complete normalized pre-state immediately before dispatch and require exact post-state evidence.

## Result handling

- `awaiting_confirmation`: show a concise human preview with the transaction id, full artifact hash, every requested target/value, and an explicit statement that execution has not happened; then wait.
- `confirmed`: confirmation was hash-bound; execution has not happened.
- `executed_unverified`: run `verify`, not `execute` again.
- `verified`: report the transaction id, `executed` and `verified` state, every requested target/value, and the actual readback evidence from this payload, then stop without an extra query. Never let a negated or failed execution/verification message sound like completion.
- `verification_failed`: report which assertion failed; do not claim completion or retry mutation.
- `verification_deferred`: a read-only verification attempt failed; a later manual `verify` is safe.
- `repreview_required`: live state changed before execution; create a new preview.
- `indeterminate`: execution may have reached Wwise; never retry automatically. Inspect live state read-only and ask the user how to proceed.
- `unsupported_boundary` / `OPERATION_BOUNDARY`: report the packaged interface gap. Do not write code to bypass it.

For a requested `WAAPI_RESULT_JSON=<json>` answer, when the successful preview or verified payload contains `agent_result`, the `<json>` portion is the compact serialization of that object verbatim in structure and values. Do not copy fields manually; this preserves backslashes, quotes, Unicode, numeric types, and the immutable request binding.

## Planner and XML boundaries

`SemanticPlanner` is a candidate/schema planning resource, not the transaction executor. Do not invoke it as proof that a mutation can execute, and do not use its generic mutation verification steps.

XML editing is not an automatic fallback. Only consider it in a separate, explicit offline project-file task after the user asks for XML editing and a packaged, previewable path exists. For an ordinary Wwise request, return `unsupported_by_skill_interface` instead of editing project files or authoring an XML helper.

Runtime playback scheduling, Game Object View control, timed posting, RTPC ramps, narrative sequencing, unsafe debug calls, and cross-app MCP federation are execution boundaries unless a future packaged operation explicitly closes them.
