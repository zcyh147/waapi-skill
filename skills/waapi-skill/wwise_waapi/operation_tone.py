"""Bounded local artifact checks for the fixed closed Tone WAV route."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .filesystem_security import metadata_is_link_or_reparse
from .builders.schema import SemanticSchemaValidator
from .canonical import canonical_sha256
from .operation_soundbank import (
    MAX_TREE_FILE_BYTES, SoundBankContractError, capture_file_proof,
    prove_artifact_path,
)

TONE_URI = "ak.wwise.debug.generateToneWAV"
TONE_FILE_VERIFICATION_SCOPE = {
    "business_outcome": "file_creation_only",
    "observed": ["exact_owned_output_path", "regular_file", "created_or_rewritten"],
    "not_checked": ["file_format", "channels", "sample_rate", "markers", "waveform", "audio_quality"],
}


def tone_output_snapshot(path: str, root: str) -> dict[str, Any]:
    proof = prove_artifact_path(path, io_root=root, field="tone output", expect_directory=False)
    return {"path": proof, "root": _root_identity(root), "file": capture_file_proof(path, field="tone output",
        max_bytes=MAX_TREE_FILE_BYTES, io_root=root) if proof["exists"] else None}


def prepare_tone_verification(args: Mapping[str, Any], audit: Mapping[str, Any], version: str) -> dict[str, Any]:
    paths = [row for row in audit["paths"] if row["json_path"] == "$.args.path"]
    if len(paths) != 1:
        raise SoundBankContractError("INVALID_PATH", "Tone output lacks its exact isolated path audit.")
    path, root = paths[0]["resolved_path"], audit["io_root"]
    effective = {**TONE_DEFAULTS, **dict(args)}
    budget = tone_artifact_budget(effective)
    return {"kind": "tone-wav-artifact", "uri": TONE_URI, "version": version,
        "args": dict(args), "effective": effective, "artifact_budget": budget,
        "explicit_fields": sorted(args),
        "verification_scope": TONE_FILE_VERIFICATION_SCOPE,
        "schema_sha256": canonical_sha256(SemanticSchemaValidator(version=version).schema_for(TONE_URI)),
        "path": path, "io_root": root,
        "before": tone_output_snapshot(path, root)}



# Defaults stated by the exact packaged 2023.1/2024.1/2025.1 Tone argument
# descriptions. Bind these independently of execution output and retain which
# values the caller actually supplied; markers have no invented omission default.
TONE_DEFAULTS = {'waveform': 'silence', 'frequency': 440, 'channelConfig': '1.0',
    'bitDepth': 'int16', 'sampleRate': 48000, 'attackTime': 0, 'sustainTime': 1,
    'releaseTime': 0, 'sustainLevel': 0, 'setAnonymous': False}


def _root_identity(root: str) -> dict[str, Any]:
    path = Path(root)
    try:
        metadata = path.lstat()
        if metadata_is_link_or_reparse(metadata) or not path.is_dir():
            raise SoundBankContractError('INVALID_IO_ROOT', 'Tone output root must remain a real directory.')
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SoundBankContractError('INVALID_IO_ROOT', 'Tone isolated output root is inaccessible or changed.', details={'reason': str(exc)}) from exc
    return {'resolved_path': str(resolved), 'device': metadata.st_dev, 'inode': metadata.st_ino}


def validate_tone_binding(plan, args, audit, version):
    if (plan.get('kind') != 'tone-wav-artifact' or plan.get('uri') != TONE_URI
            or plan.get('version') != version or plan.get('args') != dict(args)
            or plan.get('effective') != {**TONE_DEFAULTS, **dict(args)}
            or plan.get('artifact_budget') != tone_artifact_budget({**TONE_DEFAULTS, **dict(args)})
            or plan.get('explicit_fields') != sorted(args)
            or plan.get('verification_scope') != TONE_FILE_VERIFICATION_SCOPE
            or plan.get('schema_sha256') != canonical_sha256(SemanticSchemaValidator(version=version).schema_for(TONE_URI))
            or plan.get('io_root') != audit.get('io_root')
            or [row['resolved_path'] for row in audit['paths'] if row['json_path'] == '$.args.path'] != [plan.get('path')]):
        raise SoundBankContractError('INVALID_PREVIEW', 'Tone verification no longer matches its exact versioned request and I/O audit.')
    if tone_output_snapshot(plan['path'], plan['io_root']) != plan['before']:
        raise SoundBankContractError('FILE_CHANGED', 'Tone output or isolated root changed after preview; prepare again.')


def verify_tone_output_file(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Prove only the approved file-creation outcome, without parsing audio."""
    if _root_identity(plan['io_root']) != plan['before']['root']:
        raise SoundBankContractError('FILE_CHANGED', 'Tone isolated output root changed after preview.')
    after = tone_output_snapshot(plan['path'], plan['io_root'])
    if after['root'] != plan['before']['root'] or _root_identity(plan['io_root']) != plan['before']['root']:
        raise SoundBankContractError('FILE_CHANGED', 'Tone isolated output root changed during verification.')
    if after['file'] is None:
        raise SoundBankContractError('MISSING_ARTIFACT', 'Requested Tone output file is missing.')
    before = plan['before']['file']
    if before is not None and all(before[key] == after['file'][key]
            for key in ('size', 'sha256', 'mtime_ns', 'device', 'inode')):
        raise SoundBankContractError('ARTIFACT_UNCHANGED',
            'The existing Tone output file has no observable creation or rewrite; do not retry execution.')
    return {
        'artifact': {'path': after['path'], 'file': after['file']},
        'created': before is None,
        'changed': before is None or any(before[key] != after['file'][key] for key in ('size', 'sha256')),
        'rewritten': before is not None,
    }


