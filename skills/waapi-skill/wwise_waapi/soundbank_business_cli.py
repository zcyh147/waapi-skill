"""Compact CLI envelope for complete SoundBank business plans."""

from __future__ import annotations

import argparse
from typing import Any, Sequence


class SoundBankBusinessCliError(ValueError):
    """The public plan flags do not form one closed operation declaration."""


def add_soundbank_plan_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach the shared high-level plan flags to one Gateway subcommand."""

    parser.add_argument("--mode", choices=("add", "remove", "replace"))
    parser.add_argument("--soundbank-handle")
    parser.add_argument(
        "--inclusion",
        action="append",
        nargs="+",
        default=[],
        metavar="OBJECT_HANDLE_OR_FILTER",
    )
    parser.add_argument(
        "--soundbank",
        action="append",
        nargs=2,
        default=[],
        metavar=("SOUNDBANK_HANDLE", "ARTIFACT_EXPECTATION"),
    )
    parser.add_argument(
        "--event",
        action="append",
        nargs=2,
        default=[],
        metavar=("SOUNDBANK_HANDLE", "EVENT_HANDLE"),
    )
    parser.add_argument(
        "--aux-bus",
        action="append",
        nargs=2,
        default=[],
        metavar=("SOUNDBANK_HANDLE", "AUX_BUS_HANDLE"),
    )
    parser.add_argument(
        "--generation-inclusion",
        action="append",
        nargs="+",
        default=[],
        metavar="SOUNDBANK_HANDLE_OR_FILTER",
    )
    parser.add_argument(
        "--soundbank-rebuild",
        action="append",
        nargs=2,
        default=[],
        metavar=("SOUNDBANK_HANDLE", "TRUE_OR_FALSE"),
    )
    parser.add_argument("--platform", action="append", default=[])
    parser.add_argument("--temporary-soundbank", action="append", nargs=2, default=[],
                        metavar=("NAME", "ARTIFACT_EXPECTATION"))
    parser.add_argument("--all-user-soundbanks", choices=("nonlocalized", "localized", "mixed"))
    parser.add_argument("--all-user-bank-expectation", action="append", nargs=2, default=[],
                        metavar=("SOUNDBANK_HANDLE", "ARTIFACT_EXPECTATION"))
    for flag in ("empty-events", "empty-aux-busses", "empty-generation-inclusions"):
        parser.add_argument(f"--{flag}", action="append", default=[], metavar="BANK_SELECTION")
    parser.add_argument("--language", action="append", default=[])
    parser.add_argument("--all-languages", action="store_true", default=None)
    for flag in (
        "rebuild-soundbanks",
        "clear-audio-file-cache",
        "rebuild-init-bank",
    ):
        parser.add_argument(
            f"--{flag}",
            choices=("true", "false"),
        )
    for flag in ("write-to-disk", "skip-languages"):
        parser.add_argument(f"--{flag}", choices=("true", "false", "native-default"))
    parser.add_argument(
        "--source",
        action="append",
        nargs="+",
        default=[],
        metavar="INPUT_PLATFORM_OPTIONAL_OUTPUT",
    )
    parser.add_argument("--definition-file", action="append", default=[])
    parser.add_argument("--io-root")


def soundbank_plan_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
) -> dict[str, Any]:
    """Build one complete high-level plan from operation-specific CLI facts."""

    field_names = {
        "mode",
        "soundbank_handle",
        "inclusion",
        "soundbank",
        "temporary_soundbank",
        "all_user_soundbanks",
        "all_user_bank_expectation",
        "empty_events",
        "empty_aux_busses",
        "empty_generation_inclusions",
        "all_languages",
        "write_to_disk",
        "skip_languages",
        "event",
        "aux_bus",
        "generation_inclusion",
        "soundbank_rebuild",
        "platform",
        "language",
        "rebuild_soundbanks",
        "clear_audio_file_cache",
        "rebuild_init_bank",
        "source",
        "definition_file",
        "io_root",
    }
    allowed = {
        "soundbank.setInclusions": {
            "mode",
            "soundbank_handle",
            "inclusion",
        },
        "soundbank.generate": {
            "all_user_bank_expectation",
            "empty_events",
            "empty_aux_busses",
            "empty_generation_inclusions",
            "all_languages",
            "temporary_soundbank",
            "all_user_soundbanks",
            "write_to_disk",
            "skip_languages",
            "soundbank",
            "event",
            "aux_bus",
            "generation_inclusion",
            "soundbank_rebuild",
            "platform",
            "language",
            "rebuild_soundbanks",
            "clear_audio_file_cache",
            "rebuild_init_bank",
            "io_root",
        },
        "soundbank.convertExternalSources": {"source", "io_root"},
        "soundbank.processDefinitionFiles": {"definition_file", "io_root"},
    }.get(operation)
    if allowed is None:
        raise SoundBankBusinessCliError("unsupported SoundBank plan operation")

    def supplied(name: str) -> bool:
        value = getattr(args, name)
        return value is not None and value != []

    unexpected = sorted(
        name for name in field_names - allowed if supplied(name)
    )
    if unexpected:
        raise SoundBankBusinessCliError(
            f"{operation} does not accept {unexpected[0].replace('_', '-')}"
        )
    if operation == "soundbank.setInclusions":
        grouped: dict[str, list[str]] = {}
        order: list[str] = []
        for group in args.inclusion:
            if len(group) < 2:
                raise SoundBankBusinessCliError(
                    "one SoundBank inclusion requires at least one filter"
                )
            handle, *filter_names = group
            if handle not in grouped:
                grouped[handle] = []
                order.append(handle)
            for filter_name in filter_names:
                if filter_name in grouped[handle]:
                    raise SoundBankBusinessCliError(
                        "one SoundBank inclusion filter was supplied twice"
                    )
                grouped[handle].append(filter_name)
        return {
            "soundbank_handle": args.soundbank_handle,
            "mode": args.mode,
            "inclusions": [
                {"object_handle": handle, "filters": grouped[handle]}
                for handle in order
            ],
        }
    if operation == "soundbank.generate":
        rows: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for handle, expectation in args.soundbank:
            if handle in rows:
                raise SoundBankBusinessCliError(
                    "one generated SoundBank handle was supplied twice"
                )
            rows[handle] = {
                "soundbank_handle": handle,
                "artifact_expectation": expectation,
            }
            order.append(handle)
        for name, expectation in args.temporary_soundbank:
            if name in rows:
                raise SoundBankBusinessCliError("one generated SoundBank selection was supplied twice")
            rows[name] = {"name": name, "artifact_expectation": expectation}
            order.append(name)

        def append_for_bank(
            pairs: Sequence[Sequence[str]],
            field: str,
        ) -> None:
            for bank_handle, value in pairs:
                if bank_handle not in rows:
                    raise SoundBankBusinessCliError(
                        f"{field} references an undeclared SoundBank handle"
                    )
                rows[bank_handle].setdefault(field, []).append(value)

        append_for_bank(args.event, "event_handles")
        append_for_bank(args.aux_bus, "aux_bus_handles")
        for group in args.generation_inclusion:
            if len(group) < 2:
                raise SoundBankBusinessCliError(
                    "one generated SoundBank inclusion requires at least one filter"
                )
            bank_handle, *filter_names = group
            if bank_handle not in rows:
                raise SoundBankBusinessCliError(
                    "inclusions references an undeclared SoundBank handle"
                )
            inclusions = rows[bank_handle].setdefault("inclusions", [])
            for filter_name in filter_names:
                if filter_name in inclusions:
                    raise SoundBankBusinessCliError(
                        "one generated SoundBank inclusion filter was supplied twice"
                    )
                inclusions.append(filter_name)
        for source, field in ((args.empty_events, "event_handles"),
            (args.empty_aux_busses, "aux_bus_handles"), (args.empty_generation_inclusions, "inclusions")):
            for key in source:
                if key not in rows or field in rows[key]:
                    raise SoundBankBusinessCliError("an explicit empty list needs one declared bank and cannot replace supplied values")
                rows[key][field] = []
        if len(args.soundbank_rebuild) != len(
            {handle for handle, _value in args.soundbank_rebuild}
        ):
            raise SoundBankBusinessCliError(
                "one SoundBank rebuild choice was supplied twice"
            )
        for handle, raw_rebuild in args.soundbank_rebuild:
            if handle not in rows:
                raise SoundBankBusinessCliError(
                    "SoundBank rebuild references an undeclared handle"
                )
            if raw_rebuild not in {"true", "false"}:
                raise SoundBankBusinessCliError(
                    "SoundBank rebuild must be true or false"
                )
            rows[handle]["rebuild"] = raw_rebuild == "true"
        plan: dict[str, Any] = {
            "soundbanks": [rows[handle] for handle in order],
            "platforms": list(args.platform),
            "io_root": args.io_root,
        }
        if args.language:
            plan["languages"] = list(args.language)
        if args.all_languages:
            if args.language:
                raise SoundBankBusinessCliError("all-languages cannot be combined with selected languages")
            plan["languages"] = []
        if args.all_user_soundbanks is not None:
            if rows:
                raise SoundBankBusinessCliError("all-user-soundbanks cannot be combined with selected banks")
            plan["all_user_soundbanks"] = args.all_user_soundbanks
        if args.all_user_bank_expectation:
            if args.all_user_soundbanks is None:
                raise SoundBankBusinessCliError("all-user-bank-expectation requires all-user-soundbanks")
            plan["all_user_bank_expectations"] = [
                {"soundbank_handle": handle, "artifact_expectation": expectation}
                for handle, expectation in args.all_user_bank_expectation
            ]
        for name in (
            "write_to_disk",
            "skip_languages",
            "rebuild_soundbanks",
            "clear_audio_file_cache",
            "rebuild_init_bank",
        ):
            value = getattr(args, name)
            if value is not None:
                plan[name] = value if value == "native-default" else value == "true"
        return plan
    if operation == "soundbank.convertExternalSources":
        sources = []
        for row in args.source:
            if len(row) not in {2, 3}:
                raise SoundBankBusinessCliError("one source requires INPUT PLATFORM and optional OUTPUT")
            sources.append(dict(zip(("input", "platform", "output"), row)))
        return {"sources": sources, "io_root": args.io_root}
    return {
        "files": list(args.definition_file),
        "io_root": args.io_root,
    }


__all__ = [
    "SoundBankBusinessCliError",
    "add_soundbank_plan_arguments",
    "soundbank_plan_from_namespace",
]
