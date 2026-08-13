"""Run adaptive generator → validator → judge rounds.

The generator can only choose allowlisted structural mutations. Acceptance is
deterministic; an LLM never decides whether its own work passed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .defender import run_defender
from .generator import (
    load_state,
    offline_plans,
    save_state,
    sdk_plans,
    update_strategy,
)
from .judge import evaluate_candidate, score_round, smoke_benign
from .synthetic import write_candidate


ARENA_ROOT = Path(__file__).resolve().parent
REPO_ROOT = ARENA_ROOT.parent
CONFIG_PATH = ARENA_ROOT / "config.json"
STATE_PATH = ARENA_ROOT / "state.json"
REPORTS_ROOT = ARENA_ROOT / "reports"
GENERATED_ROOT = ARENA_ROOT / "corpus" / "generated"


def _load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _evaluate_in_repo(manifest_path: Path, repo: Path) -> dict[str, Any]:
    if repo.resolve() == REPO_ROOT.resolve():
        return evaluate_candidate(manifest_path)
    command = [
        sys.executable,
        str(ARENA_ROOT / "check_worker.py"),
        "--repo",
        str(repo),
        "--manifest",
        str(manifest_path),
    ]
    completed = subprocess.run(
        command,
        cwd=repo,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "campaign check failed")
    return json.loads(completed.stdout)


def _smoke_in_repo(repo: Path) -> dict[str, Any]:
    if repo.resolve() == REPO_ROOT.resolve():
        return smoke_benign()
    command = [
        sys.executable,
        str(ARENA_ROOT / "check_worker.py"),
        "--repo",
        str(repo),
        "--smoke",
    ]
    completed = subprocess.run(
        command,
        cwd=repo,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "campaign smoke failed")
    return json.loads(completed.stdout)


def _plans(
    config: dict[str, Any],
    state: dict[str, Any],
    count: int,
    require_agents: bool,
) -> tuple[list[Any], str]:
    api_key_present = bool(os.environ.get("CURSOR_API_KEY"))
    if api_key_present:
        try:
            prompt = (ARENA_ROOT / "prompts" / "generator.md").read_text(
                encoding="utf-8"
            )
            return (
                sdk_plans(
                    REPO_ROOT,
                    state,
                    count,
                    str(config["model"]),
                    prompt,
                ),
                "cursor-agent",
            )
        except Exception:
            if require_agents:
                raise
    elif require_agents:
        raise RuntimeError("CURSOR_API_KEY is not configured")

    seed = int(config["generator_seed"]) + int(state["round"])
    return offline_plans(state, count, seed), "offline-evolution"


def run_round(
    config: dict[str, Any],
    state: dict[str, Any],
    *,
    require_agents: bool = False,
    validator_repo: Path = REPO_ROOT,
) -> dict[str, Any]:
    state["round"] = int(state["round"]) + 1
    round_number = int(state["round"])
    count = int(config["candidates_per_round"])
    plans, generator_mode = _plans(config, state, count, require_agents)
    round_dir = GENERATED_ROOT / f"round-{round_number:04d}"
    round_dir.mkdir(parents=True, exist_ok=True)

    manifests: list[Path] = []
    for index, plan in enumerate(plans, start=1):
        manifest = write_candidate(round_dir, round_number, index, plan)
        manifests.append(round_dir / str(manifest["file"]).replace(".pdf", ".json"))

    evaluations = [
        _evaluate_in_repo(manifest, validator_repo) for manifest in manifests
    ]
    benign = _smoke_in_repo(validator_repo)
    score = score_round(evaluations, benign)
    update_strategy(state, evaluations)
    report: dict[str, Any] = {
        "schema": 1,
        "round": round_number,
        "generator_mode": generator_mode,
        "validator_repo": str(validator_repo),
        "score": score,
        "caught": sum(bool(item["caught"]) for item in evaluations),
        "missed": sum(not bool(item["caught"]) for item in evaluations),
        "benign": benign,
        "evaluations": evaluations,
    }
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_ROOT / f"round-{round_number:04d}.json"
    report["report_path"] = str(report_path)
    if (
        report["missed"]
        and bool(config.get("enable_defender"))
        and generator_mode == "cursor-agent"
    ):
        defender = run_defender(
            REPO_ROOT, ARENA_ROOT, report, state, config
        )
        report["defender"] = defender
        if defender.get("status") == "accepted":
            state["candidate_branch"] = defender["branch"]
            state["candidate_sha"] = defender["candidate_sha"]
            state["validator_repo"] = defender["worktree"]
    elif report["missed"]:
        report["defender"] = {
            "status": "blocked",
            "reason": (
                "generator is offline; configure CURSOR_API_KEY "
                "to enable the code-writing defender"
            ),
        }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_state(STATE_PATH, state)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safe adaptive structural-PDF training arena"
    )
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument(
        "--require-agents",
        action="store_true",
        help="fail instead of using the offline adaptive generator",
    )
    parser.add_argument(
        "--forever",
        action="store_true",
        help="run bounded batches repeatedly; Ctrl+C stops the loop",
    )
    parser.add_argument("--interval-seconds", type=int, default=3600)
    args = parser.parse_args()

    config = _load_config()
    requested = max(1, args.rounds)
    rounds = min(requested, int(config["max_rounds_per_run"]))
    state = load_state(STATE_PATH)
    clean_streak = 0

    try:
        while True:
            for _ in range(rounds):
                validator_repo = Path(
                    state.get("validator_repo") or REPO_ROOT
                )
                report = run_round(
                    config,
                    state,
                    require_agents=args.require_agents,
                    validator_repo=validator_repo,
                )
                print(
                    f"round={report['round']} mode={report['generator_mode']} "
                    f"caught={report['caught']} missed={report['missed']} "
                    f"score={report['score']}"
                )
                clean_streak = clean_streak + 1 if report["missed"] == 0 else 0
                if clean_streak >= int(config["stop_after_clean_rounds"]):
                    print("stopped: no misses in consecutive rounds")
                    return 0
            if not args.forever:
                return 0
            time.sleep(max(60, args.interval_seconds))
    except KeyboardInterrupt:
        print("stopped by user")
        return 130
    except Exception as exc:
        print(f"arena failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
