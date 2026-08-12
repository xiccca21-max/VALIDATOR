"""
Эталонные структурные профили T-Банк PDF.
Калибровка: 23 оригинала Receipt*.pdf (июнь 2026), см. docs/README_validator.md
"""

from __future__ import annotations

PROFILE_VERSION = "tbank_corpus_41_spec_2026_06"

# ── Каналы (тип перевода) ─────────────────────────────────────────────────────
# sbp   — есть блок «Идентификатор операции» (СБП, в т.ч. по номеру телефона)
# phone — «По номеру телефона» без СБП-ID (внутрибанковский перевод)
# card  — «По номеру карты» без СБП-ID
CHANNEL_SBP = "sbp"
CHANNEL_PHONE = "phone"
CHANNEL_CARD = "card"


def detect_receipt_channel(text: str) -> str:
    """Определить канал чека по тексту квитанции."""
    if not text:
        return CHANNEL_PHONE
    flat = " ".join(text.split()).lower()
    if any(m in flat for m in (
        "идентификатор операции",
        "id операции в сбп",
        "id операции сбп",
        "идентификатор операции в сбп",
        "номер операции в сбп",
    )):
        return CHANNEL_SBP
    if any(m in flat for m in (
        "по номеру карты",
        "с карты на карту",
        "перевод на карту",
    )):
        return CHANNEL_CARD
    if "на карту" in flat and ("перевод" in flat or "итого" in flat):
        return CHANNEL_CARD
    if "по номеру телефона" in flat:
        return CHANNEL_PHONE
    return CHANNEL_PHONE


# ── Подтипы перевода (для UI и условных проверок) ─────────────────────────────
SUBTYPE_SBP_PHONE = "sbp_phone"           # СБП по телефону → другой банк
SUBTYPE_SBP_CARD = "sbp_card"             # СБП по карте (редко)
SUBTYPE_INTRABANK_PHONE = "intrabank_phone"  # По телефону → клиент Т-Банка
SUBTYPE_CARD_NUMBER = "card_number"       # По номеру карты → другой банк
SUBTYPE_CARD_TRANSFER = "card_transfer"   # «На карту» (межкартовый, другой шаблон)
SUBTYPE_INTRABANK_CLIENT = "intrabank_client"  # «Клиенту Т-Банка»


def detect_receipt_subtype(text: str) -> str:
    """Детальный подтип чека по тексту (поверх канала sbp/phone/card)."""
    if not text:
        return SUBTYPE_INTRABANK_PHONE
    flat = " ".join(text.split()).lower()
    channel = detect_receipt_channel(text)

    if "клиенту т-банка" in flat or "клиенту т банка" in flat:
        return SUBTYPE_INTRABANK_CLIENT

    if channel == CHANNEL_SBP:
        if "по номеру карты" in flat:
            return SUBTYPE_SBP_CARD
        return SUBTYPE_SBP_PHONE

    if channel == CHANNEL_CARD:
        if "на карту" in flat:
            return SUBTYPE_CARD_TRANSFER
        if "по номеру карты" in flat:
            return SUBTYPE_CARD_NUMBER
        return SUBTYPE_CARD_TRANSFER

    return SUBTYPE_INTRABANK_PHONE


def receipt_subtype_label(subtype: str) -> str:
    """Человекочитаемая подпись типа чека для бота."""
    labels = {
        SUBTYPE_SBP_PHONE: "СБП Т-Банк",
        SUBTYPE_SBP_CARD: "СБП Т-Банк",
        SUBTYPE_INTRABANK_PHONE: "Чек Т-Банк, по телефону",
        SUBTYPE_CARD_NUMBER: "Чек Т-Банк, по номеру карты",
        SUBTYPE_CARD_TRANSFER: "Чек Т-Банк, на карту другого банка",
        SUBTYPE_INTRABANK_CLIENT: "Чек Т-Банк, клиенту Т-Банка",
    }
    return labels.get(subtype, "Чек Т-Банк")


