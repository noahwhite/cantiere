# QA evidence: CAN-3

Story: CAN-3, [Bug] Private model upstream check accepts non-link-local cloud metadata addresses.
QA round: 1, on 2026-11-17.
Path: no-deployment.
Target: merged commit `50d25c00491d1dd06ea0cc8706847903eaf366e6` on `main` (PR https://github.com/noahwhite/cantiere/pull/30).
Target confirmed on `main`: `git merge-base --is-ancestor 50d25c00491d1dd06ea0cc8706847903eaf366e6 origin/main` exited 0.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: a read of the merged text in a fresh clone at the target, plus `git show --word-diff`, `git grep` over `docs/`, a token comparison of the ADR-0014 refused set against row 9a, and the review list of PR #30.
Line numbers below are at the target commit.
The full command output is attached to the CAN-3 story as `CAN-3-qa-round-1-assertions.txt`.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 refused set listed explicitly, embedding forms normalised, metadata not called link-local | pending owner ruling | ADR-0014:119: "It then refuses the declaration when the declared address or the normalised address is a loopback address, ... a link-local address, the host's own address, a platform service's address, or a cloud metadata address."; ADR-0014:122 lists `169.254.169.254`, `169.254.170.2`, `169.254.170.23`, `fd00:ec2::23`, `fd00:ec2::254`, `fd20:ce::254`, `100.100.100.200` and `168.63.129.16` "because not every metadata service is link-local"; ADR-0014:118 normalises IPv4-mapped, IPv4-translated, IPv4-compatible, 6to4 and ISATAP forms; ADR-0014:120 refuses NAT64 addresses in the well-known, local-use and reported prefixes, and ADR-0014:121 accepts a residual for an unreported network-specific NAT64 prefix (see Pending owner rulings). |
| AC2 original failing case `[fd00:ec2::254]:80` refused | verified | `fd00:ec2::254` parses (ADR-0014:117), is no embedding form (ADR-0014:118) and no NAT64 address (ADR-0014:120), and is in the list at ADR-0014:122, so ADR-0014:119 refuses it; ADR-0014:124: "There is no override." |
| AC3 9a refuses the three declarations, none reachable | verified | `docs/architecture.md:181`: "including declarations at `[fd00:ec2::254]:80`, `100.100.100.200:80`, `[::ffff:169.254.169.254]:80`, ... and none of those addresses is reachable from the proxy process". |
| AC4 RFC 1918, non-metadata `100.64.0.0/10` and non-metadata ULA accepted and reachable | verified | ADR-0014:125: "A declaration at any other private address, such as an RFC 1918 address, a `100.64.0.0/10` address or a unique local address, none of them in that list, is accepted, and its address and port are reachable from the process."; `docs/architecture.md:181`: "a private model upstream declared at an RFC 1918 address, at a `100.64.0.0/10` address and at a unique local address, none of them a cloud metadata address, is accepted by the config check and reachable". |
| AC5 same refused set in ADR-0014 and 9a, `docs/requirements.md` checked | verified | The backticked tokens of ADR-0014:117-122 and of the 9a refused clause match except the prefix definitions of the embedding forms, which 9a names by category; every category (loopback, "this network", link-local, host, platform, cloud metadata, the five embedding forms, NAT64, Teredo, unparseable) appears in both; `docs/requirements.md` has no restatement of the rule. |
| DoD1 root cause identified | verified | The old clause (ADR-0014:116 at the parent commit) read "a loopback or link-local address, which includes cloud metadata services"; ADR-0014:122 replaces it with an explicit list "because not every metadata service is link-local". |
| DoD2 fix verified against the original failing case | verified | See AC2. |
| DoD3 regression protection | verified | Conformance test 9a names `[fd00:ec2::254]:80` as refused (`docs/architecture.md:181`); the repository has no CI or test suite, so the conformance test is the feasible protection. |
| DoD4 independently reviewed | verified | PR #30 review of record at `7a79a7eea36ff7860639213ca3543f5afca4d9f5`, the head PR #30 merged at; reviewer Codex GPT-6.1 Sol, adjudicator DeepSeek V4.1 Flash; "Clean at this head". |
| DoD5 docs updated for the non-obvious constraint | verified | ADR-0014:120 states why NAT64 addresses are refused outright, ADR-0014:121 states the NAT64 residual, ADR-0014:122 states why the list is explicit, and ADR-0014:123 states that matching is on the parsed address. |
| DoD6 no new regressions | verified | ADR-0014:112 and :115 drop and refuse the listed metadata addresses at runtime; the gateway-only (ADR-0014:213-214) and Compose (ADR-0014:229-230) paths, ADR-0011:19, ADR-0007:38 and `docs/architecture.md:130` and `:174` stay consistent; neither changed file has an em dash. |

## Pending owner rulings

AC1, owner: product owner.
Quoted text: "and that it refuses any IPv4-mapped, NAT64 or other IPv4-embedding form of a refused address after normalising the address".
Reading 1: a NAT64 form is an address the config check can recognise by its prefix (well-known, local-use or reported for `ipv4only.arpa`); verdict verified, by ADR-0014:120.
Reading 2: "any" NAT64 form includes an address in a network-specific prefix the resolver does not report; verdict not met, because ADR-0014:121 checks such an address "like any address outside a NAT64 prefix" and accepts that residual.
