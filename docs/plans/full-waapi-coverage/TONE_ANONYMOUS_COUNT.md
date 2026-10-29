# Anonymous channel-count override: source review and one probe — #193

The public Tone declaration formerly rejected every non-silent Ambisonics layout
even when explicit anonymous mode replaced that layout's type. The matching
sources justify admitting that explicit override through the existing closed
Gateway. They do not prove that the native Tone utility executes the combination;
native legality and observed effects remain pending the single reviewed probe.
The accepted sine-envelope implementation at `70f3ff0c` is preserved separately.

## Exact primary sources

Both matching SDK CHM members `ak_wwise_debug_generatetonewav.html` describe
`setAnonymous` as replacing the channel configuration type while retaining its
channel count. They separately restrict non-silent signals in genuine Ambisonic
configurations. The native utility's implementation is not disclosed by that
description, so the override combination still needs an actual observation.

| Source | SHA-256 |
| --- | --- |
| Wwise2024.1.13.9056/SDK/Help/WwiseSDK-Windows.chm | aa6b467caae07c2363806adc1dadeed8df7a29c4bdf2d23fd629126208054364 |
| 2024 extracted Tone member | a64edac8294e041abbcfae69dae9bb18e65f9af2481985f235c4ef3874f43af1 |
| Wwise2025.1.7.9143/SDK/Help/WwiseSDK-Windows.chm | c54b729388040e9df540a2f58d0d0eda966ac5da6410d3cd715ae256d898166d |
| 2025 extracted Tone member | a2c1da87e77b2a2ec91a72f23aa722a93a40d8575524bc3cfa6e14bfa5d0dd0e |
| 2024 SDK/include/AK/SoundEngine/Common/AkSpeakerConfig.h | ea2c7b914f4e36208a275ac093e449ef2c9498f55d00bf789669ca4a35cc4348 |
| 2025 matching header | bbd88f64c14827b929e3608b145cc75cfbf4a846dc12db7827c5df5dbac62d61 |

The installed roots are `/Applications/Audiokinetic/<build>/`. In the 2025 header,
`AkChannelConfig::SetAnonymous` at line 535 sets the requested count, anonymous
type and zero speaker mask. `SetAmbisonic` is a distinct type assignment. The
comment at line 435 specifies the full-sphere channel-count formula `(N+1)^2`;
fifth order therefore supplies 36 channels. The 2024 helper at line 530 assigns the
same anonymous type/count/mask semantics. These helpers corroborate the type
distinction; they do not establish the Tone utility's actual internal call order.

The packaged sealed Console catalog pins are unchanged:

| Build | Catalog content SHA-256 | Exact Tone schema SHA-256 |
| --- | --- | --- |
| 2024.1.13.9056 | 7f7e2f12e5a6fa369d33edc24f4aaa5dcf7fcaa48d5a357d7ddec33481840b89 | dcf2e7cc7f0331899c502a059db37d46a4cafe420f745c1f650b3a646bbbc411 |
| 2025.1.7.9143 | 7b3e3bc255bbc425bde6820e44bfdda6302a42da623e987e9ab4414651a36dc8 | ad0c920e1ac9ad1f3278aa2056b0fdb8ab114b7dc88992160e96ad0bc91faa9c |

The field is absent from the pinned 2023.1 schema; the Tone URI is absent from
2021.1/2022.1. Those boundaries are unchanged. The proposed native observation
targets only 2025.1.7.9143; 2024 native behavior remains unobserved.

## Bounded implementation and program proof

The public declaration permits the combination only when
`anonymous_channels is True`, available in 2024/2025. Omission and explicit false
retain the genuine Ambisonic non-silence restriction. The public schema explains
that layout order chooses count when anonymous mode replaces the type. Native
arguments remain Gateway-owned; the original layout and explicit true override
are both preserved in the immutable request.

Actual `gateway.main` verification for 36 channels measured 8348/8347 UTF-8 bytes on
the 2024/2025 fake-client paths within the existing 24576-byte ordinary limit.
The existing digest projection preserves all 108 segment/channel observation rows
in the durable verification event and exposes their canonical digest. It does
not truncate channel proof or alter the exact final `agent_result`.

A separate permitted large-marker request exposed the same unconditional
restriction in Tone's exceptional terminal-budget eligibility check. Before the
matching conditional fix, a 40153-byte success projection failed its 22528-byte
fixed allowance. The corrected check uses the existing 286720-byte bounded Tone
allowance for the already supported large exact request. No global ceiling or
input bound changes. Public actual-main proof preserves every marker and exact
`agent_result`, with all 108 channel observations durably retained.

False/omitted override controls reject before native dispatch; 2023 rejects its
unavailable field before dispatch. These are program proofs of Gateway behavior,
not proof of native legality. Existing waveform, fractional-rate/frame and other
native-evidence obligations remain open.

## Single native probe for Root review

Proposed node:
`tests/destructive/test_gateway_workflow_transaction_matrix.py::test_tone_anonymous_count_console_characterization`.
Its helper accepts only the reviewed 2025.1 lane and verifies live Console build
against the sealed catalog before any generation. Other native-version wrappers
skip with an explicit probe-scope reason; no public capability is excluded.

Exactly one case in one managed private SampleProject sandbox:

- `channel_layout`: `Ambisonics 5th order`.
- `anonymous_channels`: true; waveform sine; float32; 48000 Hz; 440 Hz; -6 dB.
- Attack .005 s, sustain .01 s, release .0075 s: 240/480/360 integral frames,
  1080 frames total. All 36 channels receive waveform data; no channel mask,
  anonymous layout alternatives, markers, extra cases or native retries.
- One public Draft/check/immutable Preview/show/confirm/execute-once/verify/final
  show. Including initial status/schema and final status, 12 public calls are
  planned under a 16-call cap. There is one expected WAV with 155520 audio bytes
  before native headers and additional chunks.
- Existing ceilings stay 256 KiB per public reply, 8 MiB total replies, 8 MiB per
  archived file, 512 native receipts/32 MiB native receipts, 72 MiB aggregate archive
  and 256 KiB summary receipt. Configuration identity, source hash/mtime/tree,
  exact transaction identity and final lifecycle/process cleanup remain bound.

The existing artifact verifier can check recognized float32 format, exact count 36,
zero/direct-out speaker mask, 48000 Hz, 1080 frames and all 36 channels' three sine
segments under the accepted frequency/gain/linear-envelope numerical policy.
That policy allows independent phase per segment; it checks neither phase
continuity/reset nor the utility's bit-exact DSP/internal configuration type.
The generated file may fail parsing or conformance, or native execution may
reject/lose its response. Every outcome is archived unchanged before diagnosis;
unknown outcomes are never replayed. Source-backed caller admission alone
cannot establish native legality or successful effect.

The collector always remains a diagnostic category with no effect credit.
Even if its phase verifier reports `tone_wav_artifact`, Root must review the
exact original replies, WAV, effect observations and final lifecycle row before
classifying the exercised branch. The fake protocol proves one execution and
complete 36-channel/1080-frame retention, plus unknown-outcome and wrong 35-channel
controls. It reuses the existing Tone collector and owned lifecycle rather than
introducing another native execution framework. No native launch is authorized
merely by this plan or its program tests.
