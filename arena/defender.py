"""Isolated defender worktrees and fail-closed deterministic gates."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Sequence


def _run(
    command: Sequence[str],
    cwd: Path,
    *,
    timeout: int = 300,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=check,
    )


def _production_changes(repo_root: Path) -> list[str]:
    result = _run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "detector",
            "tests",
            "tools",
        ],
        repo_root,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _worktree_root() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return local / "pdf-checker-arena" / "worktrees"


def _create_round_worktree(
    repo_root: Path, round_number: int, base_ref: str
) -> tuple[Path, str]:
    branch = f"arena/round-{round_number:04d}"
    path = _worktree_root() / f"round-{round_number:04d}"
    if path.exists():
        raise RuntimeError(f"round worktree already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = _run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        repo_root,
    ).returncode == 0
    if exists:
        raise RuntimeError(f"round branch already exists: {branch}")
    result = _run(
        ["git", "worktree", "add", "-b", branch, str(path), base_ref],
        repo_root,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "failed to create worktree")
    return path, branch


def _changed_paths(worktree: Path) -> list[str]:
    result = _run(
        ["git", "status", "--porcelain", "--untracked-files=all"], worktree
    )
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        value = line[3:].strip().replace("\\", "/")
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        paths.append(value)
    return paths


def _allowed_change(path: str) -> bool:
    return (
        (path.startswith("detector/") or path.startswith("tests/"))
        and path.endswith(".py")
        and ".." not in Path(path).parts
    )


def _run_gate(
    command: Sequence[str], worktree: Path, timeout: int
) -> dict[str, Any]:
    result = _run(command, worktree, timeout=timeout)
    return {
        "command": list(command),
        "returncode": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
        "passed": result.returncode == 0,
    }


def run_defender(
    repo_root: Path,
    arena_root: Path,
    report: dict[str, Any],
    state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Let the defender propose a candidate commit on an isolated branch."""
    if not os.environ.get("CURSOR_API_KEY"):
        return {"status": "blocked", "reason": "CURSOR_API_KEY is not configured"}

    dirty = _production_changes(repo_root)
    if dirty and not state.get("candidate_branch"):
        return {
            "status": "blocked",
            "reason": "source detector/tests/tools contain uncommitted work",
            "dirty": dirty,
        }

    round_number = int(report["round"])
    base_ref = str(state.get("candidate_branch") or "HEAD")
    try:
        worktree, branch = _create_round_worktree(
            repo_root, round_number, base_ref
        )
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}

    missed = [item for item in report["evaluations"] if not item["caught"]]
    prompt_template = (arena_root / "prompts" / "defender.md").read_text(
        encoding="utf-8"
    )
    prompt = prompt_template.format(
        report=json.dumps(
            {
                "round": round_number,
                "missed": missed,
                "benign": report["benign"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

        options = AgentOptions(
            api_key=os.environ["CURSOR_API_KEY"],
            model=str(config["model"]),
            name=f"pdf-arena-defender-{round_number:04d}",
            local=LocalAgentOptions(
                cwd=worktree,
                dirs=[
                    arena_root / "corpus" / "generated",
                    arena_root / "reports",
                ],
                auto_review=True,
            ),
        )
        result = Agent.prompt(prompt, options)
    except Exception as exc:
        return {
            "status": "error",
            "reason": f"defender could not start: {exc}",
            "branch": branch,
            "worktree": str(worktree),
        }
    if str(result.status).lower().split(".")[-1] != "finished":
        return {
            "status": "error",
            "reason": f"defender run failed: {result.status}",
            "branch": branch,
            "worktree": str(worktree),
            "run_id": result.id,
        }

    changed = _changed_paths(worktree)
    forbidden = [path for path in changed if not _allowed_change(path)]
    if not changed or forbidden:
        return {
            "status": "rejected",
            "reason": "no allowed change" if not changed else "forbidden paths changed",
            "forbidden": forbidden,
            "changed": changed,
            "branch": branch,
            "worktree": str(worktree),
            "run_id": result.id,
        }

    diff = _run(["git", "diff", "--numstat"], worktree)
    diff_lines = 0
    for line in diff.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            diff_lines += int(parts[0]) + int(parts[1])
    if diff_lines > 1000:
        return {
            "status": "rejected",
            "reason": f"diff too large: {diff_lines} lines",
            "branch": branch,
            "worktree": str(worktree),
            "run_id": result.id,
        }

    gates = [
        _run_gate(
            ["py", "-3.13", "-m", "compileall", "-q", "detector", "tests"],
            worktree,
            300,
        ),
        _run_gate(config["fast_gate"], worktree, 600),
    ]
    for command in config.get("slow_gates", []):
        gates.append(
            _run_gate(
                command,
                worktree,
                int(config["slow_gate_timeout_seconds"]),
            )
        )
    if not all(gate["passed"] for gate in gates):
        return {
            "status": "rejected",
            "reason": "one or more deterministic gates failed",
            "gates": gates,
            "changed": changed,
            "branch": branch,
            "worktree": str(worktree),
            "run_id": result.id,
        }

    add = _run(["git", "add", "--", "detector", "tests"], worktree)
    if add.returncode:
        return {
            "status": "error",
            "reason": add.stderr.strip() or "git add failed",
            "branch": branch,
            "worktree": str(worktree),
        }
    commit = _run(
        [
            "git",
            "commit",
            "-m",
            f"fix structural validator gap from arena round {round_number}",
        ],
        worktree,
        timeout=120,
    )
    if commit.returncode:
        return {
            "status": "error",
            "reason": commit.stderr.strip() or commit.stdout.strip(),
            "branch": branch,
            "worktree": str(worktree),
        }
    sha = _run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
    return {
        "status": "accepted",
        "branch": branch,
        "candidate_sha": sha,
        "worktree": str(worktree),
        "changed": changed,
        "gates": gates,
        "run_id": result.id,
        "summary": result.result,
    }
