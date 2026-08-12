#!/usr/bin/env python3
"""Build Alfa v2 shell/trailer registry from the 40-PDF corpus."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.alfa_v2.pdfutil import objects, stream_role
from detector.alfa_v2.profile_semantics import (
    classify_submethod,
    extract_operation_datetime,
    extract_operation_ids,
    parse_amounts,
)
from detector.alfa_v2.shell_clone import extract_trailer_id

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")
OUT = ROOT / "detector" / "alfa_v2" / "atlas_data" / "shell_registry.v1.json"
_ID_RE = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_PHONE_RE = re.compile(r"\+7[\d\s()_-]{10,}")
_ACCOUNT_RE = re.compile(r"\b40817\d{15}\b")
_BANK_RE = re.compile(
    r"(сбербанк|тинькофф|т-банк|втб|альфа-банк|газпромбанк|отп банк)",
    re.I,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity(text: str) -> dict[str, str]:
    method = classify_submethod(text)
    amounts = parse_amounts(text)
    dt = extract_operation_datetime(text)
    op_ids = extract_operation_ids(text)
    phone = _PHONE_RE.search(text or "")
    account = _ACCOUNT_RE.search(text or "")
    bank = _BANK_RE.search(text or "")
    receiver = ""
    for label in ("получатель", "фио получателя"):
        match = re.search(label + r"\s*[:\n]\s*([^\n]+)", text or "", re.I)
        if match:
            receiver = match.group(1).strip()
            break
    sbp = re.search(r"(?<![A-Z0-9])([AB][0-9A-Z]{31})(?![A-Z0-9])", (text or "").upper())
    return {
        "method": method,
        "amount": str(amounts.amount) if amounts.amount is not None else "",
        "fee": str(amounts.fee) if amounts.fee is not None else "",
        "operation_datetime": dt.strftime("%d.%m.%Y %H:%M:%S") if dt else "",
        "operation_id": op_ids[0] if op_ids else "",
        "receiver": receiver,
        "phone": re.sub(r"\D", "", phone.group(0)) if phone else "",
        "recipient_bank": bank.group(1).lower() if bank else "",
        "debit_account": account.group(0) if account else "",
        "sbp_id": sbp.group(1) if sbp else "",
    }


def main() -> None:
    import fitz

    by_trailer: dict[str, dict] = {}
    for path in sorted(CORPUS.glob("*.pdf")):
        data = path.read_bytes()
        trailer = extract_trailer_id(data)
        if not trailer:
            continue
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        producer = str(doc.metadata.get("producer") or "")
        doc.close()
        obj_map = {}
        images = []
        content_hashes = []
        for number, obj in objects(data).items():
            if obj.decoded_stream is None:
                continue
            role = stream_role(obj)
            digest = _sha(obj.decoded_stream)
            obj_map[str(number)] = {"role": role, "decoded_sha256": digest}
            if role == "image":
                images.append(digest)
            if role == "content":
                content_hashes.append(digest)
        content_sha = _sha("\n".join(content_hashes).encode()) if content_hashes else ""
        emitter = (
            "oracle"
            if "oracle" in producer.lower()
            else "quartz"
            if "quartz" in producer.lower()
            else "unknown"
        )
        by_trailer[trailer] = {
            "file_name": path.name,
            "file_sha256": _sha(data),
            "emitter": emitter,
            "producer": producer,
            "content_sha256": content_sha,
            "image_decoded_sha256": sorted(set(images)),
            "objects": obj_map,
            "identity": _identity(text),
        }

    payload = {
        "schema": "alfa-v2-shell-registry",
        "version": "1.0.0",
        "count": len(by_trailer),
        "by_trailer_id": by_trailer,
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} entries={len(by_trailer)}")


if __name__ == "__main__":
    main()
