"""Canonical public Draft command taxonomy for semantic test support."""

from __future__ import annotations


DRAFT_GATEWAY_SUBCOMMANDS = frozenset(
    {
        "draft-start",
        "draft-inspect",
        "draft-apply",
        "draft-add-media",
        "draft-bind-field",
        "draft-bind-object",
        "draft-business-configure",
        "draft-declare-import-batch",
        "draft-clear-object-list",
        "draft-declare-existing",
        "draft-declare-field-change",
        "draft-declare-new",
        "draft-declare-object-change",
        "draft-declare-rtpc",
        "draft-declare-switch-assignment",
        "draft-discover-fields",
        "draft-discover-types",
        "draft-remove-declaration",
        "draft-revise-declaration",
        "draft-check",
        "draft-cancel",
        "preview-from-draft",
    }
)

DRAFT_REVISION_SUBCOMMANDS = DRAFT_GATEWAY_SUBCOMMANDS - {
    "draft-start",
    "draft-inspect",
}