# Файлы корпуса (все оригиналы)
CORPUS_ORIGINALS = (
    "Receipt.pdf",
    "Receipt (1).pdf", "Receipt (2).pdf", "Receipt (3).pdf", "Receipt (4).pdf",
    "Receipt (5).pdf", "Receipt (6).pdf", "Receipt (7).pdf", "Receipt (8).pdf",
    "Receipt (9).pdf", "Receipt (10).pdf", "Receipt (11).pdf", "Receipt (12).pdf",
    "Receipt (13).pdf", "Receipt (14).pdf", "Receipt (15).pdf", "Receipt (16).pdf",
    "Receipt (17).pdf", "Receipt (18).pdf", "Receipt (19).pdf", "Receipt (20).pdf",
    "Receipt (21).pdf", "Receipt (22).pdf", "Receipt (23).pdf", "Receipt (24).pdf",
    "Receipt (25).pdf", "Receipt (26).pdf", "Receipt (27).pdf", "Receipt (28).pdf",
    "Receipt (29).pdf", "Receipt (30).pdf", "Receipt (31).pdf", "Receipt (32).pdf",
    "Receipt (33).pdf", "Receipt (34).pdf", "Receipt (35).pdf", "Receipt (36).pdf",
    "Receipt (37).pdf", "Receipt (38).pdf",
)

# ── Общий каркас Jasper/OpenPDF (все 23 файла) ───────────────────────────────
TBANK_SHELL = {
    "producer_substr": "OpenPDF",
    "creator_substr": "JasperReports",
    "object_count": 28,
    "xref_count": 1,
    "eof_count": 1,
    "zlib_header": b"\x78\x9c",
}

# ── Classic layout (все 23 — layout v2 не встречался в корпусе) ───────────────
TBANK_CLASSIC_LAYOUT = {
    "layout": "classic",
    "total_label_font": "F2",       # Medium — слово «Итого»
    "total_label_size": 16.0,
    "total_label_x": (15.0, 24.0),
    "top_amount_font": "F2",        # цифры суммы на F2
    "top_amount_size": 16.0,
    "ruble_font": "F3",             # ALSRubl — символ ₽/i
    "details_label_font": "F1",
    "details_amount_font": "F1",
}

# Content stream object 12 — ориентиры по корпусу
CONTENT_PROFILE_SBP = {
    "content_decoded_min": 4350,
    "content_decoded_max": 4650,
    "content_raw_min": 1020,
    "content_raw_max": 1100,
    "bt_count": 30,
    "tj_count": (33, 34),
    "tm_count": 31,
    "bfrange_count": 2,
    "bfchar_count": 0,
}

CONTENT_PROFILE_PHONE = {
    "content_decoded_min": 3350,
    "content_decoded_max": 3800,
    "content_raw_min": 860,
    "content_raw_max": 980,
    "bt_count": 30,
    "tj_count": (33, 34),
    "tm_count": 31,
    "bfrange_count": 2,
    "bfchar_count": 0,
}

CONTENT_PROFILE_CARD = {
    "content_decoded_min": 3600,
    "content_decoded_max": 3700,
    "content_raw_min": 870,
    "content_raw_max": 900,
    "bt_count": 26,
    "tj_count": (26, 27),
    "tm_count": 25,
    "bfrange_count": 2,
    "bfchar_count": 0,
}

# Исключение: Receipt (7) — phone, но content_dec≈4622 (как СБП)
CONTENT_PROFILE_PHONE_WIDE = {
    **CONTENT_PROFILE_SBP,
    "note": "phone transfer with full-size stream",
}

