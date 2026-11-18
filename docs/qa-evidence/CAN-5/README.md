# QA evidence: CAN-5

Story: CAN-5, [Bug] Gateway-only resolver host source names the price table, which lists no hosts.
QA round: 2, on 2026-11-18.
Path: no-deployment.
Target: merged commit `fcbedd5abca92c7fb27b84fdd3a06bbde6ec5de1` on `main` (PR https://github.com/noahwhite/cantiere/pull/37, merged head `5df0bbc5fba3b017948d33fb3fe426b935142b04`, whose tree is identical to the merge).
Target confirmed on `main`: `git merge-base --is-ancestor fcbedd5abca92c7fb27b84fdd3a06bbde6ec5de1 origin/main` exited 0.
Comparison bases: `9c678d14783b93f1c041262316f798e25e9184a5`, the squash parent of PR #19, and `57b6cceb8dda17ebdb1bc5685059f030411fa5f3`, the parent of PR #19's first commit.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: a read-only probe over a fresh clone at the target (line reads, phrase counts, `git diff` and hashes against the comparison bases, a leftover-text search of `docs/`), the Caddy release and advisory on GitHub, the reviews of record on PR #19 and PR #37, CI on the target, and a parse of the components diagram with the mermaid 11.17.2 parser under jsdom.
The full probe output is attached to the CAN-5 story as `CAN-5-qa-round-2-assertions.txt`.
Line numbers below are in `docs/adr/0014-model-credentials-gateway-and-subscriptions.md` at the target unless another file is named.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 gateway-only set clause names a defined host source, not the price table | verified | Line 244: the set is filled with answers "for the upstream hosts of the providers in the model secrets the gateway-only service holds (API-key mode, above; ADR-0017)"; the source is defined at lines 37-39 and `docs/adr/0017-configuration-repository.md:21`. |
| AC2 test 9a positive case for a host only in that source | verified | `docs/architecture.md:192` case (1): an OpenAI-compatible host (Moonshot's or DeepSeek's) "that appears only in the upstream hosts of the providers in the model secrets the gateway-only service holds, not in the price table and not as a declared private upstream" is reached on port 443. |
| AC3 test 9a negative cases by hostname and by address, with observations | verified | `docs/architecture.md:192` cases (2) and (3): the absent host is not delivered through any listener and "the gateway's resolver returns no answer for the name"; a direct connection "is dropped by the firewall and times out while the proxy logs no request"; "outside the resolver" no longer appears. |
| AC4 same host-source words; price table unchanged | verified | The phrase appears at lines 216 and 244 and in `docs/architecture.md` at lines 95 and 192 (twice); lines 40-86 hash identically to lines 36-82 of `9c678d1`, and no diff hunk from `9c678d1` touches them. |
| AC5 egress reverse proxy design | verified | Lines 215-221: Caddy in `cantiere-gateway-egress`, one listener per upstream host in the cited source, listeners on loopback under systemd and on the proxy container's address on a network that "holds only the gateway and the proxy" under Compose, plain HTTP "over loopback under systemd and across the gateway's network under Compose", TLS on port 443 to the pinned hostname with the SNI, `Host` and certificate check set by the proxy, and firewall rules that drop every other direct connection, including shared addresses; Compose at lines 261-264. |
| AC6 what the proxy sees, product, rejected alternative, cost, egress limits, relation to ADR-0011 | verified | Lines 220 and 222-223 (sees and enforces); line 224 (Caddy pinned at v2.11.9, a published release; GHSA-6365-7ppr-5r92 is patched in 2.11.5); lines 339-341 (rejected non-terminating filter and reason); lines 304-305 (accepted cost); lines 228 and 244-245 (TCP 443 to global IPv4 and its resolver, no IPv6); lines 240-242 and 343 (separate from the ADR-0011 proxy). |
| AC7 test 9a three cases with observations | verified | `docs/architecture.md:192` cases (1) to (3), each with the observation the AC names. |
| AC8 restatements and component listings | verified | `docs/architecture.md:86` labels the edge "plain HTTP, over loopback under systemd, across the gateway's network under Compose", `:87` "DNS, under systemd only", `:94` "companion resolver under systemd", and `:95` places the listeners "on a loopback address under systemd and, under Compose, on the proxy container's address on the gateway's own network", matching lines 217, 218, 247, 262 and 304. `docs/requirements.md` and ADR-0019 hold no loopback, listener or plain HTTP text, and `docs/adr/0019-packaging-and-install.md:19` and `:23` list the proxy. The proxy is in the components diagram (`docs/architecture.md:38`, `:86-88`, which parses while a broken control fails) and the components table (`:95`). |
| DoD1 root cause identified | verified | The cause was the missing declared host source, fixed at lines 37-39 and in ADR-0017 line 21. |
| DoD2 fix verified against the original failing case | verified | The Moonshot or DeepSeek host absent from the price table is test 9a case (1). |
| DoD3 regression protection | verified | Test 9a cases (1) to (3) are the conformance assertions. |
| DoD4 independently reviewed | verified | PR #19's review of record covers its merged head `e04d927e52c2d6d4bb9ecd7fd34ae98b0c2349a0` and PR #37's covers `5df0bbc5fba3b017948d33fb3fe426b935142b04`, each with no open finding. |
| DoD5 docs updated | verified | The non-obvious constraints are recorded at lines 226-233 and in Alternatives considered, lines 338-344. |
| DoD6 no new regressions | verified | Line 6 says that previously "under systemd, the service connected directly on port 443 to addresses in an nftables set that the gateway's resolver filled for the provider hosts in the price table, and under Compose it could reach port 443 on any global address", which matches `57b6cce` lines 197 and 214 and `9c678d1` lines 210 and 227, and it names no `CONNECT` allowlist. In `docs/` outside `docs/qa-evidence/`, the `CONNECT` proxy method and HAProxy appear only in the rejected alternative, lines 339-341 (`docs/adr/0010-credentials-stay-outside-the-sandbox.md:34` holds only the MySQL privilege names `KILL CONNECTION` and `CONNECTION_ADMIN`), and no PENDING-EGRESS-PROXY, "never terminates" or "outside the resolver" text remains. CI on the target passed. |

## Judgments

The diagram node `cantiere-gateway-resolver` (`docs/architecture.md:37`) has no deployment qualifier, but its only edge (`:87`) and its table row (`:94`) scope it to systemd, as line 247 does.
`docs/requirements.md:283` links `architecture.svg`, a platform overview that lists no gateway component, so it is not a component listing the proxy must join.
`docs/adr/DRAFT-upstream-model-gateways.md` is an unadopted draft whose gateway-only lines speak only of shared provider entries and declared private upstreams, which lines 221 and 264 still accept.
Round 1 named the mermaid parser as 11.4.2 from the package range; the installed parser is 11.17.2.
No item is pending an owner ruling.

## Outcome

Every AC and DoD item is verified, so the story moves to Done.
Round 1, at `b5ec4873c54495078a73ebe9799a3d94fcfe5a23`, failed AC8 and DoD6; PR #37 fixed both, and this round verifies them at the target.
