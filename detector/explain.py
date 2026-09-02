"""
Понятные объяснения для пользователя — без технических кодов PDF.
"""

from __future__ import annotations

import re

# Код флага → короткое объяснение простым языком
_REASON_BY_CODE: dict[str, str] = {
    "ANALYSIS_NOT_COMPLETED": (
        "Проверка не завершилась из-за технической ошибки. Пришлите PDF ещё раз."
    ),
    "F1_W_LENGTH_NOT_MATCHING_NEIGHBOR_CLUSTER": (
        "Таблица ширин основного шрифта записана иначе, чем в настоящих чеках Т-Банка"
    ),
    "F1_W_LENGTH_NOT_MATCHING_CID_CLUSTER": (
        "Внутренняя структура шрифта Regular не совпадает с банковским образцом"
    ),
    "F1_W_SPACES_CLUSTER_DRIFT": (
        "Шрифт текста в PDF собран не тем способом, которым пишет система банка"
    ),
    "REGULAR_WIDTH_TABLE_RAW_PROFILE_SHIFT": (
        "Профиль шрифта Regular отличается от оригинальных квитанций"
    ),
    "F1_CID_CLUSTER_NOT_OBSERVED_IN_ORIGINALS": (
        "Набор символов во встроенном шрифте не похож на типичные чеки Т-Банка"
    ),
    "F2_COMPACT_SUBSET_PROFILE": (
        "Шрифт суммы слишком «урезан» по сравнению с большинством настоящих чеков"
    ),
    "F2_W_OBJECT_TOO_COMPACT_FOR_COMMON_CLUSTER": (
        "Таблица ширин шрифта суммы компактнее, чем обычно у банка"
    ),
    "AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS": (
        "Сумма рядом с «Итого» не совпадает с суммой в блоке «Сумма»"
    ),
    "TOTAL_LABEL_FONT_LAYER_MISMATCH": (
        "Слово «Итого» выведено не тем шрифтом, как в настоящем чеке"
    ),
    "TOP_AMOUNT_FONT_LAYER_MISMATCH": (
        "Сумма вверху чека выведена не тем шрифтом, как у банка"
    ),
    "W_ARRAY_PRETTY_PRINTED": (
        "PDF пересобран сторонней программой, а не банковским генератором"
    ),
    "W_ARRAY_SERIALIZATION_ANOMALY": (
        "PDF пересобран сторонней программой"
    ),
    "id_hex_case": (
        "Служебный идентификатор PDF записан не так, как у настоящих чеков OpenPDF"
    ),
    "sbp_opid_structure": (
        "Идентификатор операции СБП не соответствует формату настоящего чека"
    ),
    "sbp_opid_reuse": (
        "Этот идентификатор операции уже встречался у другого перевода"
    ),
    "CMAP_W_MISMATCH": (
        "Внутренние таблицы символов в PDF не согласованы между собой"
    ),
    "USED_CID_CMAP_MISMATCH": (
        "В PDF используются символы, которых нет во внутренней карте шрифта"
    ),
    "GLYPH_COUNT_OUTLIER": (
        "Встроенный шрифт не похож на шрифт настоящих квитанций Т-Банка"
    ),
    "TTF_HEAD_ANOMALY": (
        "Встроенный шрифт сформирован не банковским генератором Jasper/OpenPDF"
    ),
    "stream_reserialized": (
        "Содержимое PDF перепаковано сторонним редактором"
    ),
    "keywords_creation": (
        "Дата в метаданных PDF не совпадает с датой операции в чеке"
    ),
    "keywords_tail_constant": (
        "Устаревшая проверка /Keywords — больше не используется"
    ),
    "KNOWN_FAKE_FONT_REBUILDER_SIGNATURE": (
        "F1/F2 пересобраны сторонним font builder во время создания PDF"
    ),
    "PDF_TTF_BBOX_CROSS_LAYER_MISMATCH": (
        "PDF FontBBox не совпадает с bbox встроенного TTF — FontDescriptor скопирован, "
        "а font program пересобран отдельно"
    ),
    "FONT_GLOBAL_TABLES_FOREIGN_SUBSETTER": (
        "Глобальные таблицы TinkoffSans (head/hhea/maxp) пересчитаны под чужой subset"
    ),
    "STATIC_EDITABLE_DIGIT_SUBSET_F2": (
        "В F2 заранее встроен полный набор цифр для подстановки произвольной суммы"
    ),
    "EXTRA_UNUSED_GLYPHS_F1_F2": (
        "В F1/F2 есть лишние неиспользуемые glyph сверх штатного .notdef"
    ),
    "phone_format": (
        "Номер телефона получателя записан не в том формате, как выводит банк"
    ),
    "creation_eq_operation": (
        "Время создания PDF совпадает с временем перевода — у настоящего чека файл делается позже"
    ),
    "foreign_width_array": (
        "Таблица ширин шрифта записана в формате сторонней программы"
    ),
    "bfchar_in_tounicode": (
        "Карта символов шрифта не похожа на банковскую"
    ),
    "broken_glyphmap": (
        "Текстовый слой чека повреждён или пересобран некорректно"
    ),
    "GLYPH_PIX_TOTAL_LABEL": (
        "Контур слова «Итого» не совпадает с настоящими чеками — другой шрифт или subset"
    ),
    "GLYPH_PIX_COMMISSION_ZERO": (
        "Контур нуля в комиссии не совпадает с банковским — шрифт собран не через OpenPDF банка"
    ),
    "GLYPH_TTF_F1": (
        "Контуры букв/цифр в основном шрифте не совпадают с настоящими чеками Т-Банка"
    ),
    "GLYPH_TTF_F2": (
        "Контуры цифр суммы не совпадают с банковским шрифтом Medium"
    ),
    "GLYPH_TTF_F3": (
        "Символ рубля отличается от настоящих чеков"
    ),
    "FF2_SUBSET_UNKNOWN": (
        "Все три встроенных шрифта (F1/F2/F3) не совпадают с настоящими чеками — "
        "чужой FontFile2, не банковский OpenPDF/Jasper"
    ),
    "SBER_SBP_SKELETON_UNKNOWN": (
        "В Сбер СБП внутренний рисунок текстового слоя (порядок PDF-команд) "
        "не совпадает с шаблонами настоящих чеков"
    ),
    "BANK_CONTENT_SKELETON_UNKNOWN": (
        "Внутренний рисунок текстового слоя PDF не совпадает с эталонными шаблонами банка"
    ),
    "TBANK_REASSEMBLY_FORGERY": (
        "PDF собран не так, как настоящие чеки Т-Банка: другой «рецепт» "
        "текстового слоя при незнакомом наборе встроенных шрифтов"
    ),
    "TBANK_FONT_RENDER_FORGERY": (
        "Шрифт F1/F2 пересобран или украден не так, как у банка, "
        "и вёрстка чека на картинке не совпадает с эталонными оригиналами"
    ),
    "SBER_SBP_OPERATOR_DRIFT": (
        "Для Сбер СБП количество/структура текстовых PDF-команд отличается от оригинальных чеков"
    ),
    "SBER_SBP_LAYOUT_DRIFT": (
        "В Сбер СБП геометрия ключевых полей на странице отличается от оригинального макета"
    ),
    "SBER_SBP_LAYOUT_MISSING_FIELDS": (
        "В Сбер СБП не найдены ожидаемые ключевые поля макета"
    ),
    "SBER_SBP_LAYOUT_PARSE_FAILED": (
        "Не удалось корректно разобрать внутреннюю геометрию Сбер СБП для deep-проверки"
    ),
    "SYMBOL_TTF_SIZE_DRIFT": (
        "Размер встроенного банковского шрифта отличается от эталонного диапазона"
    ),
    "SYMBOL_GLYPH_DRIFT": (
        "Часть контуров символов (glyph) не совпадает с библиотекой эталонных чеков"
    ),
    "SYMBOL_FONT_MISSING": (
        "В PDF отсутствует ожидаемый слой шрифта для выбранного банковского шаблона"
    ),
    "SENDER_NAME_TEXT_ANOMALY": (
        "В данных отправителя есть подозрительная опечатка или неестественное имя"
    ),
    "FIELD_FORMAT_INVALID": (
        "Идентификатор операции в чеке имеет неверную структуру"
    ),
    "POST_EOF": (
        "После конца файла PDF есть лишние данные — признак ручной правки"
    ),
    "K-FONT-002": (
        "Встроенный шрифт суммы (F2) совпадает с известным паком поддельных "
        "цифр — такой glyf/loca набор не встречается в настоящих чеках Т-Банка"
    ),
    "SBER_KNOWN_FAKE_FONTFILE2": (
        "Встроенный шрифт PDF совпадает с уже пойманным поддельным FontFile2 "
        "(тот же байтовый отпечаток, что у генераторных фейков)"
    ),
    "SBER_FILE_SIZE_STRONG_OUTLIER": (
        "Размер PDF сильно отличается от настоящих чеков этого типа Сбера "
        "(например СБП-оригиналы ~102–103 КБ, а файл заметно тяжелее/легче)"
    ),
    "SBER_FILE_SIZE_OUTLIER": (
        "Размер PDF выходит за обычный диапазон для этого типа чека Сбера"
    ),
    "TBANK_FILE_SIZE_STRONG_OUTLIER": (
        "Размер PDF сильно отличается от корпуса оригиналов Т-Банка (~58–61 КБ)"
    ),
    "TBANK_FILE_SIZE_OUTLIER": (
        "Размер PDF выходит за обычный диапазон оригиналов Т-Банка"
    ),
    "FIELD_POSITION_OUT_OF_PROFILE": (
        "Координаты текста (Tm) с 3+ знаками после запятой — Jasper/OpenPDF так "
        "не сериализует; след пересчёта/пересборки content stream"
    ),
    "TM_NOT_RECALCULATED": (
        "Tm-координаты пересчитаны с точностью, нехарактерной для JasperReports"
    ),
    "ALFA_FILE_SIZE_STRONG_OUTLIER": (
        "Размер PDF сильно отличается от оригиналов Альфа того же serializer "
        "(iOS/Quartz ~70–71 КБ, Oracle BI ~55–59 КБ)"
    ),
    "ALFA_FILE_SIZE_OUTLIER": (
        "Размер PDF выходит за обычный диапазон оригиналов Альфа этого типа"
    ),
    "ALFA_FIELD_VALUE_BINDING_CONFLICT": (
        "Значения в чеке Альфа сдвинуты относительно подписей полей: "
        "например, под суммой списания стоит дата, а под датой — номер операции"
    ),
    "VTB_FIELD_VALUE_BINDING_CONFLICT": (
        "Значения в чеке ВТБ сдвинуты относительно подписей полей: "
        "дата оказалась на сумме, ФИО — на номере операции СБП"
    ),
    "TEXT_TRAILING_NBSP_PADDING": (
        "В ФИО, сообщении или «Сформирована» дописаны лишние неразрывные пробелы "
        "(2 и больше) — след подгонки длины текстового слоя под чужой шаблон. "
        "У оригиналов таких пробелов 0 или ровно один"
    ),
    "ALFA_KNOWN_FAKE_SIGNATURE": (
        "Файл полностью совпал с подтверждённой подделкой чека Альфа-Банка"
    ),
    "ALFA_QUARTZ_UNCONFIRMED_COMPOSITE_PROFILE": (
        "Новый профиль Alfa iOS одновременно отличается от оригиналов по "
        "контейнеру, текстовому потоку, встроенному шрифту и профилю СБП"
    ),
    "SBER_FONT_REVERSE_GLYPH_CLOSURE": (
        "Во встроенном шрифте Сбера есть лишние глифы вне реально "
        "используемых символов — типичный след пересобранного шрифта"
    ),
    "SBER_KNOWN_FAKE_SIGNATURE": (
        "Документ совпал с известной сигнатурой подделки из malicious-атласа"
    ),
    "SBER_FONT_LAYER_CONTAMINATION": (
        "Шрифтовой слой PDF собран не банковским путём (чужой font builder / "
        "несогласованные таблицы)"
    ),
    "OZON_SBP_ID_CROSS_BANK_TAIL": (
        "В хвосте СБП-ID у Ozon-чека стоит блок G100/G101 как у Т-Банка — "
        "у настоящих Ozon route только 00 или B1"
    ),
    "OZON_KNOWN_FAKE_SBP_TAIL_FAMILY": (
        "Хвост СБП-ID совпал с подтверждённым семейством генератора Ozon "
        "(B1 / 0011 / 830901) — у живых чеков такого суффикса нет"
    ),
    "OZON_AMOUNT_FORMAT_INVALID": (
        "Сумма на чеке Ozon записана не в банковском формате "
        "(нужны пробелы между тысячами)"
    ),
    "TBANK_SUPPORT_CONTACT_CORRUPTED": (
        "Строка «Служба поддержки fb@tbank.ru» отсутствует или превращена "
        "в кракозябры — у настоящих чеков Т-Банка она всегда целая"
    ),
    "TBANK_SUPPORT_CONTACT_SPACING": (
        "Контакт поддержки записан не так, как в оригинальных чеках Т-Банка"
    ),
    "TBANK_STATIC_LABEL_CORRUPTED": (
        "Подпись поля (например «Телефон получателя») повреждена — "
        "буквы заменены на чужие символы"
    ),
    "SBP_REFERENCE_NON_NUMERIC": (
        "В трёхзначный внутренний reference-блок СБП-ID попала буква; "
        "у оригинального формата этот блок строго числовой"
    ),
    "SBP_PROFILE_EPOCH_EXPIRED": (
        "Дата операции не соответствует эпохе маршрута внутри СБП-ID: "
        "использован уже заменённый банковский профиль"
    ),
    "SBP_PROFILE_EPOCH_SLOT_CONFLICT": (
        "В СБП-ID стоит слот маршрута от другой календарной эпохи "
        "(июньский чек с августовским B1013 или наоборот)"
    ),
    "SBP_PROFILE_EPOCH_SUFFIX_CONFLICT": (
        "В новом банковском профиле СБП-ID оставлен suffix от устаревшей эпохи"
    ),
    "SBP_PROFILE_SUFFIX_OWNER_CONFLICT": (
        "Suffix СБП-ID пересажен к чужой связке class, slot и управляющих полей"
    ),
    "TBANK_FONT_GLYF_TRAILING_DATA": (
        "Встроенный TinkoffSans физически повреждён: после объявленной границы "
        "таблицы glyf остались лишние данные"
    ),
    "TBANK_SBP_TUPLE_GLYF_RESIDUE_SIGNATURE": (
        "СБП-ID и шрифтовая сборка файла совпали с известным техническим следом "
        "поддельного генератора"
    ),
    "TBANK_SBP_G1_SLOT018_BINDING_CONFLICT": (
        "Внутри СБП-ID нарушена фиксированная связка маршрута G1/00117 "
        "slot 018: control не соответствует route_marker"
    ),
    "TBANK_TRAILER_ID_CANONICAL_CONTENT_MISMATCH": (
        "PDF использует идентификатор подтверждённого оригинала, но внутренний "
        "поток содержимого заменён"
    ),
    "TBANK_COMPETITOR_NOVELTY_COMBO_001": (
        "Совпала комбо из 4 редких техследов (контент + F1-шрифт), которая не "
        "встречается в корпусе оригиналов Т-Банка"
    ),
    "TBANK_COMPETITOR_TUPLE_791103_COMBO_002": (
        "Совпала точечная комбо для SBP-серии 791103: tuple-ID + 2 структурных "
        "следа + длина контент-потока (4405/4408)"
    ),
    "TBANK_COMPETITOR_TUPLE_018_NATIVE_COMBO_004": (
        "Для SBP-маршрута slot 018 одновременно совпали четыре независимых "
        "следа пересборки контента и встроенных шрифтов"
    ),
    "TBANK_CONTENT_SKELETON_EXACT_UNKNOWN": (
        "Внутренняя раскладка текстового слоя PDF не совпадает "
        "с оригинальными чеками Т-Банка"
    ),
    "ALFA_CONTENT_BODY_EXACT_UNKNOWN": (
        "Содержимое PDF Альфа пересобрано — тело страницы не совпадает "
        "с корпусом оригиналов, даже если размер похож"
    ),
    "YANDEX_CREATION_DATE_FORMAT": (
        "Служебная дата создания PDF записана не в формате банковского OpenPDF"
    ),
    "YANDEX_YSTEXT_FULLFONT_METRICS": (
        "Встроенный шрифт YSText пересобран — не совпадает с банковской метрикой"
    ),
    "YANDEX_CREATION_TIME_MISMATCH": (
        "Время создания PDF не совпадает со временем операции на чеке Яндекс Банка"
    ),
    "YANDEX_KNOWN_FILE_SIGNATURE": (
        "Этот файл совпал с уже известной поддельной квитанцией Яндекс Банка"
    ),
    "MTS_PRODUCER_MISMATCH": (
        "PDF МТС Деньги собран не банковским dbo-print-forms / OpenPDF"
    ),
    "MTS_FONT_MISMATCH": (
        "Шрифты чека МТС Деньги не совпадают с банковским MTSSans"
    ),
    "MTS_PAGE_MISMATCH": (
        "Формат страницы не похож на чек МТС Деньги"
    ),
    "MTS_CREATION_DATE_FORMAT": (
        "Служебная дата создания PDF записана не в формате банковского OpenPDF"
    ),
    "MTS_FIELDSET_MISMATCH": (
        "Набор полей на чеке не совпадает с квитанцией МТС Деньги"
    ),
    "YOOMONEY_PRODUCER_MISMATCH": (
        "PDF ЮMoney собран не банковским Jasper 6.12"
    ),
    "YOOMONEY_FONT_MISMATCH": (
        "Шрифты чека ЮMoney не совпадают с банковским FactorIO"
    ),
    "YOOMONEY_PAGE_MISMATCH": (
        "Формат страницы не похож на чек ЮMoney"
    ),
    "YOOMONEY_CREATION_DATE_FORMAT": (
        "Служебная дата создания PDF ЮMoney записана не в банковском формате"
    ),
    "YOOMONEY_FIELDSET_MISMATCH": (
        "Набор полей на чеке не совпадает с квитанцией ЮMoney"
    ),
    "RSBANK_PRODUCER_MISMATCH": (
        "PDF Русского Стандарта собран не банковским OpenPDF / JasperReports"
    ),
    "RSBANK_FONT_MISMATCH": (
        "Шрифты чека Русского Стандарта не совпадают с банковскими Calibri/Times"
    ),
    "RSBANK_PAGE_MISMATCH": (
        "Формат страницы не похож на чек Русского Стандарта"
    ),
    "RSBANK_CREATION_DATE_FORMAT": (
        "Служебная дата создания PDF Русского Стандарта записана не в банковском формате"
    ),
    "RSBANK_ISSUER_BIK_MISMATCH": (
        "В чеке нет банковских реквизитов эмитента Русский Стандарт"
    ),
    "RSBANK_FIELDSET_MISMATCH": (
        "Набор полей на чеке не совпадает с квитанцией Русского Стандарта"
    ),
    "TOCHKA_PRODUCER_MISMATCH": (
        "PDF Точки собран не банковским Jasper OpenPDF"
    ),
    "TOCHKA_FONT_MISMATCH": (
        "Шрифты чека Точки не совпадают с банковским TTNormsTochka"
    ),
    "TOCHKA_PAGE_MISMATCH": (
        "Формат страницы не похож на чек Точки"
    ),
    "TOCHKA_CREATION_DATE_FORMAT": (
        "Служебная дата создания PDF Точки записана не в банковском формате"
    ),
    "TOCHKA_ISSUER_BIK_MISMATCH": (
        "В чеке нет банковских реквизитов эмитента Точка"
    ),
    "TOCHKA_FIELDSET_MISMATCH": (
        "Набор полей на чеке не совпадает с квитанцией Точки"
    ),
    "VTB_ACCOUNT_SBP_PRODUCER_MISMATCH": (
        "PDF перевода ВТБ на счёт собран не банковским OpenPDF"
    ),
    "VTB_ACCOUNT_SBP_FONT_MISMATCH": (
        "Шрифты чека ВТБ на счёт не совпадают с банковским Arial"
    ),
    "VTB_ACCOUNT_SBP_SFNT_MISMATCH": (
        "Встроенный шрифт чека ВТБ пересобран — сняты служебные таблицы Arial"
    ),
    "VTB_ACCOUNT_SBP_PAGE_MISMATCH": (
        "Формат страницы не похож на чек ВТБ «перевод на счёт через СБП»"
    ),
    "VTB_ACCOUNT_SBP_AMOUNT_MISMATCH": (
        "Сумма на чеке ВТБ не сходится с зачислением и комиссией"
    ),
}

