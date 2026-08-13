"""Score already-produced PDFs against the validator.

This path never builds receipts and never imports a receipt generator.
It only reads files that already exist on disk.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .adapter import Verdict, check_pdf_bytes


DEFAULT_GENERATOR_OUTPUT = Path(
    r"C:\Users\fanis\OneDrive\Desktop\ЗАПАСКА 13.07.26\output"
)


def _iter_pdfs(root: Path) -> Iterable[Path]:
    yield from sorted(root.rglob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)


def evaluate_file(path: Path) -> dict[str, Any]:
    result = check_pdf_bytes(path.read_bytes())
    expected = Verdict.FAKE
    return {
        "file": str(path),
        "sha256": result.sha256,
        "bank": result.bank,
        "expected": expected.value,
        "verdict": result.verdict.value,
        "raw_verdict": result.raw_verdict,
        "score": result.score,
        "flags": list(result.flags[:8]),
        "caught": result.verdict is expected,
        "miss": result.verdict is Verdict.CLEAN,
        "error": result.verdict is Verdict.ERROR,
    }


def ingest_folder(root: Path, *, limit: int) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    for path in _iter_pdfs(root):
        evaluations.append(evaluate_file(path))
        if len(evaluations) >= limit:
            break
    caught = sum(bool(item["caught"]) for item in evaluations)
    missed = sum(bool(item["miss"]) for item in evaluations)
    errors = sum(bool(item["error"]) for item in evaluations)
    return {
        "schema": 1,
        "source": str(root),
        "limit": limit,
        "scanned": len(evaluations),
        "caught": caught,
        "missed": missed,
        "errors": errors,
        "unknown": len(evaluations) - caught - missed - errors,
        "evaluations": evaluations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score existing generator PDFs; do not create new ones"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(
            os.environ.get("PDFCHECKER_GENERATOR_OUTPUT", DEFAULT_GENERATOR_OUTPUT)
        ),
    )
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).resolve().parent / "reports" / "generator-ingest.json",
    )
    args = parser.parse_args()
    if not args.source.exists():
        print(f"source folder not found: {args.source}")
        return 2
    report = ingest_folder(args.source, limit=max(1, args.limit))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"source={report['source']} scanned={report['scanned']} "
        f"caught={report['caught']} missed={report['missed']} "
        f"errors={report['errors']}"
    )
    print(f"report={args.report}")
    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
