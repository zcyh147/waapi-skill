# Stationary square numerical conformance — #193

The public Gateway artifact verifier checks a digital square at the frozen
requested frequency and gain, with one unparameterized phase per active
channel. It does not identify the native DSP algorithm or a unique analog
origin. Triangle, noise and non-sine envelopes remain separate obligations.

## Phase intersection and mathematical bound

Let the exact decimal request frequency divided by the integral observed
sample rate reduce to p/q cycles per frame. Represent phase in units of
1/(2q) cycle, so a full cycle is 2q and frame n advances by the exact integer
2pn modulo 2q. Phase itself can be any real number in this coordinate; it is
not restricted to integer units. No floating point phase progression or phase
grid is needed. The allowed positive phase arc is [0,q], and the negative arc
is [q,2q], modulo 2q. Either limiting sign is permitted only at the exact
discontinuities. No adjacent sample, transition window or per-edge adjustment
receives that exception. Initial phase and exact-edge polarity are not native
behavior claims.

Use the first observed sign to anchor its closed allowed half-cycle as [0,q].
For a subsequent sign, its allowed arc starts at an exact integer s modulo
2q relative to that anchor. Its intersection with [0,q] is:

- [0,q] when s=0;
- [s,q] when 0<s<q;
- the two points {0,q} when s=q;
- [0,s-q] when q<s<2q.

Intersect these constraints for every sample. The feasible state is always
one closed interval or at most the two endpoints {0,q}; it cannot grow with
frame count. Empty intersection disproves a common phase in the exact model. A surviving
intersection proves membership at the requested digital cadence, without
fitting frequency. The two-endpoint case preserves exact ties rather than
approximating them. State is O(channels), time O(samples), within the existing
512 MiB artifact and bounded channel limits. Exact integer arithmetic owns
all phase decisions; conversion to a displayed phase interval is diagnostic.

At least two observed sign transitions are required to claim sampled periodic
recurrence. Short records without recurrence stay partial even if a phase
could explain them. Aliased/Nyquist, fractional-rate/frame and
quantization-indistinguishable observations likewise stay partial. This is
not rejection of a valid request or evidence of native absence. Independent
known level, finite-value and silent-channel checks still apply.

## Gain and source boundary

Keep requested G=10^(sustainLevel/20). Reuse the previously reviewed .02 dB
gain, .002 relative shape and two representation-unit allowances without
retuning them. Check every active magnitude against requested G with the
combined sample budget. Independently check mean absolute level against the
.02 dB gain interval plus representation uncertainty. Nonnegative summation
roundoff is bounded by gamma(N)=N*epsilon/(1-N*epsilon), including division;
N is bounded by the artifact size. An observed gain is never substituted for
G, and neither frequency nor per-edge phase is fitted.

The matching reflected 2023.1/2024.1/2025.1 schemas name square, frequency,
dB sustain and segment seconds but give no DSP/error specification. Matching
2025 SDK `IAkPlugin.h:1422` gives the mathematical dB reference; it does not
establish utility linkage. Exact CHM/catalog hashes and source limitations
are recorded in [TONE_SIGNAL_COLLECTION.md](TONE_SIGNAL_COLLECTION.md).

An empty exact phase intersection remains partial cadence observability, with
`exact_cadence_conforms=false` and the first incompatible frame. The sources
do not pin utility input or phase arithmetic precision. Even an input exactly
representable in a common SDK type cannot establish exact internal phase
arithmetic. A nearly equal requested frequency can therefore fail the exact
mathematical model without proving an invalid native effect. Do not infer a
precision from the WAV depth or the separate Tone plug-in, round the request,
fit a different frequency, widen transition arcs or turn that uncertainty into
acceptance. Known magnitude, independent mean-gain, finite-value and silent
channel contradictions still fail, including when cadence remains partial.

The retained Console 2025.1.7.9143 square is mono float32, 440 Hz/48 kHz,
-6 dB and 0/.25/0 seconds. Its levels are +/-0.5006684064865112, about
-.00899626 dB relative to the requested gain: inside the already reviewed
.02 dB policy, far outside float32 representation error. The unexplained
offset is retained, not normalized away. The original six-case collection
remains diagnostic/partial. Replay through a fake adds program evidence only.
2021.1/2022.1 are pinned route-absent; 2023.1/2024.1 square effects remain
native-uncollected. Other settings, hosts/builds, Windows and Fresh evidence
are not inferred from this one original.
