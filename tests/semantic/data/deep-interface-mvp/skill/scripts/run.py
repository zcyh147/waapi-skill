#!/usr/bin/env python3
"""Test-only entrypoint for the real #52 business-declaration MVP compiler."""

from __future__ import annotations

from tests.semantic.support.codex_import_mvp_fake_gateway import main


if __name__ == "__main__":
    raise SystemExit(main())
