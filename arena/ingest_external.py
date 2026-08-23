"""Score already-produced PDFs against the validator.

This path never builds receipts and never imports a receipt generator.
It only reads files that already exist on disk.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .adapter import Verdict, check_pdf_bytes
from .explain_ru import describe_receipt


DEFAULT_GENERATOR_OUTPUT = Path(
    r"C:\Users\fanis\OneDrive\Desktop\ЗАПАСКА 13.07.26\output"
)


def _iter_pdfs(root: Path) -> Iterable[Path]:
    yield from sorted(root.rglob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)


def _stamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M:%S")


def evaluate_file(path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    result = check_pdf_bytes(path.read_bytes())
    check_ms = int((time.perf_counter() - started) * 1000)
    expected = Verdict.FAKE
    caught = result.verdict is expected
    human = describe_receipt(
        path=str(path),
        bank=result.bank,
        verdict=result.verdict.value,
        flags=result.flags,
        details=result.details,
        caught=caught,
    )
    return {
        "file": str(path),
        "name": human["name"],
        "sha256": result.sha256,
        "origin": "already_on_disk",
        "origin_label": "уже лежал в папке генератора",
        "file_mtime": _stamp(path),
        "checked_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "check_ms": check_ms,
        "bank": human["bank"],
        "submethod": human["submethod"],
        "result": human["result"],
        "why": human["why"],
        "expected": expected.value,
        "verdict": result.verdict.value,
        "raw_verdict": result.raw_verdict,
        "score": result.score,
        "flags": list(result.flags[:8]),
        "caught": caught,
        "miss": result.verdict is Verdict.CLEAN,
        "error": result.verdict is Verdict.ERROR,
    }


def ingest_folder(
    root: Path,
    *,
    limit: int,
    on_progress: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in _iter_pdfs(root):
        item = evaluate_file(path)
        digest = str(item["sha256"])
        item["unique"] = digest not in seen
        item["unique_label"] = (
            "уникальный файл" if item["unique"] else "повтор того же PDF"
        )
        seen.add(digest)
        evaluations.append(item)
        if on_progress is not None:
            on_progress(len(evaluations), limit, item)
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
    limit = max(1, args.limit)

    def progress(done: int, total: int, item: dict[str, Any]) -> None:
        print(
            "PROGRESS::"
            + json.dumps(
                {
                    "done": done,
                    "total": total,
                    "receipt": {
                        "name": item["name"],
                        "file": item["file"],
                        "bank": item["bank"],
                        "submethod": item["submethod"],
                        "result": item["result"],
                        "why": item["why"],
                        "caught": item["caught"],
                        "origin_label": item["origin_label"],
                        "file_mtime": item["file_mtime"],
                        "checked_at": item["checked_at"],
                        "check_ms": item["check_ms"],
                        "unique": item["unique"],
                        "unique_label": item["unique_label"],
                        "sha256": item["sha256"],
                    },
                },
                ensure_ascii=True,
            ),
            flush=True,
        )

    report = ingest_folder(args.source, limit=limit, on_progress=progress)
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