# Фрагменты в тексте флага (без кода) → объяснение
_REASON_BY_PHRASE: list[tuple[str, str]] = [
    ("идентификатор PDF (/ID) записан ЗАГЛАВНЫМ", "Служебный ID файла записан заглавными буквами — у Т-Банка всегда строчные"),
    ("идентификатор операции СБП", "Номер операции СБП не похож на настоящий"),
    ("Итого", "Суммы или поля «Итого» в чеке не согласованы"),
    ("Потоки пересобраны", "PDF редактировался сторонней программой"),
    ("Подозрительный Producer", "Файл создан не банковской системой"),
    ("шаблонный номер квитанции", "Указан типовой номер из шаблона подделки"),
    ("Дата шаблона", "В PDF осталась дата из чужого шаблона"),
    ("координаты с избыточной точностью", "Расположение текста пересчитано вручную"),
    ("паддинг в content stream", "Текстовый слой файла изменён после генерации"),
    ("Producer «", "PDF создан не той программой, что использует банк"),
    ("content stream", "Внутренняя структура PDF не совпадает с эталонными чеками банка"),
    ("Текстовый content stream не найден", "PDF не содержит типичного текстового слоя банка — возможна подделка"),
]

_CODE_RE = re.compile(r"^\[([A-Z0-9_]+)\]")


