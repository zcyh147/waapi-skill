"""Deterministic RIFF bytes shared by developer-owned WAV fixtures."""

def _tone_wav_bytes(*, floating=False, samples=None, rate=8000, channels=2, extra=b'', fmt_override=None):
    import struct
    # Four known audio frames. This fixture is independent of the Gateway compiler.
    if samples is None:
        samples = [0.0 if floating else 0] * 8
    audio = struct.pack('<' + ('f' if floating else 'h') * len(samples), *samples)
    width = 4 if floating else 2
    fmt = fmt_override if fmt_override is not None else struct.pack('<HHIIHH',
        3 if floating else 1, channels, rate, rate * channels * width, channels * width, width * 8)
    body = b'WAVEfmt ' + struct.pack('<I', len(fmt)) + fmt + (b'\0' if len(fmt) % 2 else b'')
    body += b'data' + struct.pack('<I', len(audio)) + audio + extra
    return b'RIFF' + struct.pack('<I', len(body)) + body

def _riff_chunk(kind, payload):
    import struct
    return kind + struct.pack('<I', len(payload)) + payload + (b'\0' if len(payload) % 2 else b'')

def _tone_marker_chunks(rows):
    import struct
    # Known RIFF fixture: cue IDs deliberately differ from positions/order.
    cue = struct.pack('<I', len(rows)) + b''.join(struct.pack('<II4sIII', identity, 0, b'data', 0, 0, frame)
        for identity, frame, _ in rows)
    labels = b'adtl' + b''.join(_riff_chunk(b'labl', struct.pack('<I', identity) + label)
        for identity, _, label in rows if label is not None)
    return _riff_chunk(b'cue ', cue) + _riff_chunk(b'LIST', labels)
