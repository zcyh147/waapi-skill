"""SoundBank semantic builders that prepare WAAPI payloads without dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION  # pyright: ignore[reportMissingImports]

from .common import (  # pyright: ignore[reportMissingImports]
    BuilderContext,
    BuilderFamily,
    ManifestSchemaLoader,
    SemanticEnvelope,
    SemanticErrorCode,
    SemanticPreview,
    SemanticReadbackPlan,
    SemanticValidationError,
    SourceNoteCheck,
    SourceNoteChecker,
)
from .identity import ObjectIdentity, ResolutionPlan, ResolvedObject, resolve_object_identity  # pyright: ignore[reportMissingImports]
from .schema import SemanticSchemaValidator  # pyright: ignore[reportMissingImports]
from .source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]


GET_INCLUSIONS_URI = "ak.wwise.core.soundbank.getInclusions"
SET_INCLUSIONS_URI = "ak.wwise.core.soundbank.setInclusions"
GENERATE_URI = "ak.wwise.core.soundbank.generate"
CONVERT_EXTERNAL_SOURCES_URI = "ak.wwise.core.soundbank.convertExternalSources"
PROCESS_DEFINITION_FILES_URI = "ak.wwise.core.soundbank.processDefinitionFiles"
GENERATED_TOPIC_URI = "ak.wwise.core.soundbank.generated"
GENERATION_DONE_TOPIC_URI = "ak.wwise.core.soundbank.generationDone"

DEFAULT_SOUNDBANK_RETURN_FIELDS = ("id", "name", "type", "path")
SUPPORTED_SET_INCLUSION_OPERATIONS = ("add", "remove", "replace")
SUPPORTED_SET_INCLUSION_FILTERS = ("events", "structures", "media")
SUPPORTED_GENERATE_INCLUSIONS = ("event", "structure", "media")


class SoundBankOperation(str, Enum):
    """Supported SoundBank semantic operations."""

    GET_INCLUSIONS = "getInclusions"
    SET_INCLUSIONS = "setInclusions"
    GENERATE = "generate"
    CONVERT_EXTERNAL_SOURCES = "convertExternalSources"
    PROCESS_DEFINITION_FILES = "processDefinitionFiles"


@dataclass(slots=True, frozen=True)
class SoundBankInclusion:
    """One inclusion row for ``setInclusions``."""

    object: ObjectIdentity | str | int
    filter: Sequence[str]

    def as_inclusion(self) -> dict[str, Any]:
        resolved = _resolve_required_exact(self.object, role="inclusion.object", destructive_use=True)
        return {"object": resolved.object, "filter": _set_inclusion_filter(self.filter)}


@dataclass(slots=True, frozen=True)
class SoundBankGenerateRequest:
    """One optional SoundBank entry inside ``soundbank.generate``."""

    name: str
    events: Sequence[ObjectIdentity | str | int] = ()
    aux_busses: Sequence[ObjectIdentity | str | int] = ()
    inclusions: Sequence[str] = ()
    rebuild: bool | None = None

    def as_generate_request(self) -> dict[str, Any]:
        item: dict[str, Any] = {"name": _non_empty_string("soundbank.name", self.name)}
        if self.events:
            item["events"] = [_resolve_required_exact(value, role="soundbank.events", destructive_use=False).object for value in self.events]
        if self.aux_busses:
            item["auxBusses"] = [_resolve_required_exact(value, role="soundbank.auxBusses", destructive_use=False).object for value in self.aux_busses]
        if self.inclusions:
            item["inclusions"] = _generate_inclusions(self.inclusions)
        if self.rebuild is not None:
            item["rebuild"] = _bool_arg("soundbank.rebuild", self.rebuild)
        return item


@dataclass(slots=True, frozen=True)
class ExternalSourceConversion:
    """One external-source conversion request."""

    input: str | Path
    platform: str
    output: str | Path | None = None

    def as_source(self) -> dict[str, Any]:
        item = {"input": _non_empty_string("source.input", str(self.input)), "platform": _non_empty_string("source.platform", self.platform)}
        if self.output is not None:
            item["output"] = _non_empty_string("source.output", str(self.output))
        return item


@dataclass(slots=True, frozen=True)
class SoundBankTopicExpectation:
    """Evidence-only expectation for SoundBank generation topics."""

    uri: str
    options: Mapping[str, Any]
    expected_soundbank: str | int | None = None
    expected_platform: str | int | None = None
    expected_language: str | int | None = None
    metadata: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload_identity: dict[str, Any] = {}
        if self.expected_soundbank is not None:
            payload_identity["soundbank"] = self.expected_soundbank
        if self.expected_platform is not None:
            payload_identity["platform"] = self.expected_platform
        if self.expected_language is not None:
            payload_identity["language"] = self.expected_language
        return {
            "uri": self.uri,
            "options": dict(self.options),
            "payload_identity": payload_identity,
            "evidence_only": True,
            "hidden_subscription": False,
            "completion_claim": "not-claimed",
            "metadata": dict(self.metadata or {}),
        }


@dataclass(slots=True, frozen=True)
class SoundBankBuilder:
    """Build source-grounded SoundBank previews without calling Wwise."""

    version: str = DEFAULT_WWISE_VERSION
    source_note_checker: SourceNoteChecker | None = None
    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)

    def get_inclusions(self, *, soundbank: ObjectIdentity | str | int) -> SemanticPreview:
        source_note, validator = self._validated_context()
        resolved = _resolve_required_exact(soundbank, role="soundbank", destructive_use=False)
        args = {"soundbank": resolved.object}
        options: dict[str, Any] = {}
        validation = validator.validate(GET_INCLUSIONS_URI, args=args, options=options)
        readback = SemanticReadbackPlan(GET_INCLUSIONS_URI, args=args, options=options, description="read back SoundBank inclusion rows")
        envelope = SemanticEnvelope(
            GET_INCLUSIONS_URI,
            args=args,
            options=options,
            metadata={
                "builder_family": BuilderFamily.SOUNDBANK.value,
                "operation": SoundBankOperation.GET_INCLUSIONS.value,
                "source_note": source_note.as_dict(),
                "schema_validation": validation.as_dict(),
                "read_only": True,
                "identity_resolution": {"soundbank": resolved.as_dict()},
                "return_expectation": {
                    "parser": "parse_soundbank_inclusions_result",
                    "shape": "object-with-inclusions-array",
                    "required_fields": ["inclusions[].object", "inclusions[].filter"],
                },
            },
        )
        return self._preview(envelope, validation_uri=GET_INCLUSIONS_URI, readback_plan=(readback,))

    def set_inclusions(
        self,
        *,
        soundbank: ObjectIdentity | str | int,
        operation: str,
        inclusions: Sequence[SoundBankInclusion | Mapping[str, Any]],
    ) -> SemanticPreview:
        source_note, validator = self._validated_context()
        resolved = _resolve_required_exact(soundbank, role="soundbank", destructive_use=True)
        rows = [_coerce_set_inclusion(item) for item in inclusions]
        if not rows:
            raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "setInclusions requires at least one inclusion row.")
        args = {"soundbank": resolved.object, "operation": _set_inclusion_operation(operation), "inclusions": rows}
        options: dict[str, Any] = {}
        validation = validator.validate(SET_INCLUSIONS_URI, args=args, options=options)
        preflight = SemanticReadbackPlan(GET_INCLUSIONS_URI, args={"soundbank": resolved.object}, options={}, description="preflight getInclusions must capture existing SoundBank inclusions before mutation")
        readback = SemanticReadbackPlan(GET_INCLUSIONS_URI, args={"soundbank": resolved.object}, options={}, description=f"post-{operation} getInclusions readback must verify SoundBank inclusions")
        envelope = SemanticEnvelope(
            SET_INCLUSIONS_URI,
            args=args,
            options=options,
            metadata={
                "builder_family": BuilderFamily.SOUNDBANK.value,
                "operation": SoundBankOperation.SET_INCLUSIONS.value,
                "source_note": source_note.as_dict(),
                "schema_validation": validation.as_dict(),
                "read_only": False,
                "destructive_gate": _destructive_gate(),
                "identity_resolution": {"soundbank": resolved.as_dict()},
                "validated_operation": args["operation"],
                "validated_filters": sorted({filter_value for row in rows for filter_value in row["filter"]}),
                "preflight_plan": preflight.as_dict(),
                "post_mutation_readback_plan": readback.as_dict(),
                "no_op_allowed": False,
            },
        )
        return self._preview(
            envelope,
            validation_uri=SET_INCLUSIONS_URI,
            readback_plan=(preflight, readback),
            requires_destructive_gate=True,
            evidence_extra=(
                {"kind": "preflight", "uri": GET_INCLUSIONS_URI, "must_execute_before": SET_INCLUSIONS_URI},
                {"kind": "readback", "uri": GET_INCLUSIONS_URI, "must_execute_after": SET_INCLUSIONS_URI},
                {"kind": "cleanup-source-immutability", "requires_sandbox": True, "refuse_source_outputs": True},
            ),
        )

    def generate(
        self,
        *,
        soundbanks: Sequence[SoundBankGenerateRequest | Mapping[str, Any]] = (),
        platforms: Sequence[str] = (),
        languages: Sequence[str] = (),
        skip_languages: bool | None = None,
        rebuild_sound_banks: bool | None = None,
        clear_audio_file_cache: bool | None = None,
        write_to_disk: bool | None = None,
        rebuild_init_bank: bool | None = None,
        output_root_hint: str | Path = "sandbox_path/GeneratedSoundBanks",
    ) -> SemanticPreview:
        source_note, validator = self._validated_context()
        args: dict[str, Any] = {}
        if soundbanks:
            args["soundbanks"] = [_coerce_generate_request(item) for item in soundbanks]
        if platforms:
            args["platforms"] = _non_empty_strings("platforms", platforms)
        if languages:
            args["languages"] = _non_empty_strings("languages", languages)
        _set_optional_bool(args, "skipLanguages", skip_languages)
        _set_optional_bool(args, "rebuildSoundBanks", rebuild_sound_banks)
        _set_optional_bool(args, "clearAudioFileCache", clear_audio_file_cache)
        _set_optional_bool(args, "writeToDisk", write_to_disk)
        _set_optional_bool(args, "rebuildInitBank", rebuild_init_bank)
        options: dict[str, Any] = {}
        validation = validator.validate(GENERATE_URI, args=args, options=options)
        artifact_plan = _generate_artifact_plan(args, output_root_hint=output_root_hint)
        readback = SemanticReadbackPlan(GENERATE_URI, args=args, options=options, description="capture SoundBank generation logs without claiming artifact completion")
        envelope = SemanticEnvelope(
            GENERATE_URI,
            args=args,
            options=options,
            metadata={
                "builder_family": BuilderFamily.SOUNDBANK.value,
                "operation": SoundBankOperation.GENERATE.value,
                "source_note": source_note.as_dict(),
                "schema_validation": validation.as_dict(),
                "read_only": False,
                "destructive_gate": _destructive_gate(),
                "artifact_evidence_plan": artifact_plan,
                "topic_expectations": [
                    "generated and generationDone are evidence expectations only",
                    "generationDone is not claimed as proof that all artifacts are complete",
                ],
            },
        )
        return self._preview(
            envelope,
            validation_uri=GENERATE_URI,
            readback_plan=(readback,),
            requires_destructive_gate=True,
            evidence_extra=(
                {"kind": "artifact-evidence", "plan": artifact_plan, "writes_files_by_preview": False},
                {"kind": "topic-evidence", "topics": [GENERATED_TOPIC_URI, GENERATION_DONE_TOPIC_URI], "hidden_subscription": False},
                {"kind": "cleanup-source-immutability", "requires_sandbox": True, "refuse_source_outputs": True},
            ),
        )

    def convert_external_sources(self, sources: Sequence[ExternalSourceConversion | Mapping[str, Any]]) -> SemanticPreview:
        source_note, validator = self._validated_context()
        rows = [_coerce_external_source(item) for item in sources]
        if not rows:
            raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "convertExternalSources requires at least one source row.")
        args = {"sources": rows}
        options: dict[str, Any] = {}
        validation = validator.validate(CONVERT_EXTERNAL_SOURCES_URI, args=args, options=options)
        readback = SemanticReadbackPlan(CONVERT_EXTERNAL_SOURCES_URI, args=args, options=options, description="capture external-source conversion result without filesystem writes by preview")
        envelope = SemanticEnvelope(
            CONVERT_EXTERNAL_SOURCES_URI,
            args=args,
            options=options,
            metadata={
                "builder_family": BuilderFamily.SOUNDBANK.value,
                "operation": SoundBankOperation.CONVERT_EXTERNAL_SOURCES.value,
                "source_note": source_note.as_dict(),
                "schema_validation": validation.as_dict(),
                "read_only": False,
                "destructive_gate": _destructive_gate(),
                "artifact_evidence_plan": {"expected_outputs": [row.get("output", "WwiseProject/.cache/ExternalSources/<platform>") for row in rows], "writes_files_by_preview": False},
            },
        )
        return self._preview(
            envelope,
            validation_uri=CONVERT_EXTERNAL_SOURCES_URI,
            readback_plan=(readback,),
            requires_destructive_gate=True,
            evidence_extra=({"kind": "artifact-evidence", "capture": ["external-source-output"], "writes_files_by_preview": False},),
        )

    def process_definition_files(
        self,
        *,
        files: Sequence[str | Path],
        expected_soundbank_names: Sequence[str] = (),
        process_result_proof: Mapping[str, Any] | None = None,
    ) -> SemanticPreview:
        source_note, validator = self._validated_context()
        file_args = [_non_empty_string("definition_file", str(path)) for path in files]
        if not file_args:
            raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "processDefinitionFiles requires at least one definition file.")
        _reject_bad_process_definition_proof(process_result_proof)
        args = {"files": file_args}
        options: dict[str, Any] = {}
        validation = validator.validate(PROCESS_DEFINITION_FILES_URI, args=args, options=options)
        readback = SemanticReadbackPlan("ak.wwise.core.object.get", args={"waql": "from type SoundBank where name in <definition ShortName values>"}, options={"return": list(DEFAULT_SOUNDBANK_RETURN_FIELDS)}, description="read back SoundBank objects created from definition file ShortName values")
        envelope = SemanticEnvelope(
            PROCESS_DEFINITION_FILES_URI,
            args=args,
            options=options,
            metadata={
                "builder_family": BuilderFamily.SOUNDBANK.value,
                "operation": SoundBankOperation.PROCESS_DEFINITION_FILES.value,
                "source_note": source_note.as_dict(),
                "schema_validation": validation.as_dict(),
                "read_only": False,
                "destructive_gate": _destructive_gate(high_risk=True),
                "risk": "high",
                "proof_policy": "reject call-success-only, empty mapping, and ak.wwise.file_error proof claims; require SoundBank readback tied to definition ShortName",
                "expected_soundbank_names": list(_non_empty_strings("expected_soundbank_names", expected_soundbank_names)) if expected_soundbank_names else [],
            },
        )
        return self._preview(
            envelope,
            validation_uri=PROCESS_DEFINITION_FILES_URI,
            readback_plan=(readback,),
            requires_destructive_gate=True,
            evidence_extra=(
                {"kind": "high-risk-guard", "rejects": ["empty-mapping", "ak.wwise.file_error", "call-success-only"]},
                {"kind": "readback", "uri": "ak.wwise.core.object.get", "must_execute_after": PROCESS_DEFINITION_FILES_URI},
                {"kind": "cleanup-source-immutability", "requires_sandbox": True, "refuse_source_outputs": True},
            ),
        )

    def generated_expectation(
        self,
        *,
        soundbank: ObjectIdentity | str | int | None = None,
        platform: str | int | None = None,
        language: str | int | None = None,
        return_fields: Sequence[str] = DEFAULT_SOUNDBANK_RETURN_FIELDS,
    ) -> SoundBankTopicExpectation:
        return self.topic_expectation(GENERATED_TOPIC_URI, soundbank=soundbank, platform=platform, language=language, return_fields=return_fields)

    def generation_done_expectation(self) -> SoundBankTopicExpectation:
        return self.topic_expectation(GENERATION_DONE_TOPIC_URI)

    def topic_expectation(
        self,
        uri: str,
        *,
        soundbank: ObjectIdentity | str | int | None = None,
        platform: str | int | None = None,
        language: str | int | None = None,
        return_fields: Sequence[str] | None = None,
    ) -> SoundBankTopicExpectation:
        if uri not in {GENERATED_TOPIC_URI, GENERATION_DONE_TOPIC_URI}:
            raise SemanticValidationError(SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED, f"Unsupported SoundBank topic: {uri!r}", details={"uri": uri})
        source_note, validator = self._validated_context()
        options: dict[str, Any] = {}
        if uri == GENERATED_TOPIC_URI and return_fields is not None:
            options["return"] = _return_fields(return_fields)
        elif uri == GENERATION_DONE_TOPIC_URI and return_fields is not None:
            raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "generationDone topic does not support return fields in the reflected schema.")
        validation = validator.validate(uri, args={}, options=options)
        resolved_soundbank = _resolve_required_exact(soundbank, role="soundbank", destructive_use=False).object if soundbank is not None else None
        return SoundBankTopicExpectation(
            uri=uri,
            options=options,
            expected_soundbank=resolved_soundbank,
            expected_platform=platform,
            expected_language=language,
            metadata={
                "builder_family": BuilderFamily.SOUNDBANK.value,
                "source_note": source_note.as_dict(),
                "schema_validation": validation.as_dict(),
                "evidence_policy": "topic payloads are evidence expectations only; no hidden subscription or completion claim",
            },
        )

    def _validated_context(self) -> tuple[SourceNoteCheck, SemanticSchemaValidator]:
        context = BuilderContext(
            BuilderFamily.SOUNDBANK,
            version=self.version,
            source_note_checker=self.source_note_checker or SemanticSourceNoteChecker(),
            manifest_loader=self.manifest_loader,
        )
        context.require_supported_family()
        source_note = context.require_source_note()
        validator = SemanticSchemaValidator(manifest_loader=self.manifest_loader, version=self.version)
        validator.require_supported_version()
        return source_note, validator

    def _preview(
        self,
        envelope: SemanticEnvelope,
        *,
        validation_uri: str,
        readback_plan: tuple[SemanticReadbackPlan, ...] = (),
        requires_destructive_gate: bool = False,
        evidence_extra: tuple[Mapping[str, Any], ...] = (),
    ) -> SemanticPreview:
        return SemanticPreview(
            envelope=envelope,
            source_note_family=BuilderFamily.SOUNDBANK.value,
            version=self.version,
            readback_plan=readback_plan,
            evidence_plan=(
                {"kind": "source-note", "family": BuilderFamily.SOUNDBANK.value, "version": self.version},
                {"kind": "schema", "uri": validation_uri, "version": self.version},
                *evidence_extra,
            ),
            requires_destructive_gate=requires_destructive_gate,
        )


def build_get_inclusions_preview(**kwargs: Any) -> SemanticPreview:
    return SoundBankBuilder(source_note_checker=kwargs.pop("source_note_checker", None)).get_inclusions(**kwargs)


def build_set_inclusions_preview(**kwargs: Any) -> SemanticPreview:
    return SoundBankBuilder(source_note_checker=kwargs.pop("source_note_checker", None)).set_inclusions(**kwargs)


def build_generate_preview(**kwargs: Any) -> SemanticPreview:
    return SoundBankBuilder(source_note_checker=kwargs.pop("source_note_checker", None)).generate(**kwargs)


def build_convert_external_sources_preview(**kwargs: Any) -> SemanticPreview:
    return SoundBankBuilder(source_note_checker=kwargs.pop("source_note_checker", None)).convert_external_sources(**kwargs)


def build_process_definition_files_preview(**kwargs: Any) -> SemanticPreview:
    return SoundBankBuilder(source_note_checker=kwargs.pop("source_note_checker", None)).process_definition_files(**kwargs)


def build_generated_expectation(**kwargs: Any) -> SoundBankTopicExpectation:
    return SoundBankBuilder(source_note_checker=kwargs.pop("source_note_checker", None)).generated_expectation(**kwargs)


def build_generation_done_expectation(**kwargs: Any) -> SoundBankTopicExpectation:
    return SoundBankBuilder(source_note_checker=kwargs.pop("source_note_checker", None)).generation_done_expectation(**kwargs)


def _coerce_set_inclusion(item: SoundBankInclusion | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, SoundBankInclusion):
        return item.as_inclusion()
    if "object" not in item or "filter" not in item:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "Each setInclusions row requires object and filter.")
    resolved = _resolve_required_exact(item["object"], role="inclusion.object", destructive_use=True)
    return {"object": resolved.object, "filter": _set_inclusion_filter(_sequence_arg("filter", item["filter"]))}


def _coerce_generate_request(item: SoundBankGenerateRequest | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, SoundBankGenerateRequest):
        return item.as_generate_request()
    allowed = {"name", "events", "auxBusses", "aux_busses", "inclusions", "rebuild"}
    unknown = tuple(sorted(str(key) for key in item if str(key) not in allowed))
    if unknown:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED, "Unsupported generate SoundBank fields.", details={"unknown_fields": list(unknown)})
    name = _non_empty_string("soundbank.name", item.get("name"))
    result: dict[str, Any] = {"name": name}
    if item.get("events"):
        result["events"] = [_resolve_required_exact(value, role="soundbank.events", destructive_use=False).object for value in _sequence_arg("events", item["events"])]
    aux = item.get("auxBusses", item.get("aux_busses", ()))
    if aux:
        result["auxBusses"] = [_resolve_required_exact(value, role="soundbank.auxBusses", destructive_use=False).object for value in _sequence_arg("auxBusses", aux)]
    if item.get("inclusions"):
        result["inclusions"] = _generate_inclusions(_sequence_arg("inclusions", item["inclusions"]))
    if "rebuild" in item:
        result["rebuild"] = _bool_arg("soundbank.rebuild", item["rebuild"])
    return result


def _coerce_external_source(item: ExternalSourceConversion | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, ExternalSourceConversion):
        return item.as_source()
    allowed = {"input", "platform", "output"}
    unknown = tuple(sorted(str(key) for key in item if str(key) not in allowed))
    if unknown:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED, "Unsupported external source fields.", details={"unknown_fields": list(unknown)})
    result = {"input": _non_empty_string("source.input", item.get("input")), "platform": _non_empty_string("source.platform", item.get("platform"))}
    if "output" in item:
        result["output"] = _non_empty_string("source.output", item["output"])
    return result


def _resolve_required_exact(value: ObjectIdentity | str | int, *, role: str, destructive_use: bool) -> ResolvedObject:
    identity: ObjectIdentity = value if isinstance(value, ObjectIdentity) else ObjectIdentity(id=value)
    resolved = resolve_object_identity(identity, destructive_use=destructive_use)
    if not isinstance(resolved, ResolvedObject):
        plan = cast(ResolutionPlan, resolved)
        raise SemanticValidationError(
            SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY,
            f"SoundBank previews require exact or resolved {role} identity.",
            details={"role": role, "identity": identity.as_dict(), "resolution_plan": plan.as_dict()},
        )
    return resolved


def _set_inclusion_operation(value: str) -> str:
    text = _non_empty_string("operation", value)
    if text not in SUPPORTED_SET_INCLUSION_OPERATIONS:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Unsupported setInclusions operation.",
            details={"operation": text, "supported": list(SUPPORTED_SET_INCLUSION_OPERATIONS)},
        )
    return text


def _set_inclusion_filter(values: Sequence[str]) -> list[str]:
    filters = _non_empty_strings("filter", values)
    if len(set(filters)) != len(filters):
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "setInclusions filters must not contain duplicates.", details={"filter": filters})
    unsupported = tuple(value for value in filters if value not in SUPPORTED_SET_INCLUSION_FILTERS)
    if unsupported:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Unsupported setInclusions filter values.",
            details={"filter": filters, "unsupported": list(unsupported), "supported": list(SUPPORTED_SET_INCLUSION_FILTERS)},
        )
    return filters


def _generate_inclusions(values: Sequence[Any]) -> list[str]:
    inclusions = _non_empty_strings("soundbank.inclusions", values)
    unsupported = tuple(value for value in inclusions if value not in SUPPORTED_GENERATE_INCLUSIONS)
    if unsupported:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Unsupported generate inclusion values.",
            details={"inclusions": inclusions, "unsupported": list(unsupported), "supported": list(SUPPORTED_GENERATE_INCLUSIONS)},
        )
    return inclusions


def _generate_artifact_plan(args: Mapping[str, Any], *, output_root_hint: str | Path) -> dict[str, Any]:
    platform_value = args.get("platforms")
    language_value = args.get("languages")
    soundbank_value = args.get("soundbanks")
    platforms = platform_value if isinstance(platform_value, list) else ["<all-platforms-or-current>"]
    languages = language_value if isinstance(language_value, list) else (["<no-localized-language>"] if args.get("skipLanguages") is True else ["<all-languages>"])
    soundbanks = soundbank_value if isinstance(soundbank_value, list) else [{"name": "<all-soundbanks>"}]
    expected_paths: list[str] = []
    root = str(output_root_hint)
    for platform in platforms:
        for language in languages:
            for soundbank in soundbanks:
                name = soundbank.get("name", "<soundbank>") if isinstance(soundbank, Mapping) else "<soundbank>"
                expected_paths.append(f"{root}/{platform}/{language}/{name}.bnk")
                expected_paths.append(f"{root}/{platform}/{language}/{name}.json")
    return {
        "platform_assumptions": list(platforms),
        "language_assumptions": list(languages),
        "expected_output_artifact_paths": expected_paths,
        "write_to_disk_requested": bool(args.get("writeToDisk")),
        "clear_audio_file_cache_requested": bool(args.get("clearAudioFileCache")),
        "writes_files_by_preview": False,
        "completion_claim": "not-claimed",
    }


def _reject_bad_process_definition_proof(proof: Mapping[str, Any] | None) -> None:
    if proof is None:
        return
    if not proof:
        raise SemanticValidationError(SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED, "empty processDefinitionFiles mapping is not proof.")
    proof_text = str(proof)
    if "ak.wwise.file_error" in proof_text:
        raise SemanticValidationError(SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED, "ak.wwise.file_error is blocker evidence, not processDefinitionFiles proof.")
    if proof == {"call": "success"} or proof.get("status") == "success" and len(proof) == 1:
        raise SemanticValidationError(SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED, "call success alone is not processDefinitionFiles proof.")


def _destructive_gate(*, high_risk: bool = False) -> dict[str, Any]:
    return {"required": True, "env": {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"}, "allow_source_mutation": False, "high_risk": high_risk}


def _set_optional_bool(target: dict[str, Any], key: str, value: bool | None) -> None:
    if value is not None:
        target[key] = _bool_arg(key, value)


def _bool_arg(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, f"{name} must be a boolean.")
    return value


def _return_fields(return_fields: Sequence[str]) -> list[str]:
    return _non_empty_strings("return_fields", return_fields)


def _non_empty_strings(name: str, values: Sequence[Any]) -> list[str]:
    rows = [_non_empty_string(name, value) for value in values]
    if not rows:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, f"{name} must contain at least one non-empty string.")
    return rows


def _sequence_arg(name: str, value: Any) -> Sequence[Any]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, f"{name} must be an array.")
    return value


def _non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, f"{name} must be a non-empty string.")
    return value
