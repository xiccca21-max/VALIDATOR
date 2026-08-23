from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from fontTools.ttLib import TTFont

from detector.alfa_v2.fonts import _sfnt_table_tags, _tounicode, _used_cids
from detector.alfa_v2.pdfutil import objects, stream_role
from detector.alfa_v2.sbp import validate_sbp_text


ZAP_ROOT = Path(r"C:\Users\fanis\OneDrive\Desktop\ЗАПАСКА 13.07.26")
ROOT = ZAP_ROOT / "output"
LOG_DIR = ROOT / "bankpdf_checks"
CHAT_EXPORT = LOG_DIR / "chat_today.json"
OUT_DIR = Path(__file__).resolve().parent / "analysis"

LABELS = {
    "amount": "Сумма перевода",
    "commission": "Комиссия",
    "operation_datetime": "Дата и время перевода",
    "operation_id": "Номер операции",
    "fio": "Получатель",
    "phone": "Номер телефона получателя",
    "bank": "Банк получателя",
    "account": "Счёт списания",
    "sbp_id": "Идентификатор операции в СБП",
    "message": "Сообщение получателю",
}


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def verdict_from_messages(messages: list[dict[str, Any]]) -> tuple[str, str]:
    texts = [str(m.get("text") or "") for m in messages[1:]]
    joined = "\n".join(texts)
    if "✅" in joined:
        return "PASS", joined
    if "❌" in joined:
        return "FAIL", joined
    return "UNKNOWN", joined


