"""Bounded local artifact checks for the fixed closed Tone WAV route."""
from __future__ import annotations

import hashlib
from collections import Counter
import math
from decimal import Decimal
import os
import struct
from pathlib import Path
from typing import Any, Mapping

from .filesystem_security import metadata_is_link_or_reparse
from .builders.schema import SemanticSchemaValidator
from .canonical import canonical_sha256
from .operation_soundbank import (
    MAX_TREE_FILE_BYTES, SoundBankContractError, capture_file_proof,
    prove_artifact_path, open_regular_artifact_file,
)

TONE_URI = "ak.wwise.debug.generateToneWAV"


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
            or plan.get('schema_sha256') != canonical_sha256(SemanticSchemaValidator(version=version).schema_for(TONE_URI))
            or plan.get('io_root') != audit.get('io_root')
            or [row['resolved_path'] for row in audit['paths'] if row['json_path'] == '$.args.path'] != [plan.get('path')]):
        raise SoundBankContractError('INVALID_PREVIEW', 'Tone verification no longer matches its exact versioned request and I/O audit.')
    if tone_output_snapshot(plan['path'], plan['io_root']) != plan['before']:
        raise SoundBankContractError('FILE_CHANGED', 'Tone output or isolated root changed after preview; prepare again.')

def verify_tone_artifact(plan: Mapping[str, Any]) -> dict[str, Any]:
    if _root_identity(plan['io_root']) != plan['before']['root']:
        raise SoundBankContractError('FILE_CHANGED', 'Tone isolated output root changed after preview.')
    parsed = inspect_tone_wav(plan["path"], plan["io_root"], plan["effective"])
    if _root_identity(plan['io_root']) != plan['before']['root']:
        raise SoundBankContractError('FILE_CHANGED', 'Tone isolated output root changed during verification.')
    after = {"path": parsed.pop("path_proof"), "file": parsed.pop("file_proof")}
    if after["file"] is None:
        raise SoundBankContractError("MISSING_ARTIFACT", "Requested Tone WAV artifact is missing.")
    before = plan["before"]["file"]
    return {"artifact": after, "wav": parsed, "created": before is None,
        "changed": before is None or any(before[key] != after["file"][key] for key in ("size", "sha256")),
        "unresolved": parsed.pop("unresolved")}


# Bounded format metadata; audio is consumed in fixed blocks, never allocated by
# a file-authored chunk size. These are Gateway resource ceilings, not WAV limits.
MAX_WAV_CHUNKS = 4096
MAX_WAV_FORMAT_BYTES = 4096
MAX_WAV_MARKER_LIST_BYTES = 128 * 1024



def tone_artifact_budget(effective: Mapping[str, Any]) -> dict[str, Any]:
    rate = Decimal(str(effective['sampleRate']))
    segments = [Decimal(str(effective[key])) * rate for key in ('attackTime', 'sustainTime', 'releaseTime')]
    layout = effective['channelConfig']
    channels = STANDARD_LAYOUTS[layout][0] if layout in STANDARD_LAYOUTS else (int(layout.split()[1][0]) + 1) ** 2
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


def _invalid(message: str) -> SoundBankContractError:
    return SoundBankContractError("INVALID_TONE_WAV", message)


class _WavReader:
    def __init__(self, stream, size: int):
        self.stream, self.size, self.offset = stream, size, 0
        self.digest = hashlib.sha256()

    def read(self, count: int) -> bytes:
        if count < 0 or self.offset + count > self.size or count > 1024 * 1024:
            raise _invalid("Tone WAV chunk exceeds its bounded file extent.")
        value = self.stream.read(count)
        if len(value) != count:
            raise _invalid("Tone WAV was truncated during inspection.")
        self.digest.update(value)
        self.offset += count
        return value

    def discard(self, count: int) -> None:
        if count < 0 or self.offset + count > self.size:
            raise _invalid("Tone WAV chunk exceeds its bounded file extent.")
        while count:
            amount = min(count, 65536)
            self.read(amount)
            count -= amount


