# Bounded sine-envelope verification — #193

This slice extends `ak.wwise.debug.generateToneWAV` through the existing public
Gateway artifact verifier. It does not complete Tone waveform coverage.
Triangle, noise, nonstationary square, fractional rate/segment rounding and
remaining marker or channel-representation obligations stay open. Stationary
square has its own [bounded conformance successor](TONE_STATIONARY_SQUARE.md).
Stationary triangle has a separate [sufficient-witness successor](TONE_STATIONARY_TRIANGLE.md);
complete triangle phase search and native precision remain unresolved.

## Observed model and accepted verification policy

The three unaltered Console 2025.1.7.9143 sine-envelope files collected on
`005afc69e79a2101d72bd24abd49164c3cf7e1fe` are preserved below
`tests/fixtures/tone/console-2025.1.7.9143/envelopes/`. Their manifest binds each
original transaction, byte count and SHA-256 to the original receipt
`f368ce72b4b4a30982c06ff7d5b0e3d841784671b32118aded8e939ac78b566d`.
No original outcome is changed: collection protocol passed, while every
original signal verification remained partial and the diagnostic category
received no business acceptance credit.

Against the separately retained same-build stationary sine, multiplying by
linear-amplitude attack n/N and release 1-n/N has maximum residuals
3.9935111995070827e-8, 1.2970632978781538e-7 and 1.202440924052972e-7 for
attack-only, release-only and combined files. The squared-envelope alternative
differs by about .1251. These are observed residuals, not a native-wide error
bound or a proof of the utility's exact DSP implementation.

The selected .05/.10/.075-second segments contain exactly 22/44/33 cycles at
440 Hz. They cannot distinguish phase continuity from phase reset. The reviewed
policy therefore allows independent unparameterized phase in each segment and
explicitly checks no phase relationship between segments. No further native
phase probe is required for this policy. Bit-exact native generation and unique
analog origin are not claimed.

## Existing verifier extension

The request fixes frequency, sustain gain and all three segment lengths. For
integral-frame segments the sample reference uses linear-amplitude attack n/N,
sustain 1 and release 1-n/N. Each segment fits only the phase of sine/cosine bases
weighted by that fixed envelope. The fitted amplitude is checked against the
requested dB and is never substituted for requested gain in the full sample
comparison. Frequency and envelope are never fitted or shifted.

The stationary policy is reused: .02 dB gain tolerance, .002 relative shape
tolerance and two representation units (PCM16 or float32). The envelope scales
the stationary shape/gain error allowance; the representation allowance stays
absolute at quiet boundaries. These tolerances predate the new captures and
were not fitted to their residuals.

The weighted Gram matrix's smallest eigenvalue bounds coefficient sensitivity
to sample representation error. A numerically rank-deficient segment or gain
indistinguishable from quantization remains partial. Other observable segments
still undergo gain and full-sample checks. An independent magnitude bound also
rejects samples impossible for every phase, including nonzero zero-weight
attack frames, even when that segment's phase is unobservable. Aliased or
fractional-rate/frame interpretations remain partial rather than guessed.

Audio remains descriptor-owned and scanned in bounded blocks. Two full sample
passes collect the fixed-size statistics and verify the signal; at most three
segments and the existing bounded channel set are held in memory. Existing
path ownership, before/after file stability, preview binding, configuration,
authorization and execute-once behavior are unchanged. The public schema
discloses `sine-envelope-numerical-conformance-v1`, its tolerances and its phase
boundary; successful results expose `wav.sine_envelope` per-segment observations.
Stationary requests retain `wav.stationary_sine` and their existing policy.

## Scope and evidence

The route is absent from the pinned 2021.1/2022.1 catalogs, with existing offline
unavailable-route controls preserved. The 2023.1, 2024.1 and 2025.1 contracts all
contain the same relevant sine/envelope fields. Independent analytic program
controls exercise each of those three public Gateway lanes in PCM16 and
float32. This is program accounting; new native envelope captures exist only
for Console 2025.1.7.9143. Native 2023/2024 envelope effects remain uncollected,
and no native Windows or other patch-build equivalence follows.

The public Preview/execute-once/verify tests cover all three preserved native
files, independent phase-varied analytic signals, wrong curve, swapped segment
lengths with unchanged total duration, gain, frequency, silence, missing
envelope and late corruption. Separate controls retain rank/quantization/
fractional/alias partial states and prove an observable segment cannot hide
behind another segment's partial result. The largest supported standard layout
also emits the exact final `agent_result` through `gateway.main` within the
ordinary 24 KiB terminal ceiling. Existing stationary native-fixture and
corruption controls cover the shared fitter.

The six-case diagnostic collector stays diagnostic on this successor. Its
synthetic wrong sine envelopes now fail verification, while unimplemented
non-sine signals stay partial. Its original native records remain untouched.
This runtime successor has no new native run, full gate or Fresh evidence.
