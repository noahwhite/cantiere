# QA evidence: CAN-6

Story: CAN-6, [Bug] ADR-0014 compromise paths omit the JSON, tokenizer and image parsers.
QA round: 1, on 2026-11-17.
Path: no-deployment.
Target: merged commit `765ff6096b1564c5b0b2f8a86355b77f50c08cb1` on `main` (PR https://github.com/noahwhite/cantiere/pull/20).
Target confirmed on `main`: `git merge-base --is-ancestor 765ff6096b1564c5b0b2f8a86355b77f50c08cb1 origin/main` exited 0.
Comparison base: the target's parent `e96198b3dc9e7ddcf17338c389f4d45f98e78eb1`.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: a read-only probe over the clone, counting each added phrase in ADR-0014 at the parent and at the target, plus `git diff`, `grep` of the mirror documents and the PR's review list.
The full probe output is attached to the CAN-6 story as `CAN-6-qa-assertions.txt`.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 compromise bullet names the strict JSON request parser and the tokenizers | verified | ADR-0014:252: "the code that parses sandbox-controlled bytes (... request bodies in the strict JSON request parser, request text in the tokenizers, ...)"; both phrases are absent at the parent. |
| AC2 ADR states whether the image token formula parses image bytes; bullet names it | verified | ADR-0014:48: "Where that formula takes an image's pixel width and height, the proxy process reads them by parsing the sandbox-controlled image bytes the request carries, so applying it parses image data (Consequences); a formula that bills a flat amount per image needs no such parse."; ADR-0014:252 names "image data for the image token formula". |
| AC3 parsers run in the proxy process; no sentence places them in the worker or another process | pending owner ruling | ADR-0014:90 places them in the session proxy process; ADR-0014:200-201 runs the same gateway, with "the same message set, budget rules and journal", in `cantiere-gateway` for the server's own model calls; the readings and their verdicts are in the CAN-6 QA evidence comment. |
| AC4 every other first-release sandbox-byte parser named; PR lists the sections checked | verified | ADR-0014:252 also names TLS, HTTP, GraphQL, git push commands and packs, and model response bodies and streams with their usage; no other first-release parse of sandbox-controlled bytes in the proxy process appears in ADR-0014; the PR #20 body lists the sections checked, Context through Alternatives considered. |
| AC5 `docs/architecture.md` and `docs/requirements.md` checked | verified | `docs/architecture.md` has no match for compromis, tokeniz or sandbox-controlled; `docs/requirements.md:254` (COST-2) says only "a compromise of the gateway process is outside this guarantee", with no parser list; the PR #20 body lists both documents. |
| DoD1 root cause identified | verified | The bullet predated the gateway's JSON, tokenizer and image steps; the fix names the whole first-release parser set, not only the two reported. |
| DoD2 fix verified against the original failing case | verified | Parent ADR-0014:250 read "parses sandbox-controlled TLS, HTTP, GraphQL, git packs or model streams"; target ADR-0014:252 names the missing parsers. |
| DoD3 regression protection | verified | The absence is justified in PR #20: "no in-repo check enforces the parser enumeration (docs-only repo with no CI)". |
| DoD4 independently reviewed | verified | PR #20 review of record (COMMENTED, Codex GPT-6.1 Sol reviewer, DeepSeek V4.1 Flash adjudicator) covers head `2225b25bb0c58c2b91d2adac3139924bcc50a1fd`, the head the PR merged at, with a clean verdict. |
| DoD5 docs updated | verified | The non-obvious constraints are encoded in ADR-0014:48 (the conditional image parse) and ADR-0014:90 (the parser placement). |
| DoD6 no new regressions | verified | One file changed, 3 insertions and 1 deletion; no em dash; `git diff --check` is clean; the only other `docs/` list of parsed formats, ADR-0004:11, is a non-exhaustive context line outside AC5. |
