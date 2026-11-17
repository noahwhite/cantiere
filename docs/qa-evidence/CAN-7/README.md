# QA evidence: CAN-7

Story: CAN-7, [Bug] Test 9b misses document, cache-write and long-context reservation rules.
QA round: 1, on 2026-11-17.
Path: no-deployment.
Target: merged commit `d00797377ba8024e48c8b6305b5c29b4c76524c6` on `main` (PR https://github.com/noahwhite/cantiere/pull/18).
Target confirmed on `main`: `git merge-base --is-ancestor d00797377ba8024e48c8b6305b5c29b4c76524c6 origin/main` exited 0.
Comparison base: the target's parent `57b6cceb8dda17ebdb1bc5685059f030411fa5f3`.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: a read-only probe over the clone, checking each phrase in the 9b row at the parent and at the target, plus `git diff`, `git grep` and the PR's review list.
The full probe output is attached to the CAN-7 story as `CAN-7-qa-assertions.txt`.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 document for a model with no maximum input entry refused (ADR-0014:48) | verified | `docs/architecture.md:182`: "a request that carries a document for a model with no maximum input entry is refused"; absent at the parent. |
| AC2 cache writes reserved at the longest duration, distinct rates, 5-minute plus 1-hour at the 1-hour price (ADR-0014:49) | verified | `docs/architecture.md:182`: "with price entries whose 5-minute and 1-hour cache-write rates differ, a request asking for cache writes is reserved at the price of the longest duration it asks for, so one asking for both 5-minute and 1-hour writes is reserved at the 1-hour price"; absent at the parent. |
| AC3 long-context tier above the threshold, base price just below, no separate document pricing (ADR-0014:49) | verified | `docs/architecture.md:182`: "a request whose input bound crosses a long-context tier's threshold is reserved at that tier's price, and one whose input bound is just below the threshold at the base price"; the clause names the request's input bound, and no clause ties a document to a tier or cache price. |
| AC4 priced provider-run tool with a use cap, on a model with no maximum input entry, refused (ADR-0014:60) | verified | `docs/architecture.md:182`: "and so is a request with a priced provider-run tool that carries a use cap on a model with no maximum input entry"; the existing "a provider-run tool without a use cap" clause stays separate. |
| AC5 existing clauses kept, row cites 0014, `docs/requirements.md` checked | verified | Removing the added span from the target row reproduces the parent row exactly; the row ends "\| 0014 \|"; `docs/requirements.md` mentions conformance tests only at line 276 (OSS-5, "with a conformance test suite"), which is no restatement, and the commit changes only `docs/architecture.md`. |
| DoD1 root cause identified | verified | The cause was the 9b row omitting cases for ADR-0014:48, :49 and :60; the fix adds those cases to the row itself. |
| DoD2 fix verified against the original failing case | verified | The cache-write clause the bug cites (1-hour priced at the 5-minute rate still passing 9b) is absent at the parent and present at the target, as are the other three cases. |
| DoD3 regression protection | verified | The added cases are themselves conformance test cases with discriminating inputs (distinct rates, a below-threshold case, a capped tool), so an implementation that breaks one of the rules fails 9b. |
| DoD4 independently reviewed | verified | PR #18 review of record (COMMENTED, Codex GPT-6.1 Sol reviewer, DeepSeek V4.1 Flash adjudicator) covers head `c95a638bff91d5aa8b81d3a29f4f4b102050a8c4`, the head the PR merged at. |
| DoD5 docs updated | verified | The fix is the documentation change; ADR-0014:42 still names 9b as the conformance test for these rules. |
| DoD6 no new regressions | verified | One file and one line changed as a pure insertion; the row keeps six pipe characters (five columns); no em dash; `git diff --check` is clean; no other restatement of 9b in `docs/` beyond the ADR-0014:42 pointer. |
