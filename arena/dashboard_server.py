"""Local cartoon dashboard for watching validator vs generator rounds."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .explain_ru import describe_receipt
from .generator import load_state
from .ingest_external import DEFAULT_GENERATOR_OUTPUT


ARENA_ROOT = Path(__file__).resolve().parent
REPO_ROOT = ARENA_ROOT.parent
STATE_PATH = ARENA_ROOT / "state.json"
REPORTS_ROOT = ARENA_ROOT / "reports"
DASHBOARD_DIR = ARENA_ROOT / "dashboard"
HOST = "127.0.0.1"
PORT = 8766

_lock = threading.Lock()
_process: subprocess.Popen[str] | None = None
_files: dict[str, Path] = {}
_job: dict[str, Any] = {
    "running": False,
    "mode": None,
    "started_at": None,
    "last_exit": None,
    "progress_done": 0,
    "progress_total": 0,
    "current_receipt": None,
    "live_receipts": [],
    "log": [],
}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _latest_round() -> dict[str, Any] | None:
    reports = sorted(REPORTS_ROOT.glob("round-*.json"))
    return _read_json(reports[-1]) if reports else None


def _trend(history: list[dict[str, Any]]) -> dict[str, str]:
    if len(history) < 2:
        return {
            "validator": "same",
            "generator": "same",
            "caption": "Мало раундов, чтобы сравнить форму.",
        }
    prev, last = history[-2], history[-1]
    v_delta = int(last["caught"]) - int(prev["caught"])
    g_delta = int(last["missed"]) - int(prev["missed"])
    if v_delta > 0 and g_delta <= 0:
        caption = "Валидатор стал лучше: ловит больше, дыр меньше."
    elif g_delta > 0 and v_delta <= 0:
        caption = "Генератор стал жёстче: больше промахов валидатора."
    elif v_delta > 0:
        caption = "Оба активны, но валидатор выигрывает раунд."
    elif g_delta > 0:
        caption = "Оба активны, но генератор нашёл новую дыру."
    else:
        caption = "Ничья: счёт как в прошлом раунде."
    return {
        "validator": "up" if v_delta > 0 else "down" if v_delta < 0 else "same",
        "generator": "up" if g_delta > 0 else "down" if g_delta < 0 else "same",
        "caption": caption,
        "validator_delta": v_delta,
        "generator_delta": g_delta,
    }


def _allowed_roots() -> list[Path]:
    return [
        DEFAULT_GENERATOR_OUTPUT.resolve(),
        (ARENA_ROOT / "corpus").resolve(),
    ]


def _safe_pdf(raw: str) -> Path | None:
    try:
        path = Path(raw).expanduser().resolve()
    except OSError:
        return None
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return None
    for root in _allowed_roots():
        try:
            path.relative_to(root)
            return path
        except ValueError:
            continue
    return None


def _register_pdf(raw: str) -> str:
    path = _safe_pdf(raw)
    if path is None:
        return ""
    fid = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    _files[fid] = path
    return fid


def _row_extras(item: dict[str, Any]) -> dict[str, Any]:
    path = str(item.get("file") or "")
    return {
        "file": path,
        "id": _register_pdf(path),
        "origin_label": item.get("origin_label") or "",
        "file_mtime": item.get("file_mtime") or "",
        "checked_at": item.get("checked_at") or "",
        "check_ms": int(item.get("check_ms") or 0),
        "unique": bool(item.get("unique", True)),
        "unique_label": item.get("unique_label") or "",
        "sha256": str(item.get("sha256") or "")[:12],
    }


def _receipt_rows(ingest: dict[str, Any] | None, latest: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if ingest:
        for item in ingest.get("evaluations") or []:
            human = describe_receipt(
                path=str(item.get("file") or item.get("name") or ""),
                bank=str(item.get("bank") or ""),
                verdict=str(item.get("verdict") or ""),
                flags=list(item.get("flags") or []),
                caught=bool(item.get("caught")),
            )
            row = {
                "name": item.get("name") or human["name"],
                "bank": item.get("bank") or human["bank"],
                "submethod": item.get("submethod") or human["submethod"],
                "result": item.get("result") or human["result"],
                "why": item.get("why") or human["why"],
                "caught": bool(item.get("caught")),
            }
            row.update(_row_extras(item))
            rows.append(row)
        return rows
    if latest:
        seen: set[str] = set()
        for item in latest.get("evaluations") or []:
            digest = str(item.get("sha256") or "")
            unique = bool(digest) and digest not in seen
            if digest:
                seen.add(digest)
            human = describe_receipt(
                path=str(item.get("file") or ""),
                bank="Синтетический PDF",
                verdict=str(item.get("production_verdict") or ""),
                flags=list(item.get("observed_codes") or []),
                mutations=list(item.get("mutations") or []),
                caught=bool(item.get("caught")),
            )
            extras = _row_extras(
                {
                    **item,
                    "origin_label": "создан в этом раунде",
                    "unique": unique,
                    "unique_label": (
                        "уникальный файл" if unique else "повтор той же мутации"
                    ),
                    "file_mtime": (
                        datetime.fromtimestamp(Path(str(item.get("file") or "")).stat().st_mtime).strftime("%d.%m.%Y %H:%M:%S")
                        if Path(str(item.get("file") or "")).is_file()
                        else ""
                    ),
                }
            )
            row = {
                "name": human["name"],
                "bank": "Синтетический тест",
                "submethod": "Структура PDF",
                "result": human["result"],
                "why": human["why"],
                "caught": bool(item.get("caught")),
            }
            row.update(extras)
            rows.append(row)
    return rows


def snapshot() -> dict[str, Any]:
    state = load_state(STATE_PATH)
    latest = _latest_round()
    ingest = _read_json(REPORTS_ROOT / "generator-ingest.json")
    history = list(state.get("history") or [])
    with _lock:
        job = dict(_job)
        running = bool(job["running"] and _process and _process.poll() is None)
        if job["running"] and not running:
            _job["running"] = False
            job["running"] = False
            job["last_exit"] = None if _process is None else _process.returncode
            _job["last_exit"] = job["last_exit"]
    receipts = _receipt_rows(None, latest)
    if job.get("mode") == "ingest":
        if running and job.get("live_receipts"):
            receipts = list(job["live_receipts"])
            for row in receipts:
                row["id"] = _register_pdf(str(row.get("file") or ""))
        elif ingest:
            receipts = _receipt_rows(ingest, None)
    elif running and job.get("live_receipts") and job.get("mode") == "arena":
        receipts = list(job["live_receipts"])
        for row in receipts:
            row["id"] = _register_pdf(str(row.get("file") or ""))
    return {
        "running": running,
        "job": job,
        "round": int(state.get("round") or 0),
        "history": history,
        "weights": state.get("weights") or {},
        "trend": _trend(history),
        "latest": latest,
        "ingest": ingest,
        "receipts": receipts,
    }


def _append_log(line: str) -> None:
    _job["log"] = (list(_job["log"]) + [line])[-40:]


def _watch_process(proc: subprocess.Popen[str], mode: str) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        text = line.strip()
        if text:
            with _lock:
                if text.startswith("PROGRESS::"):
                    try:
                        progress = json.loads(text.removeprefix("PROGRESS::"))
                    except json.JSONDecodeError:
                        _append_log(text)
                    else:
                        receipt = progress.get("receipt") or {}
                        receipt["id"] = _register_pdf(str(receipt.get("file") or ""))
                        _job["progress_done"] = int(progress.get("done") or 0)
                        _job["progress_total"] = int(progress.get("total") or 0)
                        _job["current_receipt"] = receipt
                        _job["live_receipts"] = (
                            list(_job.get("live_receipts") or []) + [receipt]
                        )[-40:]
                elif text.startswith("ROUND::"):
                    try:
                        payload = json.loads(text.removeprefix("ROUND::"))
                    except json.JSONDecodeError:
                        _append_log(text)
                    else:
                        rows = _receipt_rows(None, payload)
                        _job["progress_done"] = int(payload.get("round") or 0)
                        _job["current_receipt"] = rows[0] if rows else None
                        _job["live_receipts"] = rows
                else:
                    _append_log(text)
    code = proc.wait()
    with _lock:
        global _process
        if _process is proc:
            _job["running"] = False
            _job["last_exit"] = code
            _append_log(f"{mode} stopped ({code})")
            _process = None


def start_job(mode: str, rounds: int = 1) -> dict[str, Any]:
    global _process
    with _lock:
        if _process is not None and _process.poll() is None:
            return {"ok": False, "error": "already running"}
        command = [
            sys.executable,
            "-u",
            "-m",
            "arena.orchestrator" if mode == "arena" else "arena.ingest_external",
        ]
        if mode == "arena":
            command += [
                "--rounds",
                "1",
                "--forever",
                "--until-pause",
                "--interval-seconds",
                "2",
            ]
        else:
            command += ["--limit", "20"]
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        _process = proc
        _job.update(
            {
                "running": True,
                "mode": mode,
                "started_at": time.time(),
                "last_exit": None,
                "progress_done": 0,
                "progress_total": 20 if mode == "ingest" else 0,
                "current_receipt": None,
                "live_receipts": [],
            }
        )
        _append_log(f"start {mode}")
        threading.Thread(target=_watch_process, args=(proc, mode), daemon=True).start()
        return {"ok": True, "mode": mode}


def stop_job() -> dict[str, Any]:
    global _process
    with _lock:
        proc = _process
        if proc is None or proc.poll() is not None:
            _job["running"] = False
            return {"ok": True, "running": False}
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            proc.send_signal(signal.SIGTERM)
        _job["running"] = False
        _append_log("paused")
        return {"ok": True, "running": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, code: int, payload: dict[str, Any] | bytes, content_type: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_pdf(self, target: Path) -> None:
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", 'inline; filename="preview.pdf"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            html = (DASHBOARD_DIR / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path == "/api/snapshot":
            self._send(200, snapshot())
            return
        if path.startswith("/pdf/"):
            target = _files.get(path.rsplit("/", 1)[-1])
            if target is None or not target.is_file():
                self._send(404, {"error": "file not allowed"})
                return
            self._send_pdf(target)
            return
        if path == "/file":
            query = parse_qs(urlparse(self.path).query)
            target = _safe_pdf(unquote((query.get("p") or [""])[0]))
            if target is None:
                self._send(404, {"error": "file not allowed"})
                return
            self._send_pdf(target)
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}
        if path == "/api/start":
            mode = str(body.get("mode") or "arena")
            if mode not in {"arena", "ingest"}:
                self._send(400, {"ok": False, "error": "bad mode"})
                return
            self._send(200, start_job(mode, int(body.get("rounds") or 1)))
            return
        if path == "/api/pause":
            self._send(200, stop_job())
            return
        if path == "/api/open":
            target = _files.get(str(body.get("id") or "")) or _safe_pdf(
                str(body.get("file") or "")
            )
            if target is None:
                self._send(404, {"ok": False, "error": "file not allowed"})
                return
            os.startfile(target)  # Windows default PDF viewer
            self._send(200, {"ok": True})
            return
        self._send(404, {"error": "not found"})


def main() -> int:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"dashboard {url}")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_job()
        server.shutdown()
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
