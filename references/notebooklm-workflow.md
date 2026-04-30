# NotebookLM workflow for Wwise WAAPI docs

This workflow gates any docs-dependent Wwise WAAPI generation. Do not generate API manifests, WAQL notes, schema summaries, or semantic docs unless the gate evidence is open for notebook id `wwise-2022.1-docs`.

## Required commands

Run all commands from `.agents/skills/notebooklm` and always use the wrapper:

```bash
python scripts/run.py auth_manager.py status
python scripts/run.py notebook_manager.py list
python scripts/run.py ask_question.py --question "For Wwise 2022.1 WAAPI, what are ak.wwise.waapi.getFunctions, getTopics, and getSchema used for? Answer briefly from the sources." --notebook-id wwise-2022.1-docs
```

Do not call NotebookLM scripts directly. Do not copy browser state, cookies, `auth_info`, or `.agents/skills/notebooklm/data` into the Wwise skill.

## Notebook lookup

Use `python scripts/run.py notebook_manager.py list` to confirm that the library contains:

```text
ID: wwise-2022.1-docs
```

If the notebook is missing, record gate status `fail-closed` in `.sisyphus/evidence/task-10-notebooklm-gate.md` and stop docs-dependent generation.

## Follow-up questions

NotebookLM answers can be incomplete. If the answer lacks source-grounded details needed for the generation task, ask a follow-up with the same notebook id:

```bash
python scripts/run.py ask_question.py --question "Follow up for Wwise 2022.1 WAAPI: <specific missing detail>. Answer from the sources and keep it brief." --notebook-id wwise-2022.1-docs
```

Record each follow-up command and result in the evidence file before opening the gate.

## Fail-closed behavior

The gate is open only when all of these are true:

- auth result is `success`
- list result is `success`
- query result is `success`
- notebook id is exactly `wwise-2022.1-docs`
- gate status is `open`

If auth, browser startup, notebook list, notebook lookup, or query fails, write the exact failure to the evidence file and set gate status `fail-closed`. Future agents must block docs-dependent generation when evidence is missing, fail-closed, or tied to the wrong notebook id.
