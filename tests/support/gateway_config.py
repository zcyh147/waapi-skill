"""Explicit isolated configuration edits for Gateway test fixtures.

This helper never interprets argv or environment connection overrides. Callers
name the persistent fields they intend to configure before starting a lifecycle.
"""
import json
from pathlib import Path


def set_gateway_config(env, **fields):
    path = Path(env["WAAPI_SKILL_CONFIG_PATH"])
    configured = json.loads(path.read_text(encoding="utf-8"))
    configured.update(fields)
    path.write_text(json.dumps(configured), encoding="utf-8")
    return env
