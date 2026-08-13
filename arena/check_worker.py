"""Subprocess entry point for evaluating a campaign worktree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--manifest", type=Path)
    choice.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(args.repo.resolve()))
    sys.path.insert(1, str(project_root))

    from arena.judge import evaluate_candidate, smoke_benign

    payload = (
        smoke_benign()
        if args.smoke
        else evaluate_candidate(args.manifest.resolve())
    )
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
