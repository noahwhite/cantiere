# QA evidence: CAN-5

Story: CAN-5, [Bug] Gateway-only resolver host source names the price table, which lists no hosts.
QA round: 1, on 2026-11-18.
Path: no-deployment.
Target: merged commit `b5ec4873c54495078a73ebe9799a3d94fcfe5a23` on `main` (PR https://github.com/noahwhite/cantiere/pull/19, merged head `e04d927e52c2d6d4bb9ecd7fd34ae98b0c2349a0`).
Target confirmed on `main`: `git merge-base --is-ancestor b5ec4873c54495078a73ebe9799a3d94fcfe5a23 origin/main` exited 0.
Comparison base: the target's parent `9c678d14783b93f1c041262316f798e25e9184a5`.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: a read-only probe over a fresh clone at the target (phrase and line searches, `git diff` and `git log -S` against the parent, a leftover-text search of `docs/`), the Caddy release and advisory on GitHub, PR #19's reviews, CI on the target, and a parse of the components diagram with mermaid 11.4.2.
The full probe output is attached to the CAN-5 story as `CAN-5-qa-round-1-assertions.txt`.
Line numbers below are in `docs/adr/0014-model-credentials-gateway-and-subscriptions.md` at the target unless another file is named.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 gateway-only set clause names a defined host source, not the price table | verified | Line 244: the set is filled with answers "for the upstream hosts of the providers in the model secrets the gateway-only service holds (API-key mode, above; ADR-0017)"; the source is defined at lines 37-39 and `docs/adr/0017-configuration-repository.md:21` ("model providers with their upstream hosts"). |
| AC2 test 9a positive case for a host only in that source | verified | `docs/architecture.md:192` case (1): an OpenAI-compatible host (Moonshot or DeepSeek) "that appears only in the upstream hosts of the providers in the model secrets the gateway-only service holds, not in the price table and not as a declared private upstream" is reached on port 443. |
| AC3 test 9a negative cases by hostname and by address, with observations | verified | `docs/architecture.md:192` cases (2) and (3): the absent host gets no resolver answer and is not delivered through any listener, a connection to any other proxy port is refused or dropped, and a direct connection is dropped by the firewall and times out with no proxy log; "outside the resolver's set" no longer appears. |
| AC4 same host-source words; price table unchanged | verified | The phrase appears at lines 216 and 244 and in `docs/architecture.md` at lines 95 and 192; the price-table block is identical to the parent's, and no diff hunk touches it. |
| AC5 egress reverse proxy design | verified | Lines 215-221: Caddy in `cantiere-gateway-egress`, one listener per upstream host, plain HTTP from the gateway, TLS on port 443 to the pinned hostname with the SNI, `Host` and certificate check set by the proxy, and firewall rules that drop all other direct egress, including shared addresses; Compose at lines 217, 261-262 and 264. |
| AC6 what the proxy sees, product, rejected alternative, cost, egress limits, relation to ADR-0011 | verified | Lines 220 and 222-223 (sees and enforces); line 224 (Caddy pinned at v2.11.9, a published release; GHSA-6365-7ppr-5r92 is patched in 2.11.5); lines 339-341 (rejected non-terminating filter and reason); lines 304-305 (accepted cost); lines 228 and 244-245 (TCP 443 to global IPv4 and its resolver, no IPv6); lines 240-242 and 343 (separate from the ADR-0011 proxy). |
| AC7 test 9a three cases with observations | verified | `docs/architecture.md:192` cases (1) to (3), each with the observation the AC names. |
| AC8 restatements and component listings | pending owner ruling | Met in part under both readings: `docs/requirements.md` has no restatement of the gateway-only egress rule; the proxy is in the components diagram (`docs/architecture.md:38`, `:85-88`, which parses) and the components table (`:95`); `docs/adr/0019-packaging-and-install.md:19` and `:23` list it. The open part is whether the restatements in `docs/architecture.md` are consistent; see "Pending owner ruling" below. |
| DoD1 root cause identified | verified | The cause was the missing declared host source, fixed at lines 37-39 and in ADR-0017 line 21. |
| DoD2 fix verified against the original failing case | verified | The Moonshot or DeepSeek host absent from the price table is test 9a case (1). |
| DoD3 regression protection | verified | Test 9a cases (1) to (3) are the conformance assertions. |
| DoD4 independently reviewed | verified | PR #19's latest review of record (COMMENTED, Codex GPT-6.1 Sol reviewer, DeepSeek V4.1 Flash adjudicator) covers the merged head `e04d927e52c2d6d4bb9ecd7fd34ae98b0c2349a0` with no open finding. |
| DoD5 docs updated | verified | The non-obvious constraints are recorded at lines 226-229 and 233 and in Alternatives considered, lines 338-344. |
| DoD6 no new regressions | failed | Line 6 (added by the target): "Updated: 2026-11-17 - the gateway-only service's egress proxy is Caddy as a pinned-upstream reverse proxy that terminates the gateway's connection, replacing a non-terminating `CONNECT` allowlist". No `CONNECT` allowlist was ever in `docs/` on `main`: the parent has none, and its gateway-only egress was direct nftables rules to a resolver-filled address set (parent line 210). The `CONNECT` design existed only in PR #19's intermediate commit `58f3f86`, replaced in `38cb428` before the squash merge, so the target adds a false entry to the ADR's update history. The adjacent paths are otherwise unchanged: the session path (line 117) and ADR-0011 are untouched, and CI on the target passed. |

## Judgments

Line 218 says the gateway sends "plain HTTP over loopback", in text framed for systemd; line 217 splits the systemd and Compose listeners, and line 262 says Compose sends "as under systemd, but across the gateway's network instead of loopback", so it is consistent with AC5.

## Pending owner ruling

Item: AC8, "any restatement is made consistent".
`docs/architecture.md:86` labels the gateway-to-proxy edge "plain HTTP over loopback", and `:95` describes "one loopback listener for each of the upstream hosts", with no deployment qualifier; ADR-0014 line 217 puts the Compose listeners "on the proxy container's address on the gateway's network", and line 262 says Compose sends "across the gateway's network instead of loopback".
Reading A: the components overview depicts the systemd deployment, and test 9a covers Compose, so the restatements are consistent and AC8 is verified.
Under that reading the evidence is the diagram's DNS edge from the proxy to `cantiere-gateway-resolver` (`:87`), which holds only under systemd, since ADR-0014 line 247 says that under Compose the proxy's resolver is Docker's, and test 9a's Compose clause (`:192`).
Reading B: `docs/architecture.md` nowhere says the overview is systemd-only, so an unqualified "loopback" restatement contradicts ADR-0014 lines 217 and 262 for Compose and AC8 fails.
Under that reading the evidence is the unqualified text at `:86` and `:95` and the absence of any deployment scope in the Components section.
Owner: the product owner.

## Outcome

DoD6 failed, so the story returns to In Progress for a correction of line 6.
AC8 is pending the owner's ruling above and is not for the engineer.
