# Stationary triangle sufficient-witness conformance — #193

This extends the existing public Gateway artifact verifier with a sufficient
digital triangle proof. It is not a complete feasible-phase solver, a native
DSP/error theorem or completion of triangle/#193 coverage. A missing witness
remains partial; the utility's input and internal phase precision are unknown.
Triangle envelopes, noise, nonstationary square, fractional interpretation and
remaining native/settings/representation evidence retain their obligations.

## Fixed reference and two witnesses

Let r=p/q be the exact decimal request frequency divided by the integral
observed sample rate. Use the continuous periodic triangle

`T(u) = 1 - 4 abs(((u + 1/4) mod 1) - 1/2)`.

Keep requested G=10^(sustainLevel/20), the existing .02 dB gain and .002
relative shape policy, and R=two representation units (PCM16: 2/32768;
float32: 2 G 2^-23). The full-sample budget remains
`E = G (.002 + 10^(.02/20) - 1) + R`. These numerical policy values are not
native implementation claims and are not tuned to the retained triangle.

For each active channel take its first frame sample x0. Set z=clip(x0/G,-1,1)
only for seeding. The ascending and descending inverse branches give phases
`z/4 mod 1` and `(1/2-z/4) mod 1`. Deduplicate equal phases at an extremum.
These are the only candidates: no later seed, phase grid, edge correction,
frequency fitting or observed-gain normalization. Original samples are never
clipped for verification. Every sample must satisfy `abs(x-G T(phi+n r))<=E`
for one unchanged candidate per channel.

For an ideal triangle with at most one representation unit of sample error,
one inverse branch has circular phase error at most one unit/(4G). Since T
is 4-Lipschitz, seed error contributes at most one additional representation
unit to subsequent sample residuals. This explains the two-unit allowance for
ideal quantized controls. Approximate signals may have another feasible phase
yet neither seed may pass: sufficient-witness failure does not prove complete
phase infeasibility or native invalidity.
Nearby frequencies can be numerically indistinguishable within E on a finite
record. The exact requested cadence still owns the reference; passing this
policy never identifies a unique generating frequency or native precision.

## Separate signed gain and observability

For each fixed candidate basis t_n=T(phi+n r), accumulate exactly
`Q=sum(t_n^2)`, `P=sum(x_n t_n)` and `L=sum(abs(t_n))`. Observe the signed
projection A=P/Q; compare it with
`[G 10^(-.02/20)-R L/Q, G 10^(.02/20)+R L/Q]`.
R L/Q bounds the projection's sensitivity to the same two-unit sample/seed
representation allowance. Never substitute A for G in sample comparisons.
One candidate must pass both checks. A different gain witness cannot rescue
a phase whose full-sample check failed. Q=0 or uncertainty at least G remains
quantization-inconclusive. Gain rejection only rejects this sufficient witness;
it does not establish a phase-independent native gain defect.

Require at least two observed sign transitions per active channel for sampled
recurrence; an exact zero is nonnegative, as in the existing square policy.
Short/no-recurrence records remain partial even when a seed can explain them.
Aliased/Nyquist and fractional rate/frame interpretations remain partial.
Each channel retains its own reason, so one partial channel cannot suppress
another channel's observations or independent failures.

Every active sample also receives the phase-independent bound `abs(x)<=G+E`.
Outside-bound samples, nonfinite values and nonzero requested-silent channels
fail independently, including after both seeds have failed or an observation
is partial. Full artifact scanning continues; no native write is replayed.

## Exact arithmetic and resource proof

After the existing numerical G/E/tolerance values are computed, retain their
exact binary rational values. A finite PCM16/float32 sample is exact: use one
common sample denominator S=32768 or 2^149 respectively. For each seed take
`D=lcm(4,q,phase.denominator)` and store its phase and r as integral units
modulo D. T then has the same fixed denominator D. Residual comparisons use
cross-multiplied integers. P, Q and L use integer sums with denominators S D,
D^2 and D. Gain comparisons and representation uncertainty remain rational.
Only diagnostic display converts ratios to floats; it never decides a pass.

The closed request bounds frequency to [1,22000] as a finite Python number,
rate to [300,192000], and sustain level to [-100,0]. The shortest decimal
spelling of a supported binary64 frequency has at most 17 significant digits;
with frequency at least 1, its denominator is at most 10^16. Thus q is below
2^71. G is at least 10^-5; its binary denominator is below 2^70 and its
numerator below 2^53. A float32 sample denominator divides 2^149; a seeded
phase denominator is below 2^204. Consequently D is below 2^277 (a conservative
320-bit bound suffices). The independent level check keeps sample numerators
below 2^151. The existing 512 MiB artifact bound gives fewer than 2^29 frames.
P/Q/L integer sums remain below 800 bits and the rational gain/comparison
intermediates below a conservative 2048 bits. These bounds are consequences of
existing inputs/artifact policy; no new accepted-input restriction is added.

At most two fixed candidate rows and counters per active channel are retained.
Time is O(samples); state is O(channels), with existing bounded channel counts.
The existing descriptor-owned fixed-block iterator, RIFF/hash/path checks and
exact terminal result/journal remain the only workflow. Candidate diagnostics
are bounded and do not include audio or growing phase sets. This avoids the
unproven transfer of the square semicircle intersection bound: triangle
tolerance preimages have two arcs whose repeated intersections can fragment.

## Sources and evidence boundary

The five pinned native catalogs, matching SDK CHM hashes/source limitations and
original six-case diagnostic protocol are recorded in
[TONE_SIGNAL_COLLECTION.md](TONE_SIGNAL_COLLECTION.md). The 2023.1/2024.1/2025.1
triangle/frequency/dB/seconds/depth fields match; 2024 adds anonymous/channel
selection and 2025 adds markers. Both retained Console and Authoring catalogs
omit this URI in 2021.1/2022.1. These are pinned reflection facts, not absence
claims for other builds or alternative ways to create tones. Matching SDK
`IAkPlugin.h:1422` documents the conventional dB conversion but establishes no
utility linkage or numeric type. Storage depth cannot establish phase precision.

The byte-identical Console 2025.1.7.9143 triangle original is 48,092 bytes,
SHA-256 `9ce8be11208ef9f8b5923f5e1439cdd1641390056285f26eed9d7b802bff18d2`,
transaction `tx1-avygzzwdkaa3h2twp1tn`, from candidate
`005afc69e79a2101d72bd24abd49164c3cf7e1fe` and original receipt SHA-256
`f368ce72b4b4a30982c06ff7d5b0e3d841784671b32118aded8e939ac78b566d`.
It is mono extensible float32, 440 Hz/48 kHz, -6 dB, 0/.25/0 seconds. Its
nominal-G phase-zero maximum residual is .000528904999724189, with observed
peak -6.008996257561076 dB. The unexplained gain offset stays visible. No
measured normalization or calibration enters the oracle.

Its original collection is unchanged: diagnostic/blocked, signal unverified,
partial artifact, no business-effect/coverage credit. Replaying its copied bytes
through a fake public workflow adds program evidence only. No new native,
Windows, Fresh, other build/settings or 2023/2024 triangle effect is established.
No missing witness is relabelled native absence; complete phase-search behavior
and required remaining branches/evidence remain #193 work.
