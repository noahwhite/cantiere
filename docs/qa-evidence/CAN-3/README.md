# QA evidence: CAN-3

Story: CAN-3, [Bug] Private model upstream check accepts non-link-local cloud metadata addresses.
QA round: 2, on 2026-11-17.
Round 1 (merged in PR https://github.com/noahwhite/cantiere/pull/31) verified the earlier ACs at `50d25c0` and left AC1 as a pending owner ruling on NAT64 forms.
The owner then changed the scope to refuse every IPv6 address and the product owner rewrote the ACs on 2026-11-17 (CAN-3 comment "Scope change: refuse IPv6"); this round verifies every item against the current story text and reuses no round-1 verdict.
Path: no-deployment.
Target: merged commit `aa100812126996b1527a9f0ef63a0f3dfe296ee2` on `main` (PR https://github.com/noahwhite/cantiere/pull/34, merged head `99d2990de55af78c5a5911ea54d0e4f25f130940`).
Target confirmed on `main`: `git merge-base --is-ancestor aa100812126996b1527a9f0ef63a0f3dfe296ee2 origin/main` exited 0.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: a read of the merged text in a fresh clone at the target, plus `git show --word-diff` of the target and of `50d25c0`, `grep` over `docs/`, a category and token comparison of the ADR-0014 refused set against row 9a, and the review list of PR #34.
Line numbers below are at the target commit.
The full command output is attached to the CAN-3 story as `CAN-3-qa-round-2-assertions.txt`.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 config check refuses any IPv6 literal, including IPv4-mapped; resolver refuses IPv6 answers beside its other refusals | verified | ADR-0014:117: "The config check refuses any IPv6 address, including an IPv4-mapped one such as `::ffff:169.254.169.254`, and any other address that does not parse as dotted-decimal IPv4."; ADR-0014:115: "The resolver refuses any answer that is an IPv6 address, is in a non-global range or is at a cloud metadata address listed below", the worker resolver of ADR-0014:111. |
| AC2 IPv4 refused set with an explicit metadata list, metadata not called link-local, no override | verified | ADR-0014:119: "It refuses an IPv4 address that is a loopback address, a "this network" address (`0.0.0.0/8`), a link-local address, the host's own address, a platform service's address, or a cloud metadata address."; ADR-0014:120 lists `169.254.169.254`, `169.254.170.2`, `169.254.170.23`, `100.100.100.200` and `168.63.129.16` "because not every metadata service is link-local"; ADR-0014:121: "There is no override." See the note on `169.254.170.23`. |
| AC3 original failing case `[fd00:ec2::254]:80` refused as an IPv6 address | verified | `fd00:ec2::254` is an IPv6 address, so ADR-0014:117 refuses it; `docs/architecture.md:181` names `[fd00:ec2::254]:80` among the refused declarations. |
| AC4 IPv6-specific handling removed | verified | ADR-0014 has no match for Teredo, ISATAP, 6to4, IPv4-translated, IPv4-compatible, zone index, normalisation, `fd00:ec2`, `fd20:ce`, `64:ff9b`, `ipv4only.arpa` or the NAT64 residual; ADR-0014:117 names IPv4-mapped only as a refused IPv6 address. See the note on ADR-0014:112. |
| AC5 test 9a refuses the five declarations, none reachable | verified | `docs/architecture.md:181`: "is refused by the config check, including declarations at `[fd00:ec2::254]:80`, `[::ffff:169.254.169.254]:80`, `169.254.169.254:80`, `100.100.100.200:80` and `168.63.129.16:80`, and none of those addresses is reachable from the proxy process". |
| AC6 RFC 1918 and non-metadata `100.64.0.0/10` accepted and reachable | verified | ADR-0014:122: "A declaration at any other private IPv4 address, such as an RFC 1918 address or a `100.64.0.0/10` address that none of these rules refuses, is accepted, and its address and port are reachable from the process."; `docs/architecture.md:181`: "a private model upstream declared at an RFC 1918 address and at a `100.64.0.0/10` address, neither of them refused below, is accepted by the config check and reachable". |
| AC7 same refused set in ADR-0014 and 9a, `docs/requirements.md` checked | verified | ADR-0014:117-120 and the 9a refused clause both name any IPv6 address, an address that is not dotted-decimal IPv4, loopback, `0.0.0.0/8`, link-local, the host's own, a platform service's and the same five metadata addresses, and nothing appears in only one; 9a also carries the IPv6 resolver refusal; `docs/requirements.md` has no restatement of the rule. |
| DoD1 root cause identified | verified | The original clause "a loopback or link-local address, which includes cloud metadata services" is gone; ADR-0014:120 lists the metadata addresses explicitly, and ADR-0014:118 removes the IPv6 class: "No model upstream needs IPv6, and refusing the whole family leaves no IPv6 form that could carry or reach a refused address." |
| DoD2 fix verified against the original failing case | verified | See AC3. |
| DoD3 regression protection | verified | Conformance test 9a names `[fd00:ec2::254]:80` and the four other declarations as refused (`docs/architecture.md:181`); the repository's only CI checks the requirements exports, so the conformance test is the feasible protection. |
| DoD4 independently reviewed | verified | PR #34 review of record at `99d2990de55af78c5a5911ea54d0e4f25f130940`, the head PR #34 merged at; reviewer Codex GPT-6.1 Sol, adjudicator DeepSeek V4.1 Flash; "Clean at this head; no open valid findings." |
| DoD5 docs updated for the non-obvious constraint | verified | ADR-0014:118 states why the whole IPv6 family is refused, and ADR-0014:120 states why the metadata list is explicit. |
| DoD6 no new regressions | verified | ADR-0014:211 gives the gateway-only resolver "the same refusals"; ADR-0014:112, :210 and :226, ADR-0011:19, ADR-0007:38, ADR-0017:21 and `docs/architecture.md:130` and `:174` stay consistent; neither changed file has an em dash. |

## Notes on two judgments

AC2 names four metadata addresses, and ADR-0014:120 also lists `169.254.170.23`.
AC2 says no "only" or "exactly", and AC4 lists the entries to remove as `fd00:ec2::23`, `fd00:ec2::254` and `fd20:ce::254`, naming the IPv6 EKS Pod Identity entry but not its IPv4 sibling, so the ACs keep `169.254.170.23`.
That address is also link-local, which AC2 itself requires refused, so the refused set is the same with or without the entry.

ADR-0014:112 still names "IPv4-mapped and NAT64 prefixes" in the output chain's runtime drop list.
That text is unchanged context in the CAN-3 round-1 diff of `50d25c0`, so it predates CAN-3, and it is runtime filtering, not the config check's "NAT64 prefix rule and its accepted residual" that AC4 names, which the target removes.