def load_chat_uploads() -> dict[int, dict[str, Any]]:
    try:
        messages = json.loads(CHAT_EXPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    uploads: dict[int, dict[str, Any]] = {}
    for index, message in enumerate(messages):
        if not message.get("out") or not message.get("has_media"):
            continue
        replies: list[dict[str, Any]] = []
        for candidate in messages[index + 1 :]:
            if candidate.get("out") and candidate.get("has_media"):
                break
            if not candidate.get("out"):
                replies.append(candidate)
        verdict, response = verdict_from_messages([message, *replies])
        saved = Path(str(message.get("saved") or ""))
        uploads[int(message["id"])] = {
            "message_id": int(message["id"]),
            "filename": str(message.get("fname") or message.get("text") or saved.name),
            "saved_path": saved,
            "verdict": verdict,
            "response": response,
            "reuse_notice": (
                "Предыдущие проверки" in response or "проверялся другим пользователем" in response
            ),
            "sent_at": f"2026-08-14T{message.get('time')}+03:00" if message.get("time") else "",
        }
    return uploads


def resolve_pdf(raw_value: str, logged_size: int | None, chat_saved: Path | None) -> tuple[Path, bool]:
    raw = Path(raw_value)
    candidates = [raw]
    if not raw.is_absolute():
        candidates.extend([ZAP_ROOT / raw, ROOT / raw, LOG_DIR / raw.name])
    existing = [candidate for candidate in candidates if candidate.is_file()]
    saved_ok = bool(chat_saved and chat_saved.is_file())
    if saved_ok:
        assert chat_saved is not None
        if logged_size is None or chat_saved.stat().st_size == logged_size:
            return chat_saved, True
    if logged_size is not None:
        exact_size = next((candidate for candidate in existing if candidate.stat().st_size == logged_size), None)
        if exact_size:
            return exact_size, False
    if saved_ok:
        assert chat_saved is not None
        return chat_saved, True
    return (existing[0] if existing else raw), False


def extract_fields(text: str) -> dict[str, str]:
    lines = [line.replace("\xa0", " ").strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    out: dict[str, str] = {}
    if "Сформирована" in lines:
        index = lines.index("Сформирована")
        if index + 1 < len(lines):
            out["formed_datetime"] = lines[index + 1].removesuffix(" мск").strip()
    for key, label in LABELS.items():
        try:
            index = lines.index(label)
        except ValueError:
            continue
        if index + 1 < len(lines):
            out[key] = lines[index + 1].removesuffix(" мск").strip()
    return out


def parse_visible_datetime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
    except (TypeError, ValueError):
        return None


def font_features(pdf: bytes, pdf_objects: dict[int, Any]) -> dict[str, Any]:
    content_objects = [obj for obj in pdf_objects.values() if stream_role(obj) == "content"]
    font_objects = [obj for obj in pdf_objects.values() if stream_role(obj) == "font"]
    cmap_objects = [obj for obj in pdf_objects.values() if stream_role(obj) == "tounicode"]
    image_objects = [obj for obj in pdf_objects.values() if stream_role(obj) == "image"]
    used_by_font = _used_cids(pdf_objects)
    used = sorted(set().union(*used_by_font.values())) if used_by_font else []
    out: dict[str, Any] = {
        "content_sha": sha256(content_objects[0].decoded_stream or b"") if content_objects else "",
        "content_decoded_size": len(content_objects[0].decoded_stream or b"") if content_objects else None,
        "content_raw_size": len(content_objects[0].raw_stream or b"") if content_objects else None,
        "font_sha": sha256(font_objects[0].decoded_stream or b"") if font_objects else "",
        "font_decoded_size": len(font_objects[0].decoded_stream or b"") if font_objects else None,
        "font_raw_size": len(font_objects[0].raw_stream or b"") if font_objects else None,
        "tounicode_sha": sha256(cmap_objects[0].decoded_stream or b"") if cmap_objects else "",
        "tounicode_decoded_size": len(cmap_objects[0].decoded_stream or b"") if cmap_objects else None,
        "used_cid_count": len(used),
        "used_cid_min": min(used) if used else None,
        "used_cid_max": max(used) if used else None,
        "image_shas": "|".join(sorted(sha256(obj.decoded_stream or b"") for obj in image_objects)),
    }
    if not font_objects:
        return out
    font_blob = font_objects[0].decoded_stream or b""
    out["sfnt_order"] = "|".join(_sfnt_table_tags(font_blob))
    try:
        tt = TTFont(BytesIO(font_blob), lazy=False)
        out["num_glyphs"] = int(tt["maxp"].numGlyphs)
        out["check_sum_adjustment"] = int(tt["head"].checkSumAdjustment)
        glyph_order = tt.getGlyphOrder()
        cmap = _tounicode(cmap_objects[0].decoded_stream or b"") if cmap_objects else {}
        nul_cids = sorted(cid for cid, char in cmap.items() if char == "\x00")
        out["nul_cids"] = "|".join(str(cid) for cid in nul_cids)
        out["nul_count"] = len(nul_cids)
        out["mapped_cid_count"] = len(cmap)
        out["unused_mapped_count"] = len(set(cmap) - set(used))
        out["glyph_order_sha"] = sha256("\0".join(glyph_order).encode("utf-8"))
        tt.close()
    except Exception as exc:  # forensic harvesting must continue on malformed fonts
        out["font_parse_error"] = type(exc).__name__
    return out


def extract_pdf_features(path: Path) -> dict[str, Any]:
    pdf = path.read_bytes()
    feature: dict[str, Any] = {
        "pdf_sha": sha256(pdf),
        "pdf_size": len(pdf),
        "pdf_path": str(path),
    }
    try:
        document = fitz.open(stream=pdf, filetype="pdf")
        text = "".join(page.get_text() for page in document)
        metadata = document.metadata or {}
        document.close()
        feature["text_sha"] = sha256(text.encode("utf-8"))
        feature["producer"] = metadata.get("producer") or ""
        feature.update(extract_fields(text))
        sbp = validate_sbp_text(text)
        feature["sbp_lag_seconds"] = sbp.stats.get("completion_lag_seconds")
        feature["sbp_flag_codes"] = "|".join(flag.code for flag in sbp.flags)
    except Exception as exc:
        feature["pdf_parse_error"] = type(exc).__name__
        return feature
    pdf_objects = objects(pdf)
    feature["object_count"] = len(pdf_objects)
    feature.update(font_features(pdf, pdf_objects))
    visible = parse_visible_datetime(feature.get("operation_datetime", ""))
    if visible:
        feature["operation_hour"] = visible.hour
        feature["operation_minute"] = visible.minute
        feature["operation_second"] = visible.second
    amount_digits = re.sub(r"\D", "", feature.get("amount", ""))
    feature["amount_value"] = int(amount_digits) if amount_digits else None
    feature["fio_length"] = len(feature.get("fio", ""))
    feature["fio_initial"] = feature.get("fio", "")[-1:] or ""
    feature["phone_digits"] = re.sub(r"\D", "", feature.get("phone", ""))
    return feature


def load_submissions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}
    chat_uploads = load_chat_uploads()
    logged_message_ids: set[int] = set()
    for log_path in sorted(LOG_DIR.glob("20*.json")):
        try:
            payload = json.loads(log_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        messages = payload.get("messages") or []
        if not messages or not payload.get("pdf"):
            continue
        verdict, response = verdict_from_messages(messages)
        if verdict == "UNKNOWN":
            continue
        message_id = int(messages[0].get("id") or 0)
        logged_message_ids.add(message_id)
        chat = chat_uploads.get(message_id)
        logged_size = int(payload["size"]) if payload.get("size") is not None else None
        pdf_path, exact_chat_copy = resolve_pdf(
            str(payload["pdf"]),
            logged_size,
            chat["saved_path"] if chat else None,
        )
        sent_at = parse_dt(str(messages[0].get("date") or ""))
        row: dict[str, Any] = {
            "log_path": str(log_path),
            "filename": str(messages[0].get("text") or pdf_path.name),
            "sent_at": sent_at.isoformat() if sent_at else "",
            "message_id": message_id,
            "verdict": verdict,
            "response": response,
            "source_pdf_path": str(pdf_path),
            "pdf_exists": pdf_path.exists(),
            "logged_size": logged_size,
            "exact_chat_copy": exact_chat_copy,
            "reuse_notice": bool(chat and chat.get("reuse_notice")),
            "source": "json_log",
        }
        if pdf_path.exists():
            key = str(pdf_path.resolve()).lower()
            if key not in cache:
                try:
                    cache[key] = extract_pdf_features(pdf_path)
                except Exception as exc:
                    cache[key] = {"feature_error": type(exc).__name__, "pdf_path": str(pdf_path)}
            row.update(cache[key])
            row["size_matches_log"] = logged_size is None or row.get("pdf_size") == logged_size
            row["bytes_reliable"] = bool(exact_chat_copy or row["size_matches_log"])
        rows.append(row)
    for message_id, chat in chat_uploads.items():
        if message_id in logged_message_ids or chat["verdict"] == "UNKNOWN":
            continue
        pdf_path = chat["saved_path"]
        row = {
            "log_path": str(CHAT_EXPORT),
            "filename": chat["filename"],
            "sent_at": chat["sent_at"],
            "message_id": message_id,
            "verdict": chat["verdict"],
            "response": chat["response"],
            "source_pdf_path": str(pdf_path),
            "pdf_exists": pdf_path.is_file(),
            "logged_size": None,
            "exact_chat_copy": True,
            "reuse_notice": chat["reuse_notice"],
            "source": "chat_export_only",
        }
        if pdf_path.is_file():
            key = str(pdf_path.resolve()).lower()
            if key not in cache:
                try:
                    cache[key] = extract_pdf_features(pdf_path)
                except Exception as exc:
                    cache[key] = {"feature_error": type(exc).__name__, "pdf_path": str(pdf_path)}
            row.update(cache[key])
            row["size_matches_log"] = True
            row["bytes_reliable"] = True
        rows.append(row)
    rows.sort(key=lambda row: (row.get("sent_at") or "", int(row.get("message_id") or 0)))
    return rows


def add_history_features(rows: list[dict[str, Any]]) -> None:
    seen: dict[str, Counter[str]] = defaultdict(Counter)
    prior_times: list[datetime] = []
    prior_verdicts: list[str] = []
    previous_time: datetime | None = None
    for index, row in enumerate(rows):
        sent = parse_dt(row.get("sent_at", ""))
        row["send_index"] = index + 1
        row["gap_from_previous_seconds"] = (
            (sent - previous_time).total_seconds() if sent and previous_time else None
        )
        row["previous_verdict"] = prior_verdicts[-1] if prior_verdicts else ""
        if sent:
            row["prior_submissions_60s"] = sum(
                1 for value in prior_times if 0 <= (sent - value).total_seconds() <= 60
            )
            row["prior_passes_60s"] = sum(
                1
                for value, verdict in zip(prior_times, prior_verdicts)
                if verdict == "PASS" and 0 <= (sent - value).total_seconds() <= 60
            )
            row["prior_submissions_300s"] = sum(
                1 for value in prior_times if 0 <= (sent - value).total_seconds() <= 300
            )
            row["prior_passes_300s"] = sum(
                1
                for value, verdict in zip(prior_times, prior_verdicts)
                if verdict == "PASS" and 0 <= (sent - value).total_seconds() <= 300
            )
        for name in (
            "pdf_sha",
            "font_sha",
            "content_sha",
            "operation_id",
            "sbp_id",
            "phone_digits",
            "account",
            "operation_datetime",
        ):
            value = str(row.get(name) or "")
            row[f"prior_same_{name}_count"] = sum(seen[f"{name}:{value}"].values()) if value else 0
            row[f"prior_same_{name}_pass"] = seen[f"{name}:{value}"]["PASS"] if value else 0
            row[f"prior_same_{name}_fail"] = seen[f"{name}:{value}"]["FAIL"] if value else 0
            if value:
                seen[f"{name}:{value}"][row["verdict"]] += 1
        if sent:
            prior_times.append(sent)
            previous_time = sent
        prior_verdicts.append(row["verdict"])


def contradiction_groups(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            grouped[value].append(row)
    result = []
    for value, members in grouped.items():
        verdicts = {member["verdict"] for member in members}
        if len(verdicts) > 1:
            result.append(
                {
                    key: value,
                    "passes": sum(member["verdict"] == "PASS" for member in members),
                    "fails": sum(member["verdict"] == "FAIL" for member in members),
                    "events": [
                        {
                            "filename": member["filename"],
                            "sent_at": member["sent_at"],
                            "verdict": member["verdict"],
                            "message_id": member["message_id"],
                        }
                        for member in members
                    ],
                }
            )
    return sorted(result, key=lambda item: (-(item["passes"] + item["fails"]), str(item[key])))


def write_outputs(rows: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "bankpdf_history_dataset.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fieldnames = sorted({key for row in rows for key in row})
    with (OUT_DIR / "bankpdf_history_dataset.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    reliable_rows = [row for row in rows if row.get("bytes_reliable")]
    summary = {
        "total_submissions": len(rows),
        "passes": sum(row["verdict"] == "PASS" for row in rows),
        "fails": sum(row["verdict"] == "FAIL" for row in rows),
        "missing_pdfs": sum(not row.get("pdf_exists") for row in rows),
        "reliable_byte_submissions": len(reliable_rows),
        "unreliable_overwritten_paths": len(rows) - len(reliable_rows),
        "unique_pdf_sha": len({row.get("pdf_sha") for row in reliable_rows if row.get("pdf_sha")}),
        "unique_font_sha": len({row.get("font_sha") for row in reliable_rows if row.get("font_sha")}),
        "pdf_sha_contradictions": contradiction_groups(reliable_rows, "pdf_sha"),
        "font_sha_contradictions": contradiction_groups(reliable_rows, "font_sha"),
        "content_sha_contradictions": contradiction_groups(reliable_rows, "content_sha"),
    }
    (OUT_DIR / "bankpdf_history_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in summary.items() if not isinstance(value, list)}, indent=2))
    print("pdf_sha_contradictions", len(summary["pdf_sha_contradictions"]))
    print("font_sha_contradictions", len(summary["font_sha_contradictions"]))
    print("content_sha_contradictions", len(summary["content_sha_contradictions"]))


def main() -> None:
    rows = load_submissions()
    add_history_features(rows)
    write_outputs(rows)


if __name__ == "__main__":
    main()
