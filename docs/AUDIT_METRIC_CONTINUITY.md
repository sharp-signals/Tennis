# Audit remediation — metric continuity

CHANGE-2026-09-08-030. Approved implementation; review required before merge. Nothing here validates performance or authorises acquisition, tuning or REAL.

## Contracts

| Metric / contract | Source and unit | Calculation / population | Missing and version |
|---|---|---|---|
| Dashboard V1 legacy fields | Existing snapshots, reports, Market Memory, PAPER and public manual aggregates | All pre-030 formulas, filters and denominators remain unchanged | Existing semantics preserved; same-input parity required |
| report_colors | Canonical decision presentation per HTML/report | HTML files, including reruns; not match results | UNAVAILABLE preserved; linkage breakdown is additive |
| paired_comparison | Original snapshots + exact linked Market-Time Ledger observation | Same eligible settled snapshots for both models, binary Brier and natural-log loss via existing evaluator | PAIRED_PRICING_MARKET_V1; unavailable sources => null N, valid empty => N=0 |
| paired eligibility | Frozen full-precision market_probability_a/b and sharp_estimate_a/b | Unique snapshot/event key; capture <= analysis < start; explicit UTC offsets; verified player IDs/order, event, start, capture, Moneyline, bookmaker/endpoint and exact raw odds | Exclusions before reading outcome; duplicate identities and conflicting observation IDs excluded |
| paired market consistency | Frozen raw pricing odds vs frozen probabilities | Existing proportional de-vig identity verified to 1e-9 numerical tolerance; no odds replacement/repricing | No rounded UI probability fallback; missing full-precision values excluded |
| eligible / settled | All eligible forecasts / subset with winner_side a or b | Pending/unresolved shown separately; winner does not select eligibility | eligibility_hash excludes result; scored_snapshot_keys_hash identifies evaluated sample |
| paired delta | Fenzobot minus market on identical sample | Lower score is better; negative delta favours model in this sample only | Scores rounded by existing evaluator; versions/fingerprints/code revision shown separately |
| green_diagnostics | Stored prospective GREEN_STRONG membership and source gates | Counts of existing classifications, gates and reason codes | Gates are independent, NOT an invented sequential funnel; exclusions can overlap; no legacy retagging |
| source quality | Monitor diagnostics and authoritative local ledger | Monitor fresh/stale/unknown retained; capture time vs view-generation time distinguished | Monitor diagnostic is NOT the pricing freshness rule. No new cutoff or health threshold |
| llm_calls | Existing run counter | Legacy provider-invocation semantics preserved | Historic values never rewritten |
| llm_provider_invocations | New run counter at analyze provider call site | Counts provider invocations, including mock/disabled | New runs initialise 0; historical missing stays N/D |
| llm_external_requests | New run counter after provider guard, immediately before SDK request | SDK request attempts; NOT HTTP transport retries, token billing or successful responses | New runs initialise 0; no enabled provider/API secret introduced |
| PAPER / Guerra | Existing separated aggregate views | Unique candidates versus legs; underdog two-leg method unchanged | Never infer missing manual selections, private rows or dates |

The paired comparison is **RETROSPECTIVE_DESCRIPTIVE / EXPERIMENTAL_NOT_VALIDATED**, not primary prospective OOS or a promotion rule. It does not replace the pre-existing unpaired global series or GREEN_STRONG evaluation. Differences due to full-precision input versus display-rounded legacy inputs are explicit, not retroactive corrections.

## Presentation and updates

All old dashboard values remain accessible; empty cohort panels and detailed health metrics are collapsible. The top shows execution, data quality and validation availability separately. Scores display six decimals. Counts identify HTML versions, snapshots and legs. `generated_at` is not a publication timestamp. The legacy closing denominator remains all distinct snapshot events; no claim of 22Bet CLV.

The offline refresh module regenerates Market Memory, GREEN_STRONG and dashboard; it does not acquire data, settle outcomes, alter primary snapshots, or rotate/delete history. Monitor calls it after capture, and the manual aggregate push workflow calls it without private Sheet access. Refresh failures are explicit and do not stop operational decisions.

Report edits affect future rendering only: Fenzobot labels, UTF-8 separators, distinct operational/pricing coverage labels, manual-vs-technical PAPER explanation, and collapsible endpoint provenance. BO5 table from PR #117 and all pricing/selection functions remain unchanged.

## Release checks

Run all Python and Node tests, Ruff, compileall, secret scan, diff check and offline build. Run `python -m scripts.check_metric_continuity --baseline-ref <reviewed-base>` on identical source data. Inspect desktop 1440x900 and mobile fallback; check toggle, filters, details and report links. Compare primary-data hashes before/after. No merge without review.

## Preserved evidence

Drive folder: https://drive.google.com/drive/folders/196NaXAvOBm_D13PAyeQCCOIvpPRHZJhz

- Preservation bundle: SHA-256 `7060754ba217ec8c9c4ef347649ec909b6b43765aa2292e20e52350e5dc15077`.
- Audit evidence: SHA-256 `35fb46e1ff11a51d97f967a57506cfbf8e937a80dbbc58e5ae99c251ca944b32`.

These are preserved audit/pilot/enrichment copies, not a complete automated warehouse backup policy. Shared-cache optimisation, dependency upgrades, and a comprehensive retention/restore policy remain separate work. Sheet installation is not assumed verified; concurrent standalone-sync Changes 028/029 are not edited.
