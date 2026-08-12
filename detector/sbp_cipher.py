"""
Общий мягкий шифр СБП-ID НСПК (32 символа) для всех банков.
Используется Т-Банком, Альфой и bank_spec_engine.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

_DATE_FULL = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
)
_DATE_MIN = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})(?!\d)",
)
_SBP_ID_RE = re.compile(r"[AB][0-9A-Z]{31}")
_CORE_SUFFIXES = frozenset({"00117", "00116"})
_REF_MAX_LETTERS = 2
_VALID_SEPARATORS = frozenset("GB0")

_DATE_LABELS = (
    "дата и время операции",
    "дата и время перевода",
    "дата операции",
    "дата платежа",
)


@dataclass
class CipherFlag:
    code: str
    detail: str


@dataclass
class CipherResult:
    flags: list[CipherFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, code: str, detail: str) -> None:
        self.flags.append(CipherFlag(code, detail))


def extract_sbp_opid(text: str) -> str | None:
    flat = re.sub(r"\s+", "", text or "")
    m = _SBP_ID_RE.search(flat)
    return m.group(0) if m else None


def extract_receipt_datetime(text: str, *, prefer_first_line: bool = True) -> datetime.datetime | None:
    """Дата операции: первая строка (Т-Банк) или поле с меткой."""
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")

    if prefer_first_line:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            for pat in (_DATE_FULL, _DATE_MIN):
                m = pat.search(line)
                if m:
                    return _dt_from_match(m)
            if line and not line[0].isdigit():
                break

    low = raw.lower()
    for label in _DATE_LABELS:
        idx = low.find(label)
        if idx >= 0:
            m = _DATE_FULL.search(raw[idx:]) or _DATE_MIN.search(raw[idx:])
            if m:
                return _dt_from_match(m)

    m = _DATE_FULL.search(raw) or _DATE_MIN.search(raw)
    return _dt_from_match(m) if m else None


def _dt_from_match(m: re.Match) -> datetime.datetime | None:
    g = m.groups()
    try:
        if len(g) == 6:
            d, mo, y, h, mi, s = map(int, g)
            return datetime.datetime(y, mo, d, h, mi, s)
        d, mo, y, h, mi = map(int, g)
        return datetime.datetime(y, mo, d, h, mi, 0)
    except ValueError:
        return None


def validate_nspk_sbp_cipher(
    opid: str,
    text: str = "",
    *,
    prefer_first_line_date: bool = True,
) -> CipherResult:
    res = CipherResult()
    if not opid:
        res.add("SBP_CIPHER_MISSING", "не найден идентификатор операции СБП")
        return res

    res.stats["opid"] = opid

    if len(opid) != 32:
        res.add("SBP_CIPHER_STRUCTURE", f"длина СБП-ID {len(opid)} вместо 32 символов")
        return res

    if not re.fullmatch(r"^[AB][0-9A-Z]{31}$", opid):
        res.add("SBP_CIPHER_STRUCTURE", f"СБП-ID «{opid}» содержит недопустимые символы")
        return res

    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.add("SBP_CIPHER_STRUCTURE", "блок даты/времени в СБП-ID не числовой")
        return res

    ref = opid[11:17]
    if not re.fullmatch(r"[0-9A-Z]{6}", ref):
        res.add("SBP_CIPHER_STRUCTURE", f"ссылка «{ref}» неверного формата")
    elif opid[16] != "0":
        res.add("SBP_CIPHER_STRUCTURE", f"позиция 17 СБП-ID должна быть «0» (там «{opid[16]}»)")
    elif not opid[14].isdigit():
        res.add("SBP_CIPHER_STRUCTURE", f"позиция 15 СБП-ID должна быть цифрой (там «{opid[14]}»)")

    if opid[17] not in _VALID_SEPARATORS and not opid[17].isalpha():
        res.add("SBP_CIPHER_STRUCTURE", f"разделитель на позиции 18 «{opid[17]}» недопустим")

    if not opid[18:22].isdigit():
        res.add("SBP_CIPHER_STRUCTURE", "код канала в СБП-ID не числовой")

    if opid[22:27] not in _CORE_SUFFIXES:
        res.add("SBP_CIPHER_STRUCTURE", f"ядро «{opid[22:27]}» — ожидается 00117 или 00116")

    if not opid[27:32].isdigit():
        res.add("SBP_CIPHER_STRUCTURE", "хвост [28–32] должен быть 5 цифр")

    if sum(c.isalpha() for c in ref) > _REF_MAX_LETTERS:
        res.add(
            "SBP_CIPHER_REFERENCE",
            f"ссылка «{ref}» слишком буквенная — типично для сгенерированного ID",
        )

    dt = extract_receipt_datetime(text, prefer_first_line=prefer_first_line_date)
    if dt:
        enc_doy = int(opid[1:5]) % 1000
        enc_hour = int(opid[5:7])
        enc_min = int(opid[7:9])
        real_doy = dt.timetuple().tm_yday
        real_utc = (dt.hour - 3) % 24
        if abs(enc_doy - real_doy) > 2:
            res.add(
                "SBP_CIPHER_TIMESTAMP",
                f"в СБП-ID день года {enc_doy}, в чеке {real_doy}",
            )
        else:
            hour_diff = min(abs(enc_hour - real_utc), 24 - abs(enc_hour - real_utc))
            if hour_diff > 3:
                res.add("SBP_CIPHER_TIMESTAMP", f"в СБП-ID час UTC {enc_hour}, в чеке {real_utc} UTC")
            elif abs(enc_min - dt.minute) > 5 and abs(enc_min - dt.minute) < 55:
                res.stats["minute_drift"] = abs(enc_min - dt.minute)

    return res
