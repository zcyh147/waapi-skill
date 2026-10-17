# WAAPI setup lane

Use this reference when the request is primarily about connection, version selection, or saved config. The entry file owns the one-time conversation introduction for every lane: emit the Gateway's structured `session_context.one_time_introduction` atomically after the first result, then do not repeat it.

## First connection sequence

1. Run `python scripts/run.py gateway.py status` from the skill directory.
2. The gateway reads the selected saved host, port, and expected Wwise version. If incomplete, use `config-show` and `config-set` before retrying. Ordinary commands reject temporary connection flags and ignore connection environment overrides.
3. On success, report the detected live Wwise version, endpoint, project name, and project path requested by the user.
4. On a complete structured failure, report its reason and follow `recovery`: inspect/correct known saved values through `config-show`/`config-set`, then make at most one bounded reconnect when allowed. These task-scoped reads and connection corrections do not need another permission prompt. Service startup must already be authorized by the task. Do not scan unrelated ports/processes, search the repository, or treat saved config as live state.

`status` fails closed if a successful `getInfo`/`getProjectInfo` response is not an object, or if the current Project does not expose a canonical braced GUID `id` plus non-empty `name` and `path`. The same three fields bind every transaction preview to one concrete project; a shape-drifted or identity-free Project response is never treated as a valid guard.

## Config boundary

Inspect and change saved config only through the offline gateway:

```bash
python scripts/run.py gateway.py config-show
python scripts/run.py gateway.py config-set --wwise-version 2022.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes
python scripts/run.py gateway.py config-set --clear-wwise-version --clear-waapi-port
python scripts/run.py gateway.py config-set --reset
```

In an automated agent run, use the absolute `scripts/run.py` locator as required by `SKILL.md`. Do not hand-edit a config file. `config-show` reports the effective values, their source, the external path, and whether the checkout-local legacy fallback was used. `config-set` always writes the complete public config atomically to the external path and never writes the legacy file inside the Skill checkout.

The external path is `WAAPI_SKILL_CONFIG_PATH` when explicitly overridden, otherwise `$XDG_CONFIG_HOME/waapi-skill/config.json`, otherwise `$HOME/.config/waapi-skill/config.json`. Select a distinct absolute config path for an intentionally independent copy or sandbox, then configure it with `config-set`. Copying the Skill directory alone does not isolate user configuration. Normal user config stays outside the installed Skill.

The saved public config fields are exactly:

- `wwise_version`
- `waapi_host`
- `waapi_port`
- `project_modification_policy`

External config fails closed on unknown fields or invalid values. `wwise_version` may be cleared and otherwise must be one of the five supported year-major versions; `waapi_port` may be cleared and otherwise must be in `1..65535`.

The canonical project modification modes are:

- `read_only`: block actual project changes while continuing to allow reads,
  including packaged explicit-confirmation-only read transactions.
- `ask_before_changes`: show the immutable preview and expected result, then wait for a later explicit confirmation.
- `allow_changes`: show a notice, policy-authorize the immutable preview, and continue to one execution plus verification in the same user turn.

The Gateway re-reads this policy before mutation. A policy-authorized
transaction can execute only while the current value is still
`allow_changes`; a downgrade fails closed before dispatch. Existing config
files using `never`, `preview_then_confirm`, or `allow_with_notice` are accepted
as read-only migration aliases and normalized respectively to `read_only`,
`ask_before_changes`, and `allow_changes`. New output and saves use only the
canonical names.

If `config-show` or a normal `config-set` reports that the external JSON is unreadable or invalid, use `config-set --reset`. It replaces that external file with validated defaults, optionally followed by fields supplied in the same command. This is the only recovery route; do not hand-edit or delete the config file. A reset never reads from or writes to the legacy checkout-local config.

Do not describe timeout constants, environment wiring, default `WwiseConsole` paths, scaffold directories, or internal flags as user-facing config unless the user explicitly asks for implementation internals.

Runtime evidence and transaction state are not saved config. When explicitly
provided, `--evidence-dir` / `WWISE_EVIDENCE_DIR` and `--state-dir` /
`WAAPI_SKILL_STATE_DIR` must be absolute paths outside the installed Skill
checkout; `~` and relative paths are rejected instead of being expanded from
ambient process state. A transaction preview additionally rejects state inside
the live Wwise project before creating the state store.

Ordinary transaction commands omit `--state-dir`; users do not need to
configure it. The Gateway resolves state in this order: an explicit
`--state-dir`, `WAAPI_SKILL_STATE_DIR`, `$XDG_STATE_HOME/waapi-skill`, then
`$HOME/.local/state/waapi-skill`. Explicit empty or relative overrides fail
closed rather than falling through to another location.

## Version selection

- Save the user-provided expected version with `config-set --wwise-version`; live operations require a configured version and port.
- Use root `--version` only for offline catalog/schema inspection; it cannot select the connection used by a Draft or live command.
- The Gateway compares live `ak.wwise.core.getInfo` with the configured version and rejects mismatches before business dispatch.
- Persist approved `wwise_version`, `waapi_host`, and `waapi_port` with `config-set` so later runs do not depend on conversation memory. Never write `data/config.json`; it is read-only legacy fallback compatibility when no external config exists.

Drafts persist the selected config path, host, port, and version; their first live step also binds the project GUID and Wwise build. Every continuation compares the selected configuration before proceeding, and live steps recheck project/build. Previews retain the same configuration constraint alongside their existing project/runtime guards. Changed targets and historical state without connection bindings require a new Draft/Preview; the Gateway never silently reuses an old endpoint.

The live host profile is separate from the saved version. The gateway derives
`wwise-console` versus `wwise-authoring-ui` from the same live
`getInfo.isCommandLine` result and does not accept a config field or caller
override for it. The packaged Authoring overlay includes reviewed UI-command,
UI-topic, and versioned core/UI supplements, not a complete Authoring inventory.
Authoring-only requests receive `AUTHORING_HOST_REQUIRED` on WwiseConsole
before the target operation is dispatched. `operations` discloses business
routes across these packaged surfaces without changing the live host.
The `capabilities` and `describe` commands accept `--profile` only for offline
catalog inspection; it is not saved configuration and cannot override live
host detection.

After the one-time conversation introduction has been shown, do not repeat policy narration in every simple read-only result unless the user asks or the effective setting changes.
