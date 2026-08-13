# ADR 0002: One model-facing typed input system

- Status: Accepted
- Date: 2026-08-13
- Scope: every packaged WAAPI function, query, Topic, and named operation
- Supersedes: ADR 0001's model-facing Legacy JSON retention decision

## Context

The Gateway now compiles exact-version reflected schemas into bounded typed
facts and Gateway-issued handles. Zero-input, concise inline, recursive Draft,
query, Topic, file, Lua, and compound mutation shapes all use that Core while
retaining their distinct outer lifecycles. The Skill has not been released and
has no external compatibility obligation.

Keeping raw request documents beside the typed system would preserve two normal
input languages, duplicate validation paths, and leave a generic escape hatch
that contradicts Gateway-Owned Request Construction.

## Decision

The packaged Skill exposes one model-facing typed input system.

- `request-schema`, `operation-schema`, `query-schema`, and `topic-schema`
  return the sole continuation for the exact configured Wwise version.
- The Gateway selects zero, inline, or Draft composition; the Agent follows the
  returned continuation and never chooses an input architecture.
- Raw Preview, Legacy schema/Preview, raw args/options/query/Topic/filter
  documents, hidden action documents, and caller-authored confirmation hashes
  are absent from the packaged parser and guidance.
- `waapi.call` remains only as an internal Canonical OperationRequest used after
  an exact reflected URI has been typed and materialized. It is not a public
  operation or schema route.
- Maintainer reflection data, internal canonical mappings, stored evidence, and
  versioned historical archive codecs remain outside the model-facing parser.
- An unfinished pre-cutover Draft or Preview may be inspected only enough to
  return a bounded recreate boundary; it cannot execute through compatibility
  grammar.

## Consequences

- Every allowed WAAPI route has one discoverable construction path while read,
  Topic, mutation, terminal, and compound lifecycles remain distinct.
- Simple and zero-input APIs pay almost no composition overhead; complex APIs
  receive recursive, revision-bound handles only when their schema requires it.
- Program tests prove exact-version schema compilation, materialization, and
  lifecycle boundaries. Real Wwise and Fresh Agent campaigns remain release
  evidence rather than a second implementation mechanism.
- Historical evidence stays replayable through explicit offline codecs without
  reintroducing its grammar into production.
