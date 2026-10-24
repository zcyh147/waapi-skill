"""Bounded local artifact checks for the fixed closed Tone WAV route."""
from __future__ import annotations

import hashlib
from collections import Counter
import math
from decimal import Decimal
import os
import struct
from fractions import Fraction
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
            observed["nonzero_samples_by_channel"], signal = _scan_samples(stream, data, observed, args)
            if signal is not None:
                observed['stationary_triangle' if args.get('waveform') == 'triangle' else
                    ('stationary_square' if args.get('waveform') == 'square' else
                    ("sine_envelope" if 'segments' in signal else "stationary_sine"))] = signal
            if args.get("waveform", "silence") != "silence" and args.get("waveformChannelMask") != 0:
                if signal is None or signal['observability_reason'] is not None:
                    unresolved.append("active waveform, frequency and envelope postconditions" + (
                        ': ' + signal['observability_reason'] if signal is not None else ''))
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


def _audio_samples(stream, data, observed):
    """Descriptor-owned fixed-block iterator, also used for the second signal pass."""
    stream.seek(data[0])
    remaining = data[1]
    alignment = observed["block_align"]
    encoding = "<h" if observed["sample_format"] == "int16" else "<f"
    while remaining:
        count = min(remaining, max(alignment, (65536 // alignment) * alignment))
        values = stream.read(count)
        if len(values) != count:
            raise _invalid("Tone WAV changed or truncated during its full sample scan.")
        yield from struct.iter_unpack(encoding, values)
        remaining -= count


def _scan_samples(stream, data, observed: Mapping[str, Any], args: Mapping[str, Any]):
    channels = observed['channels']
    silence_mask = (1 << channels) - 1 if args.get("waveform", "silence") == "silence" else (
        ((1 << channels) - 1) ^ args.get("waveformChannelMask", (1 << channels) - 1))
    nonzero = [0] * channels
    stationary = (args.get('waveform') == 'sine' and not args.get('attackTime', 0)
        and not args.get('releaseTime', 0) and silence_mask != (1 << channels) - 1)
    sine_requested = args.get('waveform') == 'sine' and silence_mask != (1 << channels) - 1
    square_requested = (args.get('waveform') == 'square' and not args.get('attackTime', 0)
        and not args.get('releaseTime', 0) and silence_mask != (1 << channels) - 1)
    triangle_requested = (args.get('waveform') == 'triangle' and not args.get('attackTime', 0)
        and not args.get('releaseTime', 0) and silence_mask != (1 << channels) - 1)
    signal = _sine_signal_policy(observed, args, enveloped=not stationary) if sine_requested else (
        _square_signal_policy(observed, args) if square_requested else (
            _triangle_signal_policy(observed, args) if triangle_requested else None))
    triangle = _triangle_arithmetic(observed, args, signal) if triangle_requested else None
    triangle_rows = {channel: {'candidates': [], 'previous_sign': None, 'sign_transitions': 0}
        for channel in range(channels) if not silence_mask & (1 << channel)} if triangle_requested else None
    square_rows = {channel: {'phase_intervals': [[0, signal['phase_half_cycle_units']]], 'anchor': None,
        'magnitude_sum': 0.0, 'previous_sign': None, 'sign_transitions': 0, 'max_sample_error': 0.0}
        for channel in range(channels) if not silence_mask & (1 << channel)} if square_requested else None
    envelope_stats = [{'gram': [0.0, 0.0, 0.0], 'projections': [[0.0, 0.0] for _ in range(channels)]}
        for _ in signal['segments']] if signal is not None and 'segments' in signal else None
    ss = cc = sc = 0.0
    projections = [[0.0, 0.0] for _ in range(channels)]
    scale = 32768 if observed['sample_format'] == 'int16' else 1
    for sample_index, (sample,) in enumerate(_audio_samples(stream, data, observed)):
        channel = sample_index % channels
        if not math.isfinite(sample):
            raise _invalid("Tone WAV contains a non-finite sample.")
        if sample != 0:
            nonzero[channel] += 1
            if silence_mask & (1 << channel):
                raise _invalid(f"Tone WAV contains a nonzero sample in requested silent channel {channel} at sample {sample_index}.")
        if triangle_rows is not None and channel in triangle_rows:
            _observe_triangle_sample(sample, sample_index // channels, triangle_rows[channel], triangle,
                signal, channel)
        if square_rows is not None and channel in square_rows:
            row = square_rows[channel]
            magnitude = abs(sample / scale)
            error = abs(magnitude - signal['requested_gain'])
            if error > signal['sample_error_limit']:
                raise SoundBankContractError('INVALID_TONE_WAV',
                    'Tone stationary square sample magnitude differs from requested gain within the numerical policy.',
                    details={'stationary_square': signal, 'channel': channel,
                        'sample_index': sample_index, 'sample_error': error})
            row['magnitude_sum'] += magnitude
            row['max_sample_error'] = max(row['max_sample_error'], error)
            positive = sample >= 0
            if row['previous_sign'] is not None and positive != row['previous_sign']:
                row['sign_transitions'] += 1
            row['previous_sign'] = positive
            if signal['observability_reason'] is None and row['phase_intervals']:
                _observe_square_phase(positive, sample_index // channels, row, signal)
        if sine_requested and signal['observability_reason'] is None:
            if channel == 0:
                phase = math.remainder(signal['angular_step'] * (sample_index // channels), math.tau)
                sine, cosine = math.sin(phase), math.cos(phase)
                if envelope_stats is not None:
                    segment_index, segment, amplitude = _envelope_at(signal, sample_index // channels)
                    sine, cosine = sine * amplitude, cosine * amplitude
                    gram = envelope_stats[segment_index]['gram']
                    gram[0] += sine * sine
                    gram[1] += cosine * cosine
                    gram[2] += sine * cosine
                else:
                    ss += sine * sine
                    cc += cosine * cosine
                    sc += sine * cosine
            target = envelope_stats[segment_index]['projections'] if envelope_stats is not None else projections
            target[channel][0] += sample / scale * sine
            target[channel][1] += sample / scale * cosine
    if sine_requested and signal['observability_reason'] is None:
        if envelope_stats is not None:
            _check_sine_envelope(stream, data, observed, silence_mask, envelope_stats, signal)
        else:
            _check_stationary_sine(stream, data, observed, silence_mask, projections, (ss, cc, sc), signal)
    if square_rows is not None:
        _finish_square_channels(square_rows, observed['frames'], signal)
    if triangle_rows is not None:
        _finish_triangle_channels(triangle_rows, triangle, signal)
    return nonzero, signal


def _triangle_signal_policy(observed, args):
    signal = _sine_signal_policy(observed, args)
    signal.pop('angular_step')
    signal.update(policy='stationary-triangle-numerical-conformance-v1',
        reference='requested digital triangle; at most two first-sample inverse phase witnesses per active channel; fixed requested gain/cadence; not a complete feasible-phase solver or native DSP theorem',
        feasibility_search_complete=False, maximum_phase_candidates_per_channel=2)
    return signal


def _triangle_arithmetic(observed, args, signal):
    # See TONE_STATIONARY_TRIANGLE.md. These rationals describe the numerical
    # policy, never a guessed native input/accumulator type. All sample, phase,
    # projection and acceptance arithmetic below is exact and fixed-size.
    gain, error = Fraction(signal['requested_gain']), Fraction(signal['sample_error_limit'])
    maximum_level = gain + error
    return {'step': Fraction(str(args.get('frequency', 440))) / observed['sample_rate'],
        'scale': 32768 if observed['sample_format'] == 'int16' else 2 ** 149,
        'gain': gain, 'error': error,
        'maximum_level_numerator': maximum_level.numerator, 'maximum_level_denominator': maximum_level.denominator,
        'representation': Fraction(signal['representation_error']),
        'gain_lower': Fraction(signal['requested_gain'] * 10 ** (-0.02 / 20)),
        'gain_upper': Fraction(signal['requested_gain'] * 10 ** (0.02 / 20))}


def _observe_triangle_sample(sample, frame, row, arithmetic, signal, channel):
    scale, gain, error = arithmetic['scale'], arithmetic['gain'], arithmetic['error']
    numerator, denominator = sample.as_integer_ratio()
    value = numerator if scale == 32768 else numerator * (scale // denominator)
    if abs(value) * arithmetic['maximum_level_denominator'] > arithmetic['maximum_level_numerator'] * scale:
        raise SoundBankContractError('INVALID_TONE_WAV',
            'Tone stationary triangle sample exceeds the phase-independent requested gain bound.',
            details={'stationary_triangle': signal, 'channel': channel, 'frame': frame})
    positive = sample >= 0
    if row['previous_sign'] is not None and positive != row['previous_sign']:
        row['sign_transitions'] += 1
    row['previous_sign'] = positive
    if not row['candidates']:
        seed = min(Fraction(1), max(Fraction(-1), Fraction(value, scale) / gain))
        phases = dict.fromkeys(((seed / 4) % 1, (Fraction(1, 2) - seed / 4) % 1))
        step = arithmetic['step']
        for phase in phases:
            units = math.lcm(4, step.denominator, phase.denominator)
            row['candidates'].append({'units': units, 'position': phase.numerator * (units // phase.denominator),
                'step': step.numerator * (units // step.denominator), 'phase': float(phase),
                'projection': 0, 'energy': 0, 'absolute_basis': 0,
                'max_error': 0, 'first_sample_mismatch_frame': None})
    for candidate in row['candidates']:
        units = candidate['units']
        basis = units - 4 * abs((candidate['position'] + units // 4) % units - units // 2)
        residual = abs(value * gain.denominator * units - gain.numerator * basis * scale)
        candidate['max_error'] = max(candidate['max_error'], residual)
        if (candidate['first_sample_mismatch_frame'] is None
                and residual * error.denominator > error.numerator * scale * gain.denominator * units):
            candidate['first_sample_mismatch_frame'] = frame
        candidate['projection'] += value * basis
        candidate['energy'] += basis * basis
        candidate['absolute_basis'] += abs(basis)
        candidate['position'] = (candidate['position'] + candidate['step']) % units


def _finish_triangle_channels(rows, arithmetic, signal):
    common_reason = signal['observability_reason']
    for channel, row in rows.items():
        checks = []
        witness = None
        for index, candidate in enumerate(row['candidates']):
            units, energy = candidate['units'], candidate['energy']
            uncertainty = (arithmetic['representation'] * units * candidate['absolute_basis'] / energy
                if energy else None)
            amplitude = Fraction(units * candidate['projection'], arithmetic['scale'] * energy) if energy else None
            observable = uncertainty is not None and uncertainty < arithmetic['gain']
            lower = arithmetic['gain_lower'] - uncertainty if observable else None
            upper = arithmetic['gain_upper'] + uncertainty if observable else None
            gain_matches = observable and lower <= amplitude <= upper
            passed = candidate['first_sample_mismatch_frame'] is None and gain_matches
            checks.append({'phase_cycles': candidate['phase'],
                'max_sample_error': float(Fraction(candidate['max_error'], arithmetic['scale'] * arithmetic['gain'].denominator * units)),
                'first_sample_mismatch_frame': candidate['first_sample_mismatch_frame'],
                'measured_gain': float(amplitude) if amplitude is not None else None,
                'gain_representation_error': float(uncertainty) if uncertainty is not None else None,
                'gain_interval': [float(lower), float(upper)] if observable else None,
                'gain_matches': bool(gain_matches), 'gain_observable': observable})
            if passed and witness is None:
                witness = index
        reason = common_reason
        if reason is None:
            if not checks:
                reason = 'empty triangle record has no observable periodic recurrence'
            elif not any(check['gain_observable'] for check in checks):
                reason = 'requested triangle gain cannot be distinguished from sample quantization'
            elif witness is None:
                reason = 'no sufficient triangle phase witness; complete phase feasibility is not searched and native phase arithmetic precision is unspecified'
            elif row['sign_transitions'] < 2:
                reason = 'triangle record has no observable periodic recurrence (fewer than two sign transitions)'
        selected = checks[witness] if witness is not None else {}
        signal['channels'].append({'channel': channel, 'sufficient_witness_found': witness is not None,
            'witness_candidate': witness, 'sign_transitions': row['sign_transitions'],
            'candidate_checks': checks, 'observability_reason': reason,
            **{key: selected[key] for key in ('measured_gain', 'max_sample_error') if key in selected}})
        signal['observability_reason'] = signal['observability_reason'] or reason


def _square_signal_policy(observed, args):
    # Reuse the reviewed numerical allowances, not the sine's DSP model.
    signal = _sine_signal_policy(observed, args)
    step = Fraction(str(args.get('frequency', 440))) / observed['sample_rate']
    signal.pop('angular_step')
    signal.update(policy='stationary-square-numerical-conformance-v1',
        reference='requested digital square; one unparameterized phase per channel; either limiting sign only at exact discontinuities; not a bit-exact native algorithm or unique analog origin',
        phase_step_units=2 * step.numerator, phase_half_cycle_units=step.denominator)
    if signal['requested_gain'] <= signal['sample_error_limit']:
        signal['observability_reason'] = signal['observability_reason'] or (
            'requested square levels cannot be distinguished from sample quantization')
    return signal


def _finish_square_channels(rows, frames, signal):
    if not frames:
        signal['observability_reason'] = signal['observability_reason'] or 'empty square record has no observable periodic recurrence'
        return
    gain = signal['requested_gain']
    # Nonnegative summation and one division: a conservative gamma(N) bound.
    # N <= artifact bytes / sample bytes, so N*epsilon is always far below 1.
    gamma = frames * 2 ** -52 / (1 - frames * 2 ** -52)
    arithmetic = (gain + signal['sample_error_limit']) * gamma / (1 - gamma)
    uncertainty = signal['representation_error'] + arithmetic
    lower, upper = gain * 10 ** (-0.02 / 20) - uncertainty, gain * 10 ** (0.02 / 20) + uncertainty
    common_reason = signal['observability_reason']
    for channel, row in rows.items():
        mean = row['magnitude_sum'] / frames
        if not lower <= mean <= upper:
            raise SoundBankContractError('INVALID_TONE_WAV',
                'Tone stationary square mean absolute gain differs from requested dB within the numerical policy.',
                details={'stationary_square': signal, 'channel': channel,
                    'measured_gain': mean, 'gain_interval': [lower, upper]})
        reason = ('exact requested square cadence is incompatible; native phase arithmetic precision is unspecified'
            if not row['phase_intervals'] else ('square record has no observable periodic recurrence (fewer than two sign transitions)'
                if row['sign_transitions'] < 2 else None))
        signal['channels'].append({'channel': channel, 'measured_gain': mean,
            'gain_interval': [lower, upper], 'gain_arithmetic_error': arithmetic,
            'max_sample_error': row['max_sample_error'], 'sign_transitions': row['sign_transitions'],
            'exact_cadence_conforms': bool(row['phase_intervals']) if row['anchor'] is not None else None,
            'first_cadence_mismatch_frame': row.get('first_cadence_mismatch_frame'),
            'phase_origin_units': row['anchor'], 'phase_relative_intervals_units': row['phase_intervals']
                if row['anchor'] is not None else None,
            'observability_reason': common_reason or reason})
        signal['observability_reason'] = signal['observability_reason'] or reason


def _observe_square_phase(positive, frame, row, signal):
    # See TONE_STATIONARY_SQUARE.md: after anchoring the first closed semicircle,
    # every constraint is an interval or its two endpoints. State never grows.
    half = signal['phase_half_cycle_units']
    if row['anchor'] is None:
        row['anchor'] = 0 if positive else half
    start = ((0 if positive else half) - signal['phase_step_units'] * frame - row['anchor']) % (2 * half)
    allowed = [[0, half]] if start == 0 else ([[start, half]] if start < half else (
        [[0, 0], [half, half]] if start == half else [[0, start - half]]))
    remaining = []
    for lower, upper in row['phase_intervals']:
        for left, right in allowed:
            if max(lower, left) <= min(upper, right):
                remaining.append([max(lower, left), min(upper, right)])
    row['phase_intervals'] = remaining
    if not remaining:
        # Exact policy incompatibility alone is not native invalidity: matching
        # sources do not pin utility input/phase precision. Never round/fix the
        # frequency or widen edge arcs to turn that uncertainty into acceptance.
        row['first_cadence_mismatch_frame'] = frame


def _sine_signal_policy(observed, args, *, enveloped=False):
    # Explicit numerical conformance, not a claim of a sample-exact native DSP
    # algorithm. SDK AkSineOsc uses an approximate sine; IAkPlugin.h defines the
    # mathematical dB reference. Retained stationary 2023/24/25 WAVs independently
    # exercise these bounds; the 2025 envelope captures reuse this same policy.
    # Neither source establishes utility-wide native error bounds.
    # Reviewed policy: .02 dB gain, .2% shape, two representation units. Native
    # residual maxima were .00123 at unity / .00063 at -6 dB, gain offset <.009 dB;
    # these rounded conformance choices are not a fitted per-file oracle.
    frequency, rate = float(args.get('frequency', 440)), observed['sample_rate']
    gain = 10 ** (float(args.get('sustainLevel', 0)) / 20)
    quantum = 1 / 32768 if observed['sample_format'] == 'int16' else gain * 2 ** -23
    segment_frames = [Decimal(str(args.get(key, default))) * observed['sample_rate'] for key, default in
        (('attackTime', 0), ('sustainTime', 1), ('releaseTime', 0))]
    reason = None
    if float(args.get('sampleRate', 48000)) != rate:
        reason = 'fractional native sample-rate interpretation remains unresolved'
    elif enveloped and (any(frames != frames.to_integral_value() for frames in segment_frames)
            or sum(segment_frames) != observed['frames']):
        reason = 'fractional native envelope segment/frame interpretation remains unresolved'
    elif not enveloped and Decimal(str(args.get('sustainTime', 1))) * rate != observed['frames']:
        reason = 'fractional native sustain/frame interpretation remains unresolved'
    elif frequency >= rate / 2:
        reason = 'sampled frequency is aliased or at the Nyquist degeneracy'
    signal = {'policy': 'stationary-sine-numerical-conformance-v1',
        'reference': 'requested digital sine; phase is unparameterized; not bit-exact or unique analog origin',
        'frequency_hz': frequency, 'angular_step': math.tau * frequency / rate,
        'requested_gain': gain, 'gain_tolerance_db': 0.02, 'shape_tolerance_relative': 0.002,
        'representation_error': 2 * quantum,
        'sample_error_limit': gain * (0.002 + 10 ** (0.02 / 20) - 1) + 2 * quantum,
        'observability_reason': reason, 'channels': []}
    if enveloped:
        signal.update(policy='sine-envelope-numerical-conformance-v1',
            reference='requested fixed-frequency/gain digital sine with linear-amplitude segments; independent unparameterized phase per segment; not a bit-exact native algorithm',
            phase_relationship_checked=False,
            envelope_model='attack n/N; sustain 1; release 1-n/N for integral-frame segments')
        start = 0
        signal['segments'] = []
        for name, frames in zip(('attack', 'sustain', 'release'), segment_frames):
            count = int(frames)
            signal['segments'].append({'name': name, 'start_frame': start, 'frames': count,
                'observability_reason': None, 'channels': []})
            start += count
    return signal


def _envelope_at(signal, frame):
    for index, segment in enumerate(signal['segments']):
        if segment['start_frame'] <= frame < segment['start_frame'] + segment['frames']:
            offset = frame - segment['start_frame']
            amplitude = offset / segment['frames'] if segment['name'] == 'attack' else (
                1 - offset / segment['frames'] if segment['name'] == 'release' else 1)
            return index, segment, amplitude
    raise _invalid('Tone WAV frame lies outside the requested integral envelope segments.')


def _fit_sine_channels(observed, silence_mask, projections, gram, signal, target, frames):
    ss, cc, sc = gram
    determinant = ss * cc - sc * sc
    # Small eigenvalue gives the actual coefficient sensitivity to bounded
    # quantization. No request rate/frequency/gain is prohibited by this check.
    largest = (ss + cc + math.hypot(ss - cc, 2 * sc)) / 2
    smallest = determinant / largest if largest else 0
    if smallest <= largest * 1e-12:
        target['observability_reason'] = 'sampled sine/cosine reference is numerically rank deficient'
        return None
    uncertainty = signal['representation_error'] * math.sqrt(frames / smallest)
    target['gain_representation_error'] = uncertainty
    gain = signal['requested_gain']
    if gain <= uncertainty:
        target['observability_reason'] = 'requested amplitude cannot be distinguished from sample quantization'
        return None
    rows = {}
    for channel, (ys, yc) in enumerate(projections):
        if silence_mask & (1 << channel):
            continue
        a, b = (cc * ys - sc * yc) / determinant, (ss * yc - sc * ys) / determinant
        amplitude = math.hypot(a, b)
        lower, upper = gain * 10 ** (-0.02 / 20) - uncertainty, gain * 10 ** (0.02 / 20) + uncertainty
        if not lower <= amplitude <= upper:
            raise SoundBankContractError('INVALID_TONE_WAV',
                f'Tone sine channel {channel} gain differs from requested dB within the numerical policy.',
                details={'sine_envelope' if 'segments' in signal else 'stationary_sine': signal,
                    'segment': target.get('name'), 'channel': channel,
                    'measured_gain': amplitude, 'gain_interval': [lower, upper]})
        row = {'channel': channel, 'measured_gain': amplitude, 'gain_interval': [lower, upper],
            'phase_radians': math.atan2(b, a), 'max_sample_error': 0.0, 'rms_sample_error': 0.0}
        rows[channel] = row
    return rows


def _check_stationary_sine(stream, data, observed, silence_mask, projections, gram, signal):
    rows = _fit_sine_channels(observed, silence_mask, projections, gram, signal, signal, observed['frames'])
    if rows is None:
        return
    gain = signal['requested_gain']
    squares = [0.0] * observed['channels']
    phase_components = {channel: (math.cos(row['phase_radians']), math.sin(row['phase_radians']))
        for channel, row in rows.items()}
    for index, (sample,) in enumerate(_audio_samples(stream, data, observed)):
        channel = index % observed['channels']
        if channel == 0:
            phase = math.remainder(signal['angular_step'] * (index // observed['channels']), math.tau)
            sine, cosine = math.sin(phase), math.cos(phase)
        if channel not in rows:
            continue
        cos_phase, sin_phase = phase_components[channel]
        expected = gain * (sine * cos_phase + cosine * sin_phase)
        actual = sample / 32768 if observed['sample_format'] == 'int16' else sample
        error = abs(actual - expected)
        if not math.isfinite(error) or error > signal['sample_error_limit']:
            raise SoundBankContractError('INVALID_TONE_WAV',
                f'Tone stationary sine channel {channel} sample {index} differs from the requested fixed-frequency/gain waveform within the numerical policy.',
                details={'stationary_sine': signal, 'channel': channel, 'sample_index': index,
                    'measured_gain': rows[channel]['measured_gain'],
                    'sample_error': error if math.isfinite(error) else 'non-finite'})
        rows[channel]['max_sample_error'] = max(rows[channel]['max_sample_error'], error)
        squares[channel] += error * error
    for channel, row in rows.items():
        row['rms_sample_error'] = math.sqrt(squares[channel] / observed['frames'])
    signal['channels'] = list(rows.values())


def _check_sine_envelope(stream, data, observed, silence_mask, statistics, signal):
    # Fixed envelope-weighted bases: only phase is free, separately per segment.
    # Fit gain is compared to requested dB, never used as the sample reference.
    fitted = []
    for segment, stats in zip(signal['segments'], statistics):
        rows = _fit_sine_channels(observed, silence_mask, stats['projections'], stats['gram'],
            signal, segment, segment['frames']) if segment['frames'] else {}
        fitted.append(rows)
        if rows is None:
            signal['observability_reason'] = signal['observability_reason'] or (
                segment['name'] + ': ' + segment['observability_reason'])
        else:
            segment['channels'] = list(rows.values())
    squares = [[0.0] * observed['channels'] for _ in signal['segments']]
    components = [{channel: (math.cos(row['phase_radians']), math.sin(row['phase_radians']))
        for channel, row in (rows or {}).items()} for rows in fitted]
    for index, (sample,) in enumerate(_audio_samples(stream, data, observed)):
        channel = index % observed['channels']
        if channel == 0:
            segment_index, segment, amplitude = _envelope_at(signal, index // observed['channels'])
            phase = math.remainder(signal['angular_step'] * (index // observed['channels']), math.tau)
            sine, cosine = math.sin(phase), math.cos(phase)
        actual = sample / 32768 if observed['sample_format'] == 'int16' else sample
        limit = (signal['sample_error_limit'] - signal['representation_error']) * amplitude + signal['representation_error']
        # Phase uncertainty cannot conceal a magnitude impossible for any phase,
        # particularly a nonzero sample at a zero-weight attack frame.
        if abs(actual) > signal['requested_gain'] * amplitude + limit:
            raise SoundBankContractError('INVALID_TONE_WAV',
                f'Tone sine {segment["name"]} channel {channel} sample {index} exceeds the requested envelope magnitude for every unparameterized phase.',
                details={'sine_envelope': signal, 'channel': channel, 'segment': segment['name'],
                    'sample_index': index, 'sample_magnitude': abs(actual),
                    'maximum_magnitude': signal['requested_gain'] * amplitude + limit})
        if channel not in components[segment_index]:
            continue
        cos_phase, sin_phase = components[segment_index][channel]
        expected = signal['requested_gain'] * amplitude * (sine * cos_phase + cosine * sin_phase)
        error = abs(actual - expected)
        # Same stationary numerical policy, scaled by the fixed envelope; the
        # two representation units remain absolute at quiet segment boundaries.
        if not math.isfinite(error) or error > limit:
            raise SoundBankContractError('INVALID_TONE_WAV',
                f'Tone sine {segment["name"]} channel {channel} sample {index} differs from the requested fixed-frequency/gain/linear-amplitude envelope within the numerical policy.',
                details={'sine_envelope': signal, 'channel': channel, 'segment': segment['name'],
                    'sample_index': index, 'sample_error': error if math.isfinite(error) else 'non-finite',
                    'sample_error_limit': limit})
        row = fitted[segment_index][channel]
        row['max_sample_error'] = max(row['max_sample_error'], error)
        squares[segment_index][channel] += error * error
    for segment_index, segment in enumerate(signal['segments']):
        for row in segment['channels']:
            row['rms_sample_error'] = math.sqrt(squares[segment_index][row['channel']] / segment['frames'])



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