# ── F1 Regular — кластеры по числу CID в subset (23 оригинала) ───────────────
# Ключ = cid_count → (fontfile2, glyf, w_len, w_spaces) min/max
F1_CID_CLUSTERS: dict[int, dict[str, tuple[int, int]]] = {
    59: {"fontfile2": (15265, 15270), "glyf": (11100, 11105),
         "w_len": (348, 348), "w_spaces": (31, 31)},
    62: {"fontfile2": (15530, 15535), "glyf": (11364, 11368),
         "w_len": (364, 364), "w_spaces": (33, 33)},
    64: {"fontfile2": (16110, 16115), "glyf": (11944, 11948),
         "w_len": (372, 372), "w_spaces": (35, 35)},
    65: {"fontfile2": (16594, 16600), "glyf": (12428, 12432),
         "w_len": (364, 364), "w_spaces": (39, 39)},
    66: {"fontfile2": (16490, 16495), "glyf": (12326, 12330),
         "w_len": (380, 380), "w_spaces": (37, 37)},
    67: {"fontfile2": (16505, 16650), "glyf": (12340, 12485),
         "w_len": (387, 390), "w_spaces": (36, 37)},
    68: {"fontfile2": (16600, 17210), "glyf": (12430, 13045),
         "w_len": (391, 398), "w_spaces": (36, 38)},
    69: {"fontfile2": (16930, 16955), "glyf": (12768, 12790),
         "w_len": (403, 403), "w_spaces": (37, 37)},
    71: {"fontfile2": (17014, 17020), "glyf": (12850, 12855),
         "w_len": (421, 421), "w_spaces": (36, 36)},
    72: {"fontfile2": (16774, 16778), "glyf": (12610, 12614),
         "w_len": (417, 417), "w_spaces": (39, 39)},
    73: {"fontfile2": (17426, 17432), "glyf": (13262, 13266),
         "w_len": (434, 434), "w_spaces": (37, 37)},
    75: {"fontfile2": (17774, 17780), "glyf": (13608, 13612),
         "w_len": (450, 450), "w_spaces": (37, 37)},
    76: {"fontfile2": (17958, 17964), "glyf": (13792, 13796),
         "w_len": (443, 443), "w_spaces": (41, 41)},
}

F1_CID_ENVELOPE = (min(F1_CID_CLUSTERS) - 1, max(F1_CID_CLUSTERS) + 1)

# Типичные F1 CID по каналу (для статистики, не жёсткий фильтр)
F1_CID_TYPICAL_SBP = range(66, 77)
F1_CID_TYPICAL_PHONE = (62, 64, 65, 68)  # 68 только Receipt (7)
F1_CID_TYPICAL_CARD = (59,)

# ── F2 Medium — корпус 7–9 CID ───────────────────────────────────────────────
F2_CID_RANGE = (7, 9)

F2_CID_CLUSTERS: dict[int, dict[str, tuple[int, int]]] = {
    7: {"fontfile2": (4980, 5160), "glyf": (800, 970),
        "w_len": (56, 56), "w_spaces": (0, 0), "cmap_dec": (445, 452)},
    8: {"fontfile2": (5180, 5450), "glyf": (990, 1250),
        "w_len": (56, 64), "w_spaces": (0, 1), "cmap_dec": (458, 478)},
    9: {"fontfile2": (5490, 5580), "glyf": (1300, 1390),
        "w_len": (72, 72), "w_spaces": (0, 0), "cmap_dec": (482, 488)},
}

# ── F3 ALSRubl (рубль) — стабилен во всех 23 ─────────────────────────────────
F3_PROFILE = {
    "fontfile2": (1874, 1878),
    "glyf": (342, 346),
    "num_glyphs": 23,
}

# ── TTF (встроенные шрифты F1/F2 полные) ─────────────────────────────────────
TTF_PROFILE = {
    "f1_num_glyphs": 476,
    "f2_num_glyphs": 479,
    "units_per_em": 1000,
    "head_checksum_adj": 863796543,
    "tail_padding_bytes": 2,
    "f1_loca_len": 954,
    "f2_loca_len": 960,
}
