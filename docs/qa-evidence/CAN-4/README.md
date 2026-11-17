# QA evidence: CAN-4

Story: CAN-4, [Bug] Price-affecting values nested in a price-neutral object field bypass the reservation.
QA round: 1, on 2026-11-17.
Path: no-deployment.
Target: merged commit `e96198b3dc9e7ddcf17338c389f4d45f98e78eb1` on `main` (PR https://github.com/noahwhite/cantiere/pull/22).
Target confirmed on `main`: `git merge-base --is-ancestor e96198b3dc9e7ddcf17338c389f4d45f98e78eb1 origin/main` exited 0.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: a read of the merged text in a fresh clone at the target, plus `git diff --word-diff`, `grep` over `docs/` and the review lists of PRs #21 and #22.
Line numbers below are at the target commit.
The full command output is attached to the CAN-4 story as `CAN-4-qa-round-1-assertions.txt`.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 nested fields listed by path at every depth, tool options too | verified | ADR-0014:63: "each endpoint's request fields at every depth ... each as price-neutral or with a price for every value the provider offers"; ADR-0014:64: "A field inside an object-valued field is listed by its path, such as `additionalModelRequestFields.top_k` or `additionalModelRequestFields.anthropic_beta` on Bedrock `Converse`, down to the fields that hold values"; ADR-0014:61: "A tool's options are listed like request fields (below), by their path at every depth". |
| AC2 object field not price-neutral as a whole, unlisted nested field or value refused | verified | ADR-0014:65: "An object-valued field cannot be listed as price-neutral as a whole, because a price-affecting value can sit inside it; a request that carries a nested field or value its path does not list is refused." |
| AC3 array elements listed and priced as values | verified | ADR-0014:66: "Each element of an array-valued field is listed and priced as a value, the way each `anthropic-beta` header value is, so each entry of `additionalModelRequestFields.anthropic_beta` must be a listed value." |
| AC4 account-default and context-raising rules apply to nested values | verified | ADR-0014:70: "These two rules apply to a nested listed value exactly as they apply to a top-level one", directly after the account-default rule (ADR-0014:68) and the context-raising rule (ADR-0014:69). |
| AC5 9b covers three Bedrock `Converse` cases | verified | `docs/architecture.md:182`: "an unlisted request field at any depth, such as an unlisted key inside Bedrock `Converse`'s `additionalModelRequestFields`, ... are refused"; "a Bedrock `Converse` document request that carries a listed context-raising beta in `additionalModelRequestFields.anthropic_beta` is reserved at that beta's maximum input, and the same request is refused when that beta has no maximum input entry". |
| AC6 9b passes price-neutral nested values | verified | `docs/architecture.md:182`: "a Bedrock `Converse` request whose `additionalModelRequestFields` carries only nested values listed as price-neutral, such as `top_k`, passes". |
| AC7 9b not top-level-only, wording matches ADR-0014, `docs/requirements.md` checked | verified | The diff removes "top-level" from row 9b, which now reads "an unlisted request field at any depth" and "an unlisted element of an array-valued field", the refusal form of ADR-0014:63 and :66; `docs/requirements.md` restates no field rule (COST-2 at line 254 cites ADR-0014 only in general), so it stays unchanged. |
| DoD1 root cause identified | verified | The cause was the "top-level" scope of the field rule; the fix removes it at ADR-0014:63 and in row 9b and adds the by-path rule instead of refusing `additionalModelRequestFields`. |
| DoD2 fix verified against the original failing case | verified | The original case, `additionalModelRequestFields` listed as price-neutral with a long-context beta in `anthropic_beta`, is closed by ADR-0014:65, :66 and :69-70, and row 9b carries it as a case. |
| DoD3 regression protection | verified | Conformance test 9b gains the three Bedrock `Converse` cases and the price-neutral pass case, so a gateway that keeps the top-level-only rule fails 9b. |
| DoD4 independently reviewed | verified | PR #21 review of record at `6d9405b04ec25688881b55e8898e33652aa007b5` (round 1) and PR #22 review of record at `0d2696826beb468a86aca30d5896a921cf27a524` (delta), the head #22 merged at; reviewer Codex GPT-6.1 Sol, adjudicator DeepSeek V4.1 Flash. |
| DoD5 docs updated for the non-obvious constraint | verified | ADR-0014:65 states why an object cannot be price-neutral, and ADR-0014:67 states that request text is input priced by the input bound, not a field. |
| DoD6 no new regressions | verified | ADR-0014:76 ("a request carries only listed fields, parameters, headers and values") stays consistent; row 9b keeps every earlier case, as the diff only removes "top-level" and inserts the new cases; no other file in `docs/` restates the field rule; neither changed file has an em dash. |

Pending owner rulings: none.
