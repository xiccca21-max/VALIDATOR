"""
Sber SBP deep layout/operator drift checks (safe mode).

Design goal: detect suspicious template drift for analyst visibility without
forcing FAKE verdict for future genuine template updates.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import fitz
except ImportError:
    fitz = None

from .structure import content_stream_bytes
from .structure import content_skeleton_hash

_PROFILE_PATH = Path(__file__).with_name("bank_specs") / "sber_sbp_layout.json"

_Y_LABELS = (
    "идентификатор операции",
    "сумма операции",
    "комиссия",
    "дата и время",
    "банк получателя",
    "статус",
)

_TM_RE = re.compile(rb"\sTm\b")
_TJ_RE = re.compile(rb"\sTj\b|\sTJ\b")


@dataclass
class LayoutFlag:
    code: str
    detail: str


@dataclass
class LayoutResult:
    flags: list[LayoutFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def load_profile() -> dict:
    if not _PROFILE_PATH.is_file():
        return {}
    try:
        return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def extract_layout_features(pdf_bytes: bytes) -> dict:
    if not fitz:
        return {}
    feats: dict = {"labels_norm_y": {}}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        feats["page_w"] = round(float(page.rect.width), 2)
        feats["page_h"] = round(float(page.rect.height), 2)
        text_dict = page.get_text("dict")
        page_h = float(page.rect.height or 1.0)
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = (span.get("text") or "").strip().lower()
                    if not t:
                        continue
                    oy = float(span.get("origin", [0.0, 0.0])[1] or 0.0)
                    for label in _Y_LABELS:
                        if label in t and label not in feats["labels_norm_y"]:
                            feats["labels_norm_y"][label] = round(oy / page_h, 5)
        doc.close()
    except Exception:
        return {}

    content = content_stream_bytes(pdf_bytes)
    feats["content_size"] = len(content) if content else 0
    feats["tm_count"] = len(_TM_RE.findall(content)) if content else 0
    feats["tj_count"] = len(_TJ_RE.findall(content)) if content else 0
    feats["operator_signature"] = content_skeleton_hash(pdf_bytes)
    return feats


def check_sber_sbp_layout(pdf_bytes: bytes, *, profile: dict | None = None) -> LayoutResult:
    res = LayoutResult()
    profile = profile or load_profile()
    if not profile:
        res.stats["profile_missing"] = True
        return res

    feats = extract_layout_features(pdf_bytes)
    res.stats = feats
    if not feats:
        res.flags.append(LayoutFlag(
            "SBER_SBP_LAYOUT_PARSE_FAILED",
            "не удалось извлечь геометрию/операторы для deep-сравнения",
        ))
        return res

    # Operator drift (size + operator counts)
    for key in ("content_size", "tm_count", "tj_count"):
        bounds = (profile.get("ops_envelope") or {}).get(key)
        val = int(feats.get(key) or 0)
        if not bounds or len(bounds) != 2:
            continue
        lo, hi = int(bounds[0]), int(bounds[1])
        if val < lo or val > hi:
            res.flags.append(LayoutFlag(
                "SBER_SBP_OPERATOR_DRIFT",
                f"{key}={val} вне профиля оригиналов ({lo}-{hi})",
            ))
    known_ops = set(profile.get("operator_signatures") or [])
    op_sig = feats.get("operator_signature")
    if known_ops and op_sig and op_sig not in known_ops:
        res.flags.append(LayoutFlag(
            "SBER_SBP_OPERATOR_DRIFT",
            f"operator signature {op_sig} не входит в эталонные шаблоны ({len(known_ops)} шт.)",
        ))

    # Geometry drift (label Y position, normalized by page height)
    labels_profile = profile.get("labels_norm_y") or {}
    labels_cur = feats.get("labels_norm_y") or {}
    missing = []
    for label, bounds in labels_profile.items():
        if label not in labels_cur:
            missing.append(label)
            continue
        if not bounds or len(bounds) != 2:
            continue
        lo, hi = float(bounds[0]), float(bounds[1])
        y = float(labels_cur[label])
        if y < lo or y > hi:
            res.flags.append(LayoutFlag(
                "SBER_SBP_LAYOUT_DRIFT",
                f"поле «{label}» на позиции y={y:.5f} вне профиля ({lo:.5f}-{hi:.5f})",
            ))
    if len(missing) >= 3:
        res.flags.append(LayoutFlag(
            "SBER_SBP_LAYOUT_MISSING_FIELDS",
            "не найдены ключевые поля макета: " + ", ".join(missing[:4]),
        ))
    return res