def _flag_code(flag: str) -> str | None:
    m = _CODE_RE.match(flag.strip())
    return m.group(1) if m else None


def _reason_for_flag(flag: str) -> str | None:
    code = _flag_code(flag)
    if code and code in _REASON_BY_CODE:
        return _REASON_BY_CODE[code]
    if code:
        if code.startswith("F1_W") or code.startswith("F1_FONT"):
            return _REASON_BY_CODE.get("REGULAR_WIDTH_TABLE_RAW_PROFILE_SHIFT")
        if code.startswith("F2_"):
            return "Шрифт суммы (Medium) не совпадает с профилем настоящих чеков"
        if "RIGHT_EDGE" in code:
            return "Выравнивание полей в чеке отличается от банковского шаблона"
        if "CMAP" in code or "CID" in code:
            return "Внутренняя карта символов PDF не соответствует банковскому образцу"
    fl = flag.lower()
    for phrase, msg in _REASON_BY_PHRASE:
        if phrase.lower() in fl:
            return msg
    # голый русский флаг без кода
    if not code and len(flag) > 20 and not flag.startswith("["):
        return flag
    return None


def build_user_explanation(result: dict, *, max_reasons: int = 6) -> dict:
    """
    Вернуть понятное резюме для Telegram:
        summary, reasons[], recommendation
    """
    score = int(result.get("score", 0))
    flags = list(result.get("flags") or [])
    details = result.get("details") or {}

    if result.get("verdict") == "ФЕЙК" or score >= 60:
        summary = "Подделка"
        recommendation = (
            "Не принимайте этот чек как подтверждение оплаты. "
            "Проверьте поступление в приложении банка."
        )
    else:
        summary = "Подделка не обнаружена"
        recommendation = ""

    analysis_failed = any("ANALYSIS_NOT_COMPLETED" in str(flag) for flag in flags)
    if analysis_failed:
        summary = "Проверка не завершена"
        recommendation = "Это не вердикт о подделке. Пришлите тот же PDF ещё раз."

    seen: set[str] = set()
    reasons: list[str] = []

    for flag in flags:
        reason = _reason_for_flag(flag)
        if reason and reason not in seen:
            seen.add(reason)
            reasons.append(reason)
        if len(reasons) >= max_reasons:
            break

    if not reasons and score >= 60 and not analysis_failed:
        reasons.append("PDF не соответствует профилю оригинальных квитанций банка")

    return {
        "summary": summary,
        "reasons": reasons,
        "recommendation": recommendation,
    }
