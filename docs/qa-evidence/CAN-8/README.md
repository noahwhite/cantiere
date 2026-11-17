# QA evidence: CAN-8

Story: CAN-8, [Bug] requirements.docx and requirements.pdf are out of date with requirements.md.
QA round: 1, on 2026-11-17.
Path: no-deployment.
Target: merged commit `f265c147596cad2b6e7a7bfbfc9be7a02ad8378e` on `main` (PR https://github.com/noahwhite/cantiere/pull/26, merged head `fe262e05b44aa3dee42ff277fd3bbb03b422d1f4`).
Target confirmed on `main`: `git merge-base --is-ancestor f265c147596cad2b6e7a7bfbfc9be7a02ad8378e origin/main` exited 0.
Environment, deployed build and fixtures: none, because nothing is deployed on this path.
Method: `scripts/export-requirements.sh --check` at the target with an empty tool cache, a probe extracting COST-2 from each export with `scripts/export-text.py`, three local drift mutations against the merged script in a throwaway worktree, and `gh` reads of PR #26, its reviews and the `Requirements exports` workflow runs.
The full probe and CI output is attached to the CAN-8 story as `CAN-8-qa-assertions.txt`.

## Verdicts

| Item | Verdict | Evidence at the target |
|---|---|---|
| AC1 generator script with pinned tool versions, README names the command | verified | `scripts/export-requirements.sh:13-17` sets `PANDOC_VERSION=3.13`, `TYPST_VERSION=0.15.1` and `PYPDF_VERSION=6.9.2`, and each download carries a SHA-256 (lines 17, 22, 24, 28, 30); `README.md:49`: "After editing `docs/requirements.md`, run `scripts/export-requirements.sh` and commit the regenerated exports with it." |
| AC2 committed exports produced by the script, COST-2 matches, before and after text and absent content in the PR | verified | Running the script at the target leaves both committed exports byte-identical, and `--check` exits 0. The COST-2 text extracted from the docx and from the PDF is identical to `docs/requirements.md:254` once whitespace is collapsed. The PR #26 body quotes the before text from the docx at c02cea8 and from the Markdown, states the after text, and lists the old PDF page header and the old diagram caption as intentionally excluded. |
| AC3 CI workflow on every pull request and push to main, regenerates both, compares extracted text | verified | `.github/workflows/requirements-exports.yml:6-9`: `on: pull_request:` and `push: branches: [main]`; line 27: `run: scripts/export-requirements.sh --check`. The script regenerates both exports into a temporary directory (lines 119-120) and diffs the text from `scripts/export-text.py` (lines 134-157); line 8: "Text is compared, not bytes". |
| AC4 failing and passing CI runs linked on the story | verified | The story's evidence comment links run 44174906356 (failure, Markdown changed only, both exports stale), 44174915913 (failure, docx stale only) and 44174921656 (failure, PDF stale only), and passing PR-head runs 44174776741 (0061701) and 44178178902 (fe262e0). Each evidence commit changes only the file its run names. Those failing runs used the script at 0061701, so QA repeated all three cases with the merged script: each exits 1 and names the expected export stale. |
| DoD1 root cause identified | verified | The exports were made by hand with no recorded generator and no check; `git log` shows them last changed in 2c3fd1d while `docs/requirements.md` changed in 1a3f725, 5bdd3d3 and c4ce6a4. |
| DoD2 fix verified against the original failing case | verified | COST-2 in the docx at c02cea8 reads "so spend cannot pass the cap except by provider-side usage a response does not report" and differs from the Markdown; at the target the docx and PDF COST-2 equal the Markdown. |
| DoD3 regression protection | verified | The `Requirements exports` workflow is the gate: push run 44178387895 on f265c14 succeeded, and the next push to `main` (281e47a, run 44178580195) also succeeded. |
| DoD4 independently reviewed | verified | PR #26 has reviews of record at 0061701, 8bace68, 8534f3d, 17432d5 and the merged head fe262e0, with Codex GPT-6.1 Sol reviewing and DeepSeek V4.1 Flash adjudicating the three rounds that had findings; all eight findings were fixed in the PR, and the last two rounds had none. |
| DoD5 docs updated | verified | `README.md:46-51` adds a "Requirements exports" section, and the script header (lines 2-10) and workflow comment (lines 3-4) state that text is compared and how to fix a failure. |
| DoD6 no new regressions | verified | The merge changes six files and leaves `docs/requirements.md` untouched; its text files have no em dash, and `git diff --check f265c14^ f265c14 -- README.md scripts .github` is clean (the check is not run on the binary exports); pages 1, 12 and 14 of the 17-page PDF were rendered and inspected. |
