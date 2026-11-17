# QA evidence: CAN-6

Story: CAN-6, [Bug] ADR-0014 compromise paths omit the JSON, tokenizer and image parsers.
QA round: 2, on 2026-11-17.
Round 1 (merged in PR https://github.com/noahwhite/cantiere/pull/25) verified every item except AC3, which it left as a pending owner ruling.
The owner ruled for reading A, and the product owner amended AC3 on 2026-11-17; this round verifies every item against the current story text, including the amended AC3.
Path: no-deployment.
Target: merged commit `765ff6096b1564c5b0b2f8a86355b77f50c08cb1` on `main` (PR https://github.com/noahwhite/cantiere/pull/20).
Target confirmed on `main`: `git merge-base --is-ancestor 765ff6096b1564c5b0b2f8a86355b77f50c08cb1 origin/main` exited 0.
Comparison base: the target's parent `e96198b3dc9e7ddcf17338c389f4d45f98e78eb1`.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: a read-only probe over a fresh clone at the target, counting each added phrase in ADR-0014 at the parent and at the target, listing every ADR-0014 line that names the worker or another process together with a parse, plus `git diff`, a search of the mirror documents, and PR #20's body and reviews.
The full probe output is attached to the CAN-6 story as `CAN-6-qa-assertions-round-2.txt`.
Line numbers below are in `docs/adr/0014-model-credentials-gateway-and-subscriptions.md` at the target unless another file is named.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 compromise bullet names the strict JSON request parser and the tokenizers | verified | Line 252: "the code that parses sandbox-controlled bytes (... request bodies in the strict JSON request parser, request text in the tokenizers, ...)"; each phrase counts 0 at the parent and 1 at the target. |
| AC2 ADR states whether the image token formula parses image bytes; bullet names it | verified | Line 48: "Where that formula takes an image's pixel width and height, the proxy process reads them by parsing the sandbox-controlled image bytes the request carries, so applying it parses image data (Consequences); a formula that bills a flat amount per image needs no such parse."; line 252 names "image data for the image token formula". |
| AC3 (amended 2026-11-17) parsers run in the proxy process; no sentence places them in the worker or in another process that handles sandbox-controlled bytes | verified | Line 90: "The gateway's strict JSON request parser, its tokenizers and its image parsing (above) run in this process with the rest of the gateway; the worker never parses a session's model requests." Every other line that names the worker with a parse is context (line 12), the journal parse (line 170), or a rejected alternative (lines 279 and 282). The only other process that runs the gateway, `cantiere-gateway` (lines 200-201), serves "Model calls the server makes itself, outside any session", and its section (lines 198-223) never mentions the sandbox, so it handles no sandbox-controlled bytes, which the amendment places outside AC3. |
| AC4 every other first-release sandbox-byte parser named; PR lists the sections checked | verified | Line 252 also names TLS, HTTP, GraphQL, git push commands and packs, and model response bodies and streams with their usage; no other first-release parse of sandbox-controlled bytes in the proxy process appears in ADR-0014; the PR #20 body, "ADR-0014 sections checked (AC4)", lists Context through Alternatives considered. |
| AC5 `docs/architecture.md` and `docs/requirements.md` checked | verified | Neither file restates the compromise-path list: `docs/architecture.md:182` mentions only "the parser" for unknown usage fields in test 9b, and `docs/requirements.md:254` (COST-2) says only "a compromise of the gateway process is outside this guarantee"; the target changes neither file, and the PR #20 body, "Mirror documents (AC5)", lists both. |
| DoD1 root cause identified | verified | The parent bullet predated the gateway's JSON, tokenizer and image steps; the fix names the whole first-release parser set, not only the two reported. |
| DoD2 fix verified against the original failing case | verified | Parent line 250 read "parses sandbox-controlled TLS, HTTP, GraphQL, git packs or model streams"; target line 252 names the missing parsers. |
| DoD3 regression protection | verified | The absence is justified in PR #20: "no in-repo check enforces the parser enumeration (docs-only repo with no CI)". |
| DoD4 independently reviewed | verified | PR #20's latest review of record (COMMENTED, Codex GPT-6.1 Sol reviewer, DeepSeek V4.1 Flash adjudicator) covers `2225b25bb0c58c2b91d2adac3139924bcc50a1fd`, the head PR #20 merged at, with the verdict "clean". |
| DoD5 docs updated | verified | The non-obvious constraints are encoded in line 48 (the conditional image parse) and line 90 (the parser placement). |
| DoD6 no new regressions | verified | One file changed, 3 insertions and 1 deletion; no em dash in ADR-0014; `git diff --check` exits 0; the mirror documents are unchanged. |
