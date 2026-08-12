"""
Шифр идентификатора СБП в чеках Альфа-Банка (32 символа).

Структура (как НСПК + хвост банка):
  [0]       A|B — тип операции
  [1:5]     (год-2020)*1000 + день_года
  [5:7]     час UTC (в чеке МСК−3)
  [7:9]     минута
  [9:11]    секунда
  [11:17]   6-символьная ссылка (последний символ [16] = '0')
  [17]      разделитель-буква (G|B, реже цифра у других банков)
  [18:22]   код канала (цифры)
  [22:27]   ядро эмитента (00117 или 00116)
  [27:32]   5-значный хвост (маршрут/банк в цепочке СБП)

Проверяем структуру и согласованность времени с датой в чеке.
Неизвестный хвост [27:32] — не фейк (только stats), пока нет в корпусе.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
)
_CORE_SUFFIXES = frozenset({"00117", "00116"})
_REF_MAX_LETTERS = 2

_EXT_PATH = Path(__file__).with_name("alfa_sbp_extensions.json")


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


def load_observed_extensions() -> frozenset[str]:
    if _EXT_PATH.is_file():
        data = json.loads(_EXT_PATH.read_text(encoding="utf-8"))
        return frozenset(data.get("extensions", []))
    return frozenset()


def _extract_operation_datetime(text: str) -> datetime.datetime | None:
    raw = (text or "").replace("\xa0", " ")
    for label in (
        "дата и время перевода",
        "дата и время операции",
        "дата операции",
    ):
        idx = raw.lower().find(label)
        if idx >= 0:
            m = _DATE_RE.search(raw[idx:])
            if m:
                d, mo, y, h, mi, s = map(int, m.groups())
                try:
                    return datetime.datetime(y, mo, d, h, mi, s)
                except ValueError:
                    pass
    m = _DATE_RE.search(raw)
    if not m:
        return None
    d, mo, y, h, mi, s = map(int, m.groups())
    try:
        return datetime.datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def validate_alfa_sbp_cipher(opid: str, text: str = "") -> CipherResult:
    res = CipherResult()
    if not opid:
        res.add("ALFA_SBP_ID_MISSING", "не найден идентификатор операции в СБП")
        return res

    res.stats["opid"] = opid
    res.stats["length"] = len(opid)

    if len(opid) != 32:
        res.add(
            "ALFA_SBP_ID_STRUCTURE",
            f"длина ID {len(opid)} вместо 32 символов",
        )
        return res

    if not re.fullmatch(r"^[AB][0-9A-Z]{31}$", opid):
        res.add("ALFA_SBP_ID_STRUCTURE", f"ID «{opid}» содержит недопустимые символы")
        return res

    blocks = {
        "date_block": opid[1:5],
        "hour": opid[5:7],
        "minute": opid[7:9],
        "second": opid[9:11],
        "reference": opid[11:17],
        "separator": opid[17],
        "channel": opid[18:22],
        "core": opid[22:27],
        "tail": opid[27:32],
    }
    res.stats.update(blocks)

    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.add("ALFA_SBP_ID_STRUCTURE", "блок даты/времени в ID не числовой")
        return res

    ref = opid[11:17]
    if not re.fullmatch(r"[0-9A-Z]{6}", ref):
        res.add("ALFA_SBP_ID_STRUCTURE", f"ссылка операции «{ref}» неверного формата")
    elif opid[16] != "0":
        res.add(
            "ALFA_SBP_ID_STRUCTURE",
            f"позиция 17 ID должна быть «0» (там «{opid[16]}»)",
        )

    letters_in_ref = sum(c.isalpha() for c in ref)
    if letters_in_ref > _REF_MAX_LETTERS:
        res.add(
            "ALFA_SBP_ID_REFERENCE",
            f"ссылка «{ref}» слишком «буквенная» ({letters_in_ref} букв) — "
            "типично для сгенерированного ID",
        )

    if not opid[17].isalpha():
        res.add(
            "ALFA_SBP_ID_STRUCTURE",
            f"разделитель на позиции 18 не буква (там «{opid[17]}»)",
        )

    if not opid[18:22].isdigit():
        res.add("ALFA_SBP_ID_STRUCTURE", "блок кода канала не числовой")

    if opid[22:27] not in _CORE_SUFFIXES:
        res.add(
            "ALFA_SBP_ID_STRUCTURE",
            f"ядро эмитента «{opid[22:27]}» — ожидается 00117 или 00116",
        )

    if not opid[27:32].isdigit():
        res.add("ALFA_SBP_ID_STRUCTURE", "хвост [27:32] должен быть 5 цифр")

    observed = load_observed_extensions()
    res.stats["tail_observed_in_corpus"] = opid[27:32] in observed
    if observed and opid[27:32] not in observed:
        res.stats["tail_unknown"] = True

    dt = _extract_operation_datetime(text)
    if dt:
        res.stats["receipt_datetime"] = dt.isoformat(sep=" ")
        enc_doy = int(opid[1:5]) % 1000
        enc_hour = int(opid[5:7])
        enc_min = int(opid[7:9])
        real_doy = dt.timetuple().tm_yday
        real_utc = (dt.hour - 3) % 24

        res.stats["encoded_doy"] = enc_doy
        res.stats["encoded_hour_utc"] = enc_hour

        # Жёстко только при явном рассогласовании даты (ID с другого дня).
        # Часы/минуты/секунды в оригиналах расходятся — не баним.
        if abs(enc_doy - real_doy) > 2:
            res.add(
                "ALFA_SBP_ID_TIMESTAMP",
                f"в ID день года {enc_doy}, в чеке {real_doy} — "
                "ID не соответствует дате операции",
            )
        else:
            hour_diff = min(abs(enc_hour - real_utc), 24 - abs(enc_hour - real_utc))
            if hour_diff > 4:
                res.stats["hour_drift"] = hour_diff
            if abs(enc_min - dt.minute) > 10 and abs(enc_min - dt.minute) < 50:
                res.stats["minute_drift"] = abs(enc_min - dt.minute)

    return res
