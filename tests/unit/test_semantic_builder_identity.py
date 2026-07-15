from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    SemanticErrorCode,
    SemanticValidationError,
)
from wwise_waapi.builders.identity import (  # pyright: ignore[reportMissingImports]
    IdentityAmbiguityError,
    ObjectIdentity,
    ResolutionPlan,
    ResolvedObject,
    resolve_object_identity,
)


def test_explicit_id_identity_is_exact_without_readback() -> None:
    resolved = resolve_object_identity(ObjectIdentity(id="{11111111-1111-1111-1111-111111111111}"), destructive_use=True)

    assert isinstance(resolved, ResolvedObject)
    assert resolved.object == "{11111111-1111-1111-1111-111111111111}"
    assert resolved.resolution == "exact-id"


def test_exact_path_identity_is_exact_without_readback() -> None:
    resolved = resolve_object_identity(ObjectIdentity(path=r"\Actor-Mixer Hierarchy\Default Work Unit\Sound"), destructive_use=True)

    assert isinstance(resolved, ResolvedObject)
    assert resolved.object == r"\Actor-Mixer Hierarchy\Default Work Unit\Sound"
    assert resolved.resolution == "exact-path"


def test_waql_identity_builds_object_get_resolution_plan() -> None:
    planned = resolve_object_identity(ObjectIdentity(waql="from type Sound"))

    assert isinstance(planned, ResolutionPlan)
    assert planned.readback_plan.uri == "ak.wwise.core.object.get"
    assert planned.readback_plan.args == {"waql": "from type Sound"}
    assert planned.readback_plan.options == {"return": ["id", "name", "type", "path", "parent"]}


def test_waql_destructive_use_requires_exactly_one_row() -> None:
    identity = ObjectIdentity(waql="from object \"SomeSound\"")

    with pytest.raises(IdentityAmbiguityError) as missing:
        resolve_object_identity(identity, destructive_use=True)
    assert missing.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY

    resolved = resolve_object_identity(identity, {"return": [{"id": "{sound}", "name": "SomeSound", "type": "Sound"}]}, destructive_use=True)
    assert isinstance(resolved, ResolvedObject)
    assert resolved.object == "{sound}"

    with pytest.raises(IdentityAmbiguityError) as ambiguous:
        resolve_object_identity(identity, [{"id": "{a}"}, {"id": "{b}"}], destructive_use=True)
    assert ambiguous.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY
    assert ambiguous.value.details["row_count"] == 2


def test_name_only_identity_requires_unique_scope() -> None:
    with pytest.raises(IdentityAmbiguityError) as name_only:
        resolve_object_identity(ObjectIdentity(name="Explosion"))
    assert name_only.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY

    scoped = ObjectIdentity(name="Explosion", type="Sound", parent=r"\Actor-Mixer Hierarchy\Default Work Unit")
    planned = resolve_object_identity(scoped)
    assert isinstance(planned, ResolutionPlan)
    assert planned.readback_plan.uri == "ak.wwise.core.object.get"
    assert planned.readback_plan.args == {
        "waql": (
            r'from object "\Actor-Mixer Hierarchy\Default Work Unit" '
            'select children where type = "Sound" and name = "Explosion"'
        )
    }

    resolved = resolve_object_identity(
        scoped,
        [
            {
                "id": "{explosion}",
                "name": "Explosion",
                "type": "Sound",
                "parent": r"\Actor-Mixer Hierarchy\Default Work Unit",
            }
        ],
        destructive_use=True,
    )
    assert isinstance(resolved, ResolvedObject)
    assert resolved.object == "{explosion}"

    with pytest.raises(IdentityAmbiguityError):
        resolve_object_identity(
            scoped,
            [
                {"id": "{a}", "name": "Explosion", "type": "Sound", "parent": r"\Actor-Mixer Hierarchy\Default Work Unit"},
                {"id": "{b}", "name": "Explosion", "type": "Sound", "parent": r"\Actor-Mixer Hierarchy\Default Work Unit"},
            ],
            destructive_use=True,
        )


def test_identity_rejects_conflicting_or_blank_exact_shapes() -> None:
    with pytest.raises(IdentityAmbiguityError) as conflict:
        resolve_object_identity(ObjectIdentity(id="{id}", path=r"\Actor-Mixer Hierarchy\Default Work Unit\Sound"))
    assert conflict.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY
    assert conflict.value.details["shapes"] == ["exact-id", "exact-path"]

    with pytest.raises(IdentityAmbiguityError):
        resolve_object_identity(ObjectIdentity(id=""))


def test_scoped_identity_rejects_multirow_readback_even_with_one_match() -> None:
    scoped = ObjectIdentity(name="Explosion", type="Sound", parent=r"\Actor-Mixer Hierarchy\Default Work Unit")

    with pytest.raises(IdentityAmbiguityError) as exc:
        resolve_object_identity(
            scoped,
            [
                {"id": "{match}", "name": "Explosion", "type": "Sound", "parent": r"\Actor-Mixer Hierarchy\Default Work Unit"},
                {"id": "{other}", "name": "Other", "type": "Sound", "parent": r"\Actor-Mixer Hierarchy\Default Work Unit"},
            ],
            destructive_use=True,
        )

    assert exc.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY
    assert exc.value.details["row_count"] == 2
    assert exc.value.details["matching_row_count"] == 1


def test_scoped_identity_fails_closed_for_unproven_literal_escaping() -> None:
    with pytest.raises(SemanticValidationError, match="embedded quotes") as exc:
        resolve_object_identity(
            ObjectIdentity(
                name='Explosion "quoted"',
                type="Sound",
                parent=r"\Actor-Mixer Hierarchy\Default Work Unit",
            )
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
