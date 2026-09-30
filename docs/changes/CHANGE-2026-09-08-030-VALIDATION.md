# CHANGE-2026-09-08-030 — Implementation handoff

Status: IMPLEMENTED ON PR BRANCH / NOT MERGED / AWAITING REVIEW.
Source implementation: aa2df50c955ad0d9ab3e06b6092bcf482a20626d.
Validated main input baseline: 217cbf508a7347b981a2c3bf7ccada5cddb21791.

## Verified validation

Run https://github.com/sharp-signals/Tennis/actions/runs/34273799002 completed successfully:
- 391 Python tests, including 20 audit tests; 18 additional motor checks; 11 Node/Apps Script tests passed.
- Ruff, compileall, known-format secret scan and git diff check passed.
- Overall coverage 62%; audit module 96%.
- Same-input comparison against the baseline dashboard: every legacy field equal, both before and after offline refresh; 1,809 report HTML files.
- Primary snapshots, PAPER, public manual aggregates, active/archive market observations and old report HTML remained unchanged (git diff guard).
- No bot, pilot, backfill or paid-provider dispatch was initiated for this CHANGE.

Validation artifact 10074935689, SHA256 d7a437ce0558dc5e5032ba8459cd52cf0e3c3fc861b34e5c958ced0b4cd06fdc.
A previous publication failed because the Actions token cannot edit workflows. No permission was escalated: source publication stayed inside its contents permission; authorised connector writes finalise the approved workflow edits and remove the temporary validation workflow.

## Manual aggregate refresh correction

The existing Apps Script uses `[skip ci]`. The final refresh workflow therefore uses successful `pages build and deployment` completion on main, not push-only. The guard checks the exact triggering commit diff for `data/manual_paper_22bet.json`; derived-only commits are rejected, preventing recursion. Only trusted main code is checked out. Five additional local Git-based tests cover skip-ci commits, derived-only commits, malformed input, nonancestor commits and explicit dispatch. The final normal PR CI must pass these too before review.

This supersedes the phrase 'manual aggregate push workflow' in the metric catalogue: source data and methodology are unchanged. Actual production trigger activation remains untested until merge; monitor refresh is an additional update path.

## Interpretation and boundaries

The new descriptive paired benchmark currently has 16 eligible forecasts and 13 settled pairs. Both sides use the same 13 snapshots. GREEN_STRONG remains N=0. These are availability observations, not claims of edge or a validated strategy.

UI changes keep all legacy metrics accessible, show scores to six decimal places, place operational/data/validation status at the top, and distinguish HTML versions, snapshots and PAPER legs. Report rendering edits affect only future reports; existing HTML and BO5/PAPER/pricing contracts are unchanged.

Pilot/enrichment and audit evidence were preserved in Drive with checksum verification. A complete ongoing warehouse retention/restore policy, cache optimisation and dependency upgrades remain separate work. No claim is made that the private Sheet installation was audited.

Review required before merge. Do not update Project Canon as MERGED or production-active until merge and publication are actually verified.