# Gateway ceilings used to reserve format and marker bytes before dispatch.
MAX_WAV_FORMAT_BYTES = 4096
MAX_WAV_MARKER_LIST_BYTES = 128 * 1024

# Standard channel counts from AkSpeakerConfig.h.
STANDARD_LAYOUT_CHANNELS = {"0.1": 1, "1.0": 1, "2.0": 2, "2.1": 3, "3.0": 3, "4.0": 4,
    "5.1": 6, "7.1": 8, "5.1.2": 8, "7.1.2": 10, "7.1.4": 12}


def tone_artifact_budget(effective: Mapping[str, Any]) -> dict[str, Any]:
    rate = Decimal(str(effective['sampleRate']))
    segments = [Decimal(str(effective[key])) * rate for key in ('attackTime', 'sustainTime', 'releaseTime')]
    layout = effective['channelConfig']
    channels = STANDARD_LAYOUT_CHANNELS[layout] if layout in STANDARD_LAYOUT_CHANNELS else (int(layout.split()[1][0]) + 1) ** 2
    audio_bytes = int(sum(segments)) * channels * (2 if effective['bitDepth'] == 'int16' else 4)
    # Reserve the full accepted fmt payload, RIFF+data framing, every cue and
    # requested UTF-8 label including optional terminator/padding. This is a
    # disclosed resource reservation, not a claim about the native writer's
    # chosen fmt size or marker text encoding. Extra/native-variant metadata
    # and fractional duration interpretation remain independently bounded at readback.
    markers = effective.get('markers')
    metadata_bytes = 0
    list_bytes = 0
    if markers is not None:
        list_bytes = 4
        for marker in markers:
            payload = 4 + len(marker.get('label', '').encode('utf-8')) + 1
            list_bytes += 8 + payload + (payload & 1)
        metadata_bytes = 12 + 24 * len(markers) + 8 + list_bytes
    framing_bytes = 12 + 8 + MAX_WAV_FORMAT_BYTES + 8 + metadata_bytes
    reserved = audio_bytes + framing_bytes
    budget = {'artifact_limit_bytes': MAX_TREE_FILE_BYTES, 'audio_bytes_before_native_rounding': audio_bytes,
        'format_payload_reserve_bytes': MAX_WAV_FORMAT_BYTES,
        'requested_utf8_marker_list_bytes': list_bytes, 'header_and_metadata_reserve_bytes': framing_bytes,
        'reserved_total_bytes': reserved,
        'duration_rounding_unresolved': rate != rate.to_integral_value() or any(value != value.to_integral_value() for value in segments),
        'native_marker_encoding_unresolved': bool(markers), 'additional_native_chunks_unknown': True}
    if reserved > MAX_TREE_FILE_BYTES or list_bytes > MAX_WAV_MARKER_LIST_BYTES:
        raise SoundBankContractError('LIMIT_EXCEEDED',
            'Requested Tone WAV exceeds the 512 MiB Gateway artifact budget including format/marker resource reservations before dispatch.',
            details={'artifact_budget': budget})
    return budget
