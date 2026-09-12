# Bare Skill welcome regression — 2026-09-13

## Scope and candidate

- Reproduction: Codex task `01a09660-05cd-7e52-bf54-d59cf482b7b5` received
  only a Skill link, read the Skill, and asked for a request without Gateway
  evidence or a welcome.
- Product fix: `0915c3960e0ae7fa5ad852c22b5e24f9050cdf16` changes only the
  packaged `SKILL.md` introduction section. Bare invocation now calls offline
  `config-show`; a concrete request reuses its first required Gateway result.
  Gateway code, configuration persistence, live connection, authorization,
  mutation, and transaction behavior are unchanged.
- Final semantic candidate: `83a60629f35164795aa0fe890b346a25971b60c8`.
  The later commit changes only test evidence persistence and its regression.
  The packaged Skill is identical to `0915c39`.

## Completed checks

| Lane | Result | Boundary |
| --- | --- | --- |
| Focused welcome/Gateway/matrix regressions | 199 passed | Deterministic tests; no Codex or Wwise |
| Program gate at `0915c39` | 4759 passed, 2 skipped | Fake clients; native-Windows shell and NTFS checks skipped |
| macOS `first_use_2`, root `first-use-20260913-r2` | 2 tasks / 4 turns passed | Fresh memory-off Codex; production offline Gateway; no Wwise |

The focused command selected `test_gateway_session_context.py`,
`test_skill_contract_protocol.py`, `test_codex_first_use.py`, and
`test_codex_skill_matrix.py`. Program used `ci/test.sh --mode program -- -q -ra`.
No full Non-live, live, cross-version, integration, or native-Windows campaign
was run for this narrow first-use change.

## Fresh-task evidence

- Model: `gpt-5.6-terra`, medium reasoning, default service tier.
- Codex CLI: `0.144.3`, explicitly selected `/opt/homebrew/bin/codex`;
  executable and Python hashes are in the sealed run config.
- Isolated configuration: adapter `2024.1`, endpoint
  `ws://127.0.0.1:18765/waapi`; this is configuration, not live Wwise proof.
- Each task started with an empty workspace, one installed Skill, disposable
  HOME/CODEX_HOME, and the existing Harness prompt/environment memory audits.
  No welcome hint or test-only developer instruction was injected.
- `bare-slash`: first user text was exactly `/waapi-skill`; configured policy
  was `ask_before_changes`; thread `01a09676-058f-7d32-9eda-377e0652ae78`.
- `bare-link`: first user text was exactly a Markdown link to that task's
  installed `SKILL.md`; configured policy was `allow_changes`; thread
  `01a09676-6c7d-7fe0-a43c-ffe694236b72`.
- Both initial turns read the Skill once, ran exactly one authenticated
  `config-show`, and printed all introduction facts immediately afterward.
  Manual reading additionally confirmed the current-policy labels and the
  distinction between configured and connected state.
- Each second user turn was `先不操作，等我下一条消息。` in the same thread.
  Both replied with an acknowledgement, issued no command, and did not repeat
  the welcome.
- One-shot macOS LaunchAgent: one run, exit 0, then booted out and its plist
  deleted. Final scoped process check was empty. Wwise was never started.

Evidence is retained under
`skills/waapi-skill-workspace/first-use-20260913-r2/`: prompts, raw
`events.jsonl`, replies, complete Codex audit results, Broker evidence, and
per-turn checks. All 509 files listed in `evidence-manifest.json` passed a
separate SHA-256 verification after completion.

The earlier `first-use-20260913-r1` root had passing in-memory behavior checks
but omitted raw turn persistence. It is frozen diagnostic evidence, not final
acceptance. A failing archive-content regression was added, persistence was
repaired, and both tasks were rerun in the new root. No failed root was
rewritten or replayed. This caller responsibility is recorded in
`tests/semantic/HARNESS_PITFALLS.md`.