def inspect_tone_wav(path: str, root: str, args: Mapping[str, Any]) -> dict[str, Any]:
    path_proof = prove_artifact_path(path, io_root=root, field="tone artifact",
        must_exist=True, expect_directory=False)
    opened_path, descriptor, before = open_regular_artifact_file(path, field="tone artifact", io_root=root)
    try:
        with os.fdopen(descriptor, "rb") as stream:
            _require_stable_artifact(path, root, path_proof, before, os.fstat(stream.fileno()))
            if before.st_size > MAX_TREE_FILE_BYTES:
                raise SoundBankContractError("LIMIT_EXCEEDED", "Tone WAV exceeds the 512 MiB Gateway artifact bound.")
            reader = _WavReader(stream, before.st_size)
            header = reader.read(12)
            if header[:4] != b"RIFF" or header[8:] != b"WAVE" or struct.unpack_from("<I", header, 4)[0] + 8 != before.st_size:
                raise _invalid("Tone artifact must be a complete bounded RIFF/WAVE file.")
            fmt = data = None
            cues = None
            labels: dict[int, bytes] = {}
            count = 0
            while reader.offset < reader.size:
                count += 1
                if count > MAX_WAV_CHUNKS:
                    raise SoundBankContractError("LIMIT_EXCEEDED", "Tone WAV exceeds the 4096 chunk Gateway bound.")
                chunk_id, size = struct.unpack("<4sI", reader.read(8))
                if reader.offset + size + (size & 1) > reader.size:
                    raise _invalid("Tone WAV chunk extends past the declared RIFF boundary.")
                if chunk_id == b"fmt ":
                    if fmt is not None or not 16 <= size <= MAX_WAV_FORMAT_BYTES:
                        raise _invalid("Tone WAV requires one bounded format chunk.")
                    fmt = reader.read(size)
                elif chunk_id == b"data":
                    if data is not None:
                        raise _invalid("Tone WAV contains duplicate audio data chunks.")
                    data = (reader.offset, size)
                    reader.discard(size)
                elif chunk_id == b"cue ":
                    if cues is not None or size < 4:
                        raise _invalid("Tone WAV has duplicate or truncated cue metadata.")
                    cue_count = struct.unpack("<I", reader.read(4))[0]
                    if cue_count > 128:
                        raise SoundBankContractError("LIMIT_EXCEEDED", "Tone WAV exceeds the 128 cue Gateway bound.")
                    if size != 4 + cue_count * 24:
                        raise _invalid("Tone WAV cue count does not match its chunk extent.")
                    cues = {}
                    for _ in range(cue_count):
                        cue_id, position, target, chunk_start, block_start, sample_offset = struct.unpack("<II4sIII", reader.read(24))
                        if cue_id in cues or target != b"data":
                            raise _invalid("Tone WAV cue identities or data association are malformed.")
                        cues[cue_id] = {'cue_id': cue_id, 'position': position,
                            'chunk_start': chunk_start, 'block_start': block_start, 'sample_offset': sample_offset}
                elif chunk_id == b"LIST":
                    if size < 4:
                        raise _invalid("Tone WAV LIST chunk omits its list type.")
                    list_end = reader.offset + size
                    list_type = reader.read(4)
                    if list_type == b"adtl":
                        _read_marker_labels(reader, list_end, labels)
                    else:
                        reader.discard(list_end - reader.offset)
                else:
                    reader.discard(size)
                if size & 1:
                    reader.read(1)
            if fmt is None or data is None:
                raise _invalid("Tone WAV requires both format and audio data chunks.")
            if set(labels) - set(cues or {}):
                raise _invalid("Tone WAV contains orphan marker labels.")
            if args.get("markers") == [] and (cues or labels):
                raise _invalid("Tone WAV contains markers despite the explicit empty marker request.")
            observed = _parse_format(fmt)
            if data[1] % observed["block_align"]:
                raise _invalid("Tone WAV audio data is not frame-aligned.")
            observed["frames"] = data[1] // observed["block_align"]
            observed["markers"], marker_unresolved = _check_requested_markers(cues or {}, labels, args)
            unresolved = _check_requested_format(observed, args) + marker_unresolved
            observed["nonzero_samples_by_channel"] = _scan_samples(stream, data, observed, args)
            if args.get("waveform", "silence") != "silence" and args.get("waveformChannelMask") != 0:
                unresolved.append("active waveform, frequency and envelope postconditions")
            after = os.fstat(stream.fileno())
            _require_stable_artifact(path, root, path_proof, before, after)
            return {**observed, "unresolved": unresolved, "path_proof": path_proof,
                "file_proof": {"path": str(opened_path), "size": after.st_size,
                    "sha256": reader.digest.hexdigest(), "mtime_ns": after.st_mtime_ns,
                    "device": after.st_dev, "inode": after.st_ino}}
    except OSError as exc:
        raise SoundBankContractError("INVALID_FILE", "Tone artifact could not be inspected.", details={"reason": str(exc)}) from exc


