# 09: Validate the integrated candidate and reconcile coverage claims

## Parent

#163

## What to build

Deliver one frozen candidate with program tests, affected real-Wwise evidence and four Mac-only Fresh workflows, accurately stating remaining gaps.

## Acceptance criteria

- [ ] Complete the fixed five-version Program gate and full Non-live gate. Run real Wwise tests sequentially using existing sandbox lifecycle; missing prerequisites never count as PASS.
- [ ] Reuse the formal harness for F1 property listing/paging/configuration, F2 continued work after a query miss, F3 GameParameter creation/configuration, F4 standalone ShareSet creation. First batch: each workflow once, Mac only, not multiplied by versions.
- [ ] Before spending Fresh quota, freeze candidate/version/model/options and enumerate user turns and transactions; prove deterministic prerequisites and plugin license availability first.
- [ ] Implement and program-test all 2021.1–2025.1 lanes. Real execution evidence covers affected native branches; never infer all-version live support from fake tests or a Mac run.
- [ ] No Windows Fresh in this scope, no native-Windows acceptance claim. Do not treat Wine and native Windows behavior as identical.
- [ ] Finish ordinary failures in a frozen batch before repair; stop on systemic sandbox/evidence faults. Additional Fresh runs or reruns require a stated rationale/count and user approval; no automatic full matrix.
- [ ] Reconcile the audit ledger against final code, preserve raw verdicts and separately report independent business outcomes. Only completed runs may update README/test counts.
- [ ] Complete Standards and Spec code review; fix actionable findings before final handoff. Report all unimplemented audit discoveries without claiming full closure.

## Blocked by

#164, #165, #166, #167, #168, #169, #170, #171

## Validation

Combined gates and focused real evidence, followed by four budgeted Fresh workflows. Avoid redundant live work already proven by unchanged per-ticket evidence.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
