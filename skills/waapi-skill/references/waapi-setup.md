# WAAPI setup lane

Use this reference when the request is primarily about connection, version selection, or saved config. The entry file owns the one-time conversation introduction for every lane: emit the Gateway's structured `session_context.one_time_introduction` atomically after the first result, then do not repeat it.

## First connection sequence

1. Run `python scripts/run.py gateway.py status` from the skill directory.
2. The gateway resolves explicit flags, test/runtime environment variables, and then saved config; do not inspect these sources manually first.
3. On success, report the detected live Wwise version, endpoint, project name, and project path requested by the user.
4. On failure, report the JSON `error_code` and `message`. Do not scan ports, inspect processes, search the repository, or treat saved config as live state.

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

The external path is `WAAPI_SKILL_CONFIG_PATH` when explicitly overridden, otherwise `$XDG_CONFIG_HOME/waapi-skill/config.json`, otherwise `$HOME/.config/waapi-skill/config.json`. The override exists for controlled runtimes and tests; normal user config stays outside the installed Skill.

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

## Version selection

- Prefer an explicit user-provided Wwise version when exact API behavior matters; pass it with `--version`.
- Otherwise let the gateway infer the exact supported year-major version from live `ak.wwise.core.getInfo`.
- A mismatch between an explicit/configured version and the connected Wwise instance must fail closed.
- Persist approved `wwise_version`, `waapi_host`, and `waapi_port` with `config-set` so later runs do not depend on conversation memory. Never write `data/config.json`; it is read-only legacy fallback compatibility when no external config exists.

The live host profile is separate from the saved version. The gateway derives
`wwise-console` versus `wwise-authoring-ui` from the same live
`getInfo.isCommandLine` result and does not accept a config field or caller
override for it. Only the five `ak.wwise.ui.commands.*` APIs depend on this
profile; a WwiseConsole connection receives `AUTHORING_HOST_REQUIRED` before
the requested UI operation is dispatched.
The `capabilities` and `describe` commands accept `--profile` only for offline
catalog inspection; it is not saved configuration and cannot override live
host detection.

After the one-time conversation introduction has been shown, do not repeat policy narration in every simple read-only result unless the user asks or the effective setting changes.