def _require_stable_artifact(path, root, path_proof, before, after):
    names = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    current = Path(path).stat()
    if any(getattr(before, name) != getattr(after, name) or getattr(after, name) != getattr(current, name) for name in names):
        raise SoundBankContractError("FILE_CHANGED", "Tone artifact changed during inspection.")
    if prove_artifact_path(path, io_root=root, field="tone artifact", must_exist=True,
            expect_directory=False) != path_proof:
        raise SoundBankContractError("FILE_CHANGED", "Tone artifact path changed during inspection.")


# Exact standard speaker positions from matching 2023/2024/2025 SDK
# AkSpeakerConfig.h. This is unrelated to waveformChannelMask (sample indexes).
STANDARD_LAYOUTS = {"0.1": (1, 8), "1.0": (1, 4), "2.0": (2, 3),
    "2.1": (3, 11), "3.0": (3, 7), "4.0": (4, 1539), "5.1": (6, 1551),
    "7.1": (8, 1599), "5.1.2": (8, 22031), "7.1.2": (10, 22079), "7.1.4": (12, 185919)}
PCM_SUBTYPE = bytes.fromhex("0100000000001000800000aa00389b71")
FLOAT_SUBTYPE = bytes.fromhex("0300000000001000800000aa00389b71")


def _parse_format(fmt: bytes) -> dict[str, Any]:
    tag, channels, rate, byte_rate, alignment, bits = struct.unpack_from("<HHIIHH", fmt)
    subtype, speaker_mask, valid_bits = tag, None, None
    if len(fmt) != 16:
        if len(fmt) < 18 or struct.unpack_from("<H", fmt, 16)[0] + 18 != len(fmt):
            raise _invalid("Tone WAV format extension length is inconsistent.")
    if tag == 65534:
        if len(fmt) < 40:
            raise _invalid("Tone WAV extensible format lacks valid bits, mask or subtype.")
        valid_bits, speaker_mask = struct.unpack_from("<HI", fmt, 18)
        guid = fmt[24:40]
        subtype = 1 if guid == PCM_SUBTYPE else 3 if guid == FLOAT_SUBTYPE else None
        # The retained Console2025.1.7.9143 Tone PCM16/float32 outputs use
        # zero in this union field. Decode only the explicit supported subtype /
        # container pair below; preserve zero without inventing a precision claim
        # or a generic WAV default. Nonzero contradictory widths stay invalid.
        if valid_bits not in (0, bits) or subtype is None:
            raise _invalid("Tone WAV extensible valid bits or PCM/float subtype is unsupported.")
    if not channels or channels > 64 or not rate or (subtype, bits) not in {(1, 16), (3, 32)}:
        raise _invalid("Tone WAV does not contain bounded PCM16 or IEEE float32 audio.")
    if alignment != channels * (bits // 8) or byte_rate != rate * alignment:
        raise _invalid("Tone WAV block alignment or byte rate is inconsistent.")
    return {"format_tag": tag, "sample_format": "int16" if subtype == 1 else "float32",
        "channels": channels, "sample_rate": rate, "byte_rate": byte_rate,
        "block_align": alignment, "bits": bits, "valid_bits": valid_bits, "speaker_mask": speaker_mask}


def _check_requested_format(observed: Mapping[str, Any], args: Mapping[str, Any]) -> list[str]:
    unresolved = []
    if observed["sample_format"] != args.get("bitDepth", "int16"):
        raise _invalid("Tone WAV sample format differs from the frozen requested bit depth.")
    rate = Decimal(str(args.get("sampleRate", 48000)))
    if rate != rate.to_integral_value():
        unresolved.append("fractional sample-rate native rounding")
    elif observed["sample_rate"] != int(rate):
        raise _invalid("Tone WAV sample rate differs from the frozen requested rate.")
    segments = [Decimal(str(args.get(key, default))) * rate for key, default in
        (("attackTime", 0), ("sustainTime", 1), ("releaseTime", 0))]
    if rate == rate.to_integral_value() and all(frames == frames.to_integral_value() for frames in segments):
        if observed["frames"] != int(sum(segments)):
            raise _invalid("Tone WAV frame count differs from the requested integral-frame duration.")
    else:
        unresolved.append("fractional segment duration/frame rounding")
    layout = args.get("channelConfig", "1.0")
    standard = STANDARD_LAYOUTS.get(layout)
    channels = standard[0] if standard else (int(layout.split()[1][0]) + 1) ** 2
    if observed["channels"] != channels:
        raise _invalid("Tone WAV channel count differs from the requested layout.")
    if args.get("setAnonymous", False):
        # Pinned native input says anonymous overrides the configuration type,
        # retaining count (also when that count was supplied by Ambisonic order).
        # Microsoft WAVEFORMATEXTENSIBLE remarks define zero/direct-out as no
        # assigned speakers. This observes that header state, not writer choice.
        # https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ksmedia/ns-ksmedia-waveformatextensible
        if observed["speaker_mask"] is None:
            unresolved.append("native anonymous-channel layout representation without explicit speaker positions")
        elif observed["speaker_mask"] != 0:
            raise _invalid("Tone WAV assigns speaker positions despite the requested anonymous channel configuration.")
    elif standard:
        if observed["speaker_mask"] is not None:
            if observed["speaker_mask"] != standard[1]:
                raise _invalid("Tone WAV speaker positions differ from the requested layout.")
        elif layout not in {"1.0", "2.0"}:
            unresolved.append("legacy WAV channel layout without explicit speaker positions")
    else:
        unresolved.append("native Ambisonic channel representation and normalization")
    return unresolved


def _scan_samples(stream, data, observed: Mapping[str, Any], args: Mapping[str, Any]) -> list[int]:
    stream.seek(data[0])
    remaining = data[1]
    channels, alignment = observed["channels"], observed["block_align"]
    silence_mask = (1 << channels) - 1 if args.get("waveform", "silence") == "silence" else (
        ((1 << channels) - 1) ^ args.get("waveformChannelMask", (1 << channels) - 1))
    nonzero = [0] * channels
    encoding = "<h" if observed["sample_format"] == "int16" else "<f"
    sample_index = 0
    while remaining:
        count = min(remaining, max(alignment, (65536 // alignment) * alignment))
        values = stream.read(count)
        if len(values) != count:
            raise _invalid("Tone WAV changed or truncated during its full sample scan.")
        for (sample,) in struct.iter_unpack(encoding, values):
            channel = sample_index % channels
            if not math.isfinite(sample):
                raise _invalid("Tone WAV contains a non-finite sample.")
            if sample != 0:
                nonzero[channel] += 1
                if silence_mask & (1 << channel):
                    raise _invalid(f"Tone WAV contains a nonzero sample in requested silent channel {channel} at sample {sample_index}.")
            sample_index += 1
        remaining -= count
    return nonzero



def _read_marker_labels(reader: _WavReader, end: int, labels: dict[int, bytes]) -> None:
    metadata_bytes = end - reader.offset
    if metadata_bytes > MAX_WAV_MARKER_LIST_BYTES:
        raise SoundBankContractError("LIMIT_EXCEEDED", "Tone WAV marker metadata exceeds the 128 KiB Gateway bound.")
    chunks = 0
    while reader.offset < end:
        chunks += 1
        if chunks > MAX_WAV_CHUNKS or end - reader.offset < 8:
            raise _invalid("Tone WAV marker metadata is malformed or over-bounded.")
        kind, size = struct.unpack("<4sI", reader.read(8))
        if reader.offset + size + (size & 1) > end:
            raise _invalid("Tone WAV marker label exceeds its LIST boundary.")
        if kind == b"labl":
            if size < 4 or size > 4 + 8192 + 1 or len(labels) >= 128:
                raise _invalid("Tone WAV marker label exceeds its bounded size or count.")
            cue_id = struct.unpack("<I", reader.read(4))[0]
            if cue_id in labels:
                raise _invalid("Tone WAV marker label has a duplicate cue identity.")
            labels[cue_id] = reader.read(size - 4)
        else:
            reader.discard(size)
        if size & 1:
            reader.read(1)


def _check_requested_markers(cues: Mapping[int, Mapping[str, int]], labels: Mapping[int, bytes],
                             args: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    # WaveCue/sample offset and AkWaveMarker frame positions are pinned in the
    # matching SDK AkWavDefs.h. Cue IDs bind labels, never input array indexes.
    # An optional terminal null is allowed by AkWaveMarker's documented count.
    actual = [(row['sample_offset'], labels.get(identity, b'').removesuffix(b'\0'))
              for identity, row in cues.items()]
    summary = {'cue_count': len(cues), 'label_count': len(labels),
        'rows': [{**dict(row), 'label_bytes': len(labels.get(identity, b'')),
                  'label_sha256': hashlib.sha256(labels.get(identity, b'')).hexdigest()}
                 for identity, row in cues.items()]}
    requested = args.get('markers')
    if requested is None:
        return summary, []
    if len(cues) != len(requested):
        raise _invalid('Tone WAV marker count differs from the frozen requested list, including multiplicity.')
    canonical_positions = all(not row['chunk_start'] and not row['block_start'] for row in cues.values())
    rate = Decimal(str(args.get('sampleRate', 48000)))
    expected = []
    for marker in requested:
        frame = Decimal(str(marker['position'])) * rate
        # Source does not specify native fractional-rate/marker rounding. Keep
        # the valid request and check the known parts without inventing ±frames.
        position = int(frame) if rate == rate.to_integral_value() and frame == frame.to_integral_value() and canonical_positions else None
        text = marker.get('label', '')
        label = text.encode('ascii') if text.isascii() else None
        expected.append((position, label))
    positions_checked = all(position is not None for position, _ in expected)
    labels_checked = all(label is not None for _, label in expected)
    def require_subset(known, observed, field):
        if Counter(known) - Counter(observed):
            raise _invalid(f'Tone WAV requested marker {field} differ from their cue/label associations.')
    require_subset([position for position, _ in expected if position is not None],
                   [position for position, _ in actual], 'frame positions')
    require_subset([label for _, label in expected if label is not None],
                   [label for _, label in actual], 'labels')
    require_subset([(position, label) for position, label in expected if position is not None and label is not None],
                   actual, 'position/label pairs')
    summary.update(requested_positions_checked=positions_checked, requested_labels_checked=labels_checked)
    unresolved = []
    if not positions_checked:
        unresolved.append('native fractional marker rounding or cue chunk/block position interpretation')
    if not labels_checked:
        unresolved.append('native populated marker Unicode label encoding')
    return summary, unresolved
