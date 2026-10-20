# Next bounded Tone signal observations — #193

This is a source-first review package for a collector, not native launch
authorization or waveform/envelope acceptance. The existing stationary sine
verifier and original native receipts remain unchanged. New observations are
needed before implementing the remaining signal checks.

## Evidence already available

`operation_tone.py` implements full-sample stationary sine conformance at the
public Gateway verification boundary, with explicit frequency, gain, shape and
representation tolerances. The retained fixture manifest at
`tests/fixtures/tone/console-2025.1.7.9143/manifest.json` binds four originals:
PCM16/float32 at 0/-6 dB, mono, 440 Hz, 48 kHz, 0/.25/0-second envelope.
The recorded 2023/2024 captures match those 2025 bytes exactly. Those captures
contain no other waveform or nonzero attack/release. R40's existing public
wrong-frequency, gain, shape and accidental-envelope controls already exercise
the stationary verifier; repeating those controls adds no missing native fact.

## Exact native sources

The sealed Console catalogs in `resources/native-catalog/<version>/` establish
the route's availability and exact schema; they do not establish a DSP formula.
All paths here are relative to `skills/waapi-skill/` unless otherwise stated.

| Release | Reflected Console build | `generateToneWAV` |
| --- | --- | --- |
| 2021.1 | 2021.1.14.8108 | absent |
| 2022.1 | 2022.1.19.8584 | absent |
| 2023.1 | 2023.1.19.8928 | present; no successor collection authorized |
| 2024.1 | 2024.1.13.9056 | present; no successor collection authorized |
| 2025.1 | 2025.1.7.9143 | proposed successor collection only |

2025 Console catalog content SHA-256:
`7b3e3bc255bbc425bde6820e44bfdda6302a42da623e987e9ab4414651a36dc8`.
Canonical exact URI schema SHA-256:
`ad0c920e1ac9ad1f3278aa2056b0fdb8ab114b7dc88992160e96ad0bc91faa9c`.
The collector records both and checks live `getInfo` against the catalog's
exact build and Console host before generating any file.

Matching primary documentation was read directly from
`/Applications/Audiokinetic/Wwise2025.1.7.9143/SDK/Help/WwiseSDK-Windows.chm`:

- CHM SHA-256: `c54b729388040e9df540a2f58d0d0eda966ac5da6410d3cd715ae256d898166d`.
- Extracted member `ak_wwise_debug_generatetonewav.html`, SHA-256:
  `a2c1da87e77b2a2ec91a72f23aa722a93a40d8575524bc3cfa6e14bfa5d0dd0e`.

The page identifies SDK 2025.1.7. It documents seconds for the three envelope
segments, dB attenuation for sustain, and the same five waveform choices as
reflection. It does not specify envelope curve, phase continuity/reset,
triangle/square synthesis, noise seed/distribution or quantization. The separate
Tone Generator plug-in's DSP examples are not proof of this utility's algorithm.

## Six observations in one owned sandbox

Every case explicitly requests mono (`1.0`), float32, 48,000 Hz, 440 Hz and
-6 dB. Markers, anonymous layout and channel selection remain omitted. Avoiding
a waveform × depth × gain crossproduct keeps the next experiment bounded;
PCM16, other gains and other builds retain their remaining evidence obligations.

| Case name | Public waveform | Attack/sustain/release seconds | Missing fact sought |
| --- | --- | --- | --- |
| triangle-stationary | triangle | 0/.25/0 | actual periodic shape and phase behavior |
| square-stationary | square | 0/.25/0 | actual edge shape and amplitude behavior |
| white-noise-stationary | white_noise | 0/.25/0 | actual bounded signal realization; no seed/distribution inference from one file |
| sine-attack-only | sine | .05/.10/0 | attack curve and entry into sustain, without release |
| sine-release-only | sine | 0/.10/.075 | release curve and tail, without attack |
| sine-attack-release | sine | .05/.10/.075 | composition and phase continuity across both boundaries |

Unequal attack/release times separate swapped/ignored segments. Isolated edges
permit independent comparisons; the combined case tests whether those edges
compose. Analysis must compare candidate curves and boundary samples without
assuming linear amplitude, linear dB or a phase reset. A sample difference may
disprove a candidate formula; six files cannot establish utility-wide bounds.

## Execution and evidence boundary

The only native test node is
`tests/destructive/test_gateway_workflow_transaction_matrix.py::test_tone_waveform_envelope_console_characterization`.
Its private helper accepts only reviewed 2025.1; the test wrapper skips other
versions with an explicit collection-scope reason. Public route availability
for older versions remains unchanged. Root owns the matching native slot and
must review the frozen source/roster before any launch.

The existing managed lifecycle creates one private SampleProject copy and one
isolated output directory. Each case uses the public business Draft, check,
immutable Preview, show, confirm, execute once, verify and final show. The
Gateway owns native arguments, including `white_noise` → `whiteNoise`.
No raw client, alternate dispatch, retry or direct project change is added.

The expected public call count is 57: initial status/schema, nine calls per
case, final status. The call ceiling rises from 48 to 64 for this successor;
the old four-case collector retains its 48 ceiling. Six distinct WAV names
and transaction IDs bind the requested cases. All other ceilings are reused:
256 KiB per public reply, 8 MiB total replies, 8 MiB per archived file,
512 native receipt files/32 MiB native receipts, 72 MiB aggregate archive and
256 KiB summary receipt. Nominal audio is 249,600 bytes total before headers;
independent archive and receipt ceilings still apply if native output differs.

Outputs are copied exclusively before verification can stop collection, then
all new native receipts and exact public replies are archived with byte hashes.
The receipt seals catalog/schema, exact live identity, config digest, source
path, immutable transaction records and the required final lifecycle row.
The final row must independently establish unchanged source hash/mtime/tree,
the exact six transaction IDs and owned process/sandbox cleanup. A prepared row
does not prove cleanup. Missing files, reply identity drift or unknown native
outcomes stop collection and retain original failure evidence without replay.

Collection is diagnostic: even valid WAVs or successful verification phases
leave its category blocked, `signal_verified=false`,
`business_effect_verified=false` and no coverage credit. Malformed originals
are retained unchanged with their verification failures. Subsequent verifier
work requires source-reviewed interpretation and public positive plus
wrong-effect negatives; current native verification is not relabelled.

The original 2025.1.7.9143 collection subsequently completed as characterization
only on `005afc69`: 57 public calls, six separate transactions and six immutable
WAVs, with full lifecycle closure. Its envelope durations are commensurate with
440 Hz, so the phase continuity/reset question remains unobserved. See the
[bounded sine-envelope successor](TONE_SINE_ENVELOPE.md) for the reviewed
phase-independent numerical policy and separate program evidence. The original
collection's partial outcomes and all earlier failures remain unchanged.

The [stationary square successor](TONE_STATIONARY_SQUARE.md) reuses the untouched
square original for program regression. It checks requested gain and full-sample
exact digital cadence under a disclosed numerical policy. An incompatible
exact cadence remains partial because utility phase arithmetic precision is not
specified; it is never rounded into acceptance or labelled native invalidity.
Triangle, noise and non-sine envelopes remain unfinished. No new collection or
relabelled original native outcome follows from this successor.
