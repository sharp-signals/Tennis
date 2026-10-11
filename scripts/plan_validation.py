"""Plan proportional validation and main-drift handling for Codex work.

CHANGE-2026-10-11-103. This script is read-only: it inspects changed paths and
prints a deterministic validation plan. It never edits files, branches, or CI.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from typing import Iterable

SENSITIVE_FILES = {
    "src/main.py",
    "src/fetch_data.py",
    "src/config.py",
    "src/report_html.py",
    "src/prelive_decision.py",
    "src/pricing.py",
    "src/calibration_store.py",
    "src/paper_trading.py",
    "src/competition_evidence.py",
    "src/competition_registry.py",
}

TEST_MAP = {
    "src/fetch_data.py": (
        "tests.test_data_transforms",
        "tests.test_external_data_resilience",
    ),
    "src/main.py": (
        "tests.test_main_deterministic",
        "tests.test_prelive_operational",
    ),
    "src/report_html.py": (
        "tests.test_report_contract",
        "tests.test_laver_only_evidence",
    ),
    "src/prelive_decision.py": ("tests.test_prelive_operational",),
    "src/pricing.py": ("tests.test_pricing",),
    "src/calibration_store.py": ("tests.test_calibration_store",),
    "src/paper_trading.py": ("tests.test_prelive_operational",),
    "src/competition_evidence.py": (
        "tests.test_competition_evidence",
        "tests.test_competition_evidence_integration",
        "tests.test_laver_only_evidence",
        "tests.test_atp_ranking_eligible_evidence",
    ),
    "src/competition_registry.py": ("tests.test_atp_ranking_eligible_evidence",),
    "scripts/competition_evidence_impact_audit.py": (
        "tests.test_atp_ranking_eligible_evidence",
    ),
}

DOMAIN_RULES = {
    "data_pipeline": {
        "src/main.py",
        "src/fetch_data.py",
        "src/competition_evidence.py",
        "src/competition_registry.py",
    },
    "decision": {
        "src/main.py",
        "src/prelive_decision.py",
        "src/pricing.py",
        "src/report_html.py",
    },
    "persistence": {
        "src/calibration_store.py",
        "src/paper_trading.py",
        "src/snapshot_identity.py",
        "src/snapshot_reconciliation.py",
    },
    "workflows": set(),
}

PROCESS_DOCS = {
    "AGENTS.md",
    "README.md",
    "PRELIVE_OPERATIONAL_CONTRACT.md",
}

GENERATED_OR_DATA_PREFIXES = (
    "data/",
    "docs/dashboard/",
)

WORKFLOW_PREFIX = ".github/workflows/"
TEST_PREFIX = "tests/"
DOC_PREFIX = "docs/"


def _clean_paths(paths: Iterable[str]) -> list[str]:
    return sorted({str(path).strip().replace("\\", "/") for path in paths if str(path).strip()})


def git_changed_files(base: str, head: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return _clean_paths(completed.stdout.splitlines())


def _is_doc(path: str) -> bool:
    return path in PROCESS_DOCS or path.startswith(DOC_PREFIX) or path.endswith(".md")


def _is_test(path: str) -> bool:
    return path.startswith(TEST_PREFIX)


def _is_generated_or_data(path: str) -> bool:
    return path.startswith(GENERATED_OR_DATA_PREFIXES)


def _domains(paths: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for path in paths:
        if path.startswith(WORKFLOW_PREFIX):
            result.add("workflows")
        for domain, members in DOMAIN_RULES.items():
            if path in members:
                result.add(domain)
    return result


def _targeted_test_modules(paths: Iterable[str]) -> list[str]:
    modules: set[str] = set()
    for path in paths:
        modules.update(TEST_MAP.get(path, ()))
        if path.startswith(TEST_PREFIX) and path.endswith(".py"):
            modules.add(path[:-3].replace("/", "."))
    return sorted(modules)


def validation_plan(paths: Iterable[str], level: int = 1) -> dict:
    changed = _clean_paths(paths)
    if level not in (1, 2, 3):
        raise ValueError("level must be 1, 2 or 3")

    docs_only = bool(changed) and all(_is_doc(path) for path in changed)
    tests_only = bool(changed) and all(_is_doc(path) or _is_test(path) for path in changed)
    sensitive = sorted(set(changed).intersection(SENSITIVE_FILES))
    workflows = sorted(path for path in changed if path.startswith(WORKFLOW_PREFIX))
    python_paths = sorted(
        path for path in changed
        if path.endswith(".py") and not path.startswith(TEST_PREFIX)
    )

    targeted_modules = _targeted_test_modules(changed)
    targeted_commands: list[str] = []
    if python_paths:
        targeted_commands.append("ruff check " + " ".join(python_paths))
    if targeted_modules:
        targeted_commands.append(
            "python -m unittest -v " + " ".join(targeted_modules)
        )
    if any(path.startswith("scripts/google_apps_script/") for path in changed):
        targeted_commands.append("node --test scripts/google_apps_script/*.test.js")
    if workflows:
        targeted_commands.append(
            "python -m unittest -v "
            "tests.test_match_identity_workflow_contract "
            "tests.test_report_notification_workflow"
        )

    full_ci_required = (
        level >= 2
        or bool(sensitive)
        or bool(workflows)
        or any(path.startswith("src/") for path in changed)
    )
    if docs_only and level == 1:
        full_ci_required = False
    elif tests_only and level == 1 and not sensitive and not workflows:
        full_ci_required = False

    if docs_only:
        scope = "DOCS_ONLY"
    elif tests_only:
        scope = "TESTS_OR_DOCS_ONLY"
    elif sensitive:
        scope = "SENSITIVE_CODE"
    elif workflows:
        scope = "WORKFLOW"
    else:
        scope = "STANDARD"

    return {
        "change_level": level,
        "scope": scope,
        "changed_files": changed,
        "sensitive_files": sensitive,
        "domains": sorted(_domains(changed)),
        "targeted_commands": targeted_commands,
        "full_ci_required_at_final_checkpoint": full_ci_required,
        "development_loop": (
            "Run targeted commands after each logical edit; do not rerun full CI "
            "until the change is stable."
        ),
        "final_gate": (
            "Run/await full PR CI once after final sync."
            if full_ci_required
            else "Use proportional targeted validation; full CI is optional unless the brief requires it."
        ),
    }


def main_drift_plan(
    change_paths: Iterable[str],
    drift_paths: Iterable[str],
) -> dict:
    changed = set(_clean_paths(change_paths))
    drift = set(_clean_paths(drift_paths))
    exact_overlap = sorted(changed.intersection(drift))
    changed_domains = _domains(changed)
    drift_domains = _domains(drift)
    domain_overlap = sorted(changed_domains.intersection(drift_domains))
    drift_data_only = bool(drift) and all(_is_generated_or_data(path) for path in drift)

    if not drift:
        action = "NO_SYNC_NEEDED"
        reason = "main has no new paths in the inspected drift"
    elif exact_overlap:
        action = "SYNC_NOW"
        reason = "main changed one or more files also changed by this branch"
    elif domain_overlap:
        action = "SYNC_NOW"
        reason = "main changed the same critical domain even without exact file overlap"
    elif drift_data_only:
        action = "FINAL_SYNC_ONLY"
        reason = "main drift is generated/data-only and does not intersect the change"
    else:
        action = "REVIEW_ONCE_THEN_FINAL_SYNC"
        reason = "main drift is independent; inspect it once and avoid restarting the work loop"

    return {
        "action": action,
        "reason": reason,
        "exact_file_overlap": exact_overlap,
        "critical_domain_overlap": domain_overlap,
        "drift_data_only": drift_data_only,
        "drift_files": sorted(drift),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan proportional validation and main-drift handling."
    )
    parser.add_argument("--level", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--base", help="git base used to discover change paths")
    parser.add_argument("--head", default="HEAD", help="git head for change paths")
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="explicit changed path; repeat instead of using --base",
    )
    parser.add_argument("--drift-from", help="older main/base SHA")
    parser.add_argument("--drift-to", help="newer main SHA/ref")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.file:
        changed = _clean_paths(args.file)
    elif args.base:
        changed = git_changed_files(args.base, args.head)
    else:
        raise SystemExit("provide --base or at least one --file")

    result = {"validation": validation_plan(changed, args.level)}
    if bool(args.drift_from) != bool(args.drift_to):
        raise SystemExit("--drift-from and --drift-to must be supplied together")
    if args.drift_from and args.drift_to:
        drift = git_changed_files(args.drift_from, args.drift_to)
        result["main_drift"] = main_drift_plan(changed, drift)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        validation = result["validation"]
        print(f"scope: {validation['scope']}")
        print(f"level: {validation['change_level']}")
        print(
            "full CI at final checkpoint: "
            f"{validation['full_ci_required_at_final_checkpoint']}"
        )
        for command in validation["targeted_commands"]:
            print(f"targeted: {command}")
        if "main_drift" in result:
            drift = result["main_drift"]
            print(f"main drift: {drift['action']} — {drift['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
