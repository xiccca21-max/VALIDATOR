"""v6.0 подробный отчёт для @kronlead (spec §16)."""

from __future__ import annotations

from .types import PipelineResult, V6Flag

_IMPACT_BY_TIER = {
    "KNOWN": "exact known-fake signature → ФЕЙК",
    "A": "hard internal inconsistency → ФЕЙК",
    "B": "supporting group (нужно ≥2 независимых для ФЕЙК)",
}

_WHY_NOT_VARIABILITY: dict[str, str] = {
    "K-FONT-001": (
        "новый subset/hash допустим; здесь же font program пересобран "
        "и descriptor не согласован с TTF"
    ),
    "K-FONT-002": (
        "exact glyf/loca digit pack в known-fake atlas после проверки "
        "0 hits на корпусе оригиналов чеки/**; банковский TinkoffSans-Medium "
        "subset туда не кладём (FP 2026-07-31 снят)"
    ),
    "TBANK_REASSEMBLED_BANK_ASSETS": (
        "это не новый hash шрифта: все F1/F2 glyph и статические F3/images "
        "доверенные, но их полная content/font/CMap/W-сборка отсутствует в корпусе "
        "и одновременно подтверждена versioned provenance генератора"
    ),
    "TBANK_REASSEMBLED_BANK_ASSETS_V2": (
        "пять структурных evidence-групп generator/reassembly family v2: "
        "точный static asset bundle + canonical glyph mosaic + неизвестная "
        "complete F1/F2 assembly + rebuilt CMap/W/AST + fingerprint "
        "tbank_generator_content_ast_v2"
    ),
    "TBANK_REASSEMBLY_FAMILY_V3": (
        "подтверждённая F1/F2 reconstructed-subset serialization family v3: "
        "плотный F2 ToUnicode bfrange + компактный/расширенный glyf lattice "
        "и cross-layer FontFile2/ToUnicode stream lengths; не novelty SHA. "
        "Обход с целым визуалом: нельзя подогнать только F2.glyf в bank-band — "
        "нужен simultaneous font_signature∧stream_signature как у нативного "
        "Jasper; частичный match (одна длина) HARD не снимает"
    ),
    "TBANK_SUBSET_CMAP_NOT_MINIMAL": (
        "Jasper/OpenPDF subset ToUnicode описывает только реально выведенные CID; "
        "лишние mapped CID — след reconstructed subset"
    ),
    "TBANK_W_ARRAY_NOT_MINIMAL": (
        "/W должен совпадать с used CIDs; запасные/editable slots в оригинале отсутствуют"
    ),
    "TBANK_W_TTF_ADVANCE_MISMATCH": (
        "PDF /W width обязан равняться round(ttf_aw * 1000 / unitsPerEm)"
    ),
    "TBANK_CID_SERIALIZATION_BIJECTION_VIOLATION": (
        "used CIDs ≡ ToUnicode ≡ /W, и каждый used CID имеет валидный GID/loca/hmtx/glyf. "
        "Разрыв биекции — след ручной/SEQ-пересборки subset, не смена ФИО. "
        "Обход с целым визуалом: держать used≡cmap≡/W без orphan CID и без "
        "дыр в loca/glyf на painted CID; нельзя «донастроить» только ToUnicode"
    ),
    "TBANK_FONT_SUBSET_EXACT_CLOSURE": (
        "в FontFile2 nonempty-глифы должны = closure(нарисованных CID) ∪ {.notdef}. "
        "Лишний nonempty, ещё попавший в ToUnicode|/W, или дырка в нужном глифе — "
        "пересборка subset, не «лишняя буква банка». "
        "Обход с целым визуалом: оставить в nonempty только painted(+closure+.notdef); "
        "unmapped spare без cmap/W этот HARD не бьёт; нельзя выкинуть рисуемый глиф"
    ),
    "TBANK_FONT_SUBSET_ORPHAN_RESIDUE": (
        "в FontFile2 лежат nonempty-глифы вне closure(used∪ToUnicode) — не в cmap и не "
        "как компоненты. Банк почти не оставляет spare: редкие F1∈{35,239} и F2∈{306} "
        "(сбп2/8). Любой другой unmapped nonempty, ≥2 orphan в F2 или kit-пара 113+227 — "
        "след пересборки glyf. Не смена ID/счёта; обход maxp (донорский envelope) это не спасает. "
        "Обход с целым визуалом: вычистить unmapped nonempty из F1/F2 (loca/glyf), "
        "оставив только painted+composite-closure+.notdef (+ редкий genuine spare)"
    ),
    "TBANK_F1_MAXP_RECOMPUTED_TO_SUBSET": (
        "Jasper/OpenPDF оставляет в F1 maxp «донорский» envelope полного TinkoffSans "
        "(обычно maxPoints=100, maxContours=7, maxComponentElements=3), даже после subset — "
        "actual glyf extrema строго ниже. SEQ-пересборщик пересчитывает maxp ровно под "
        "вложенный glyf (часто 85/4/1). Равенство maxp≡glyf extrema — след ребилда FontFile2, "
        "не вариативность текста. "
        "Обход с целым визуалом: не трогать maxp (оставить банковский envelope) либо "
        "подставить maxp с полным шрифта, не совпадающий с extrema subset'а"
    ),
    "TBANK_F1_MAXP_COMPOSITE_ENVELOPE_MISMATCH": (
        "у всех Jasper SBP-оригиналов F1 maxp.maxCompositePoints=102 и "
        "maxCompositeContours=4 (полный TinkoffSans). SEQ часто оставляет maxPoints=100, "
        "но ужимает composite-поля (51/2, 51/3) — частичный rewrite maxp после пересборки glyf. "
        "Не смена ФИО/суммы. "
        "Обход с целым визуалом: копировать maxp целиком с банковского FontFile2 "
        "(102/4), не пересчитывать composite-статы под subset"
    ),
    "TBANK_F1_HHEA_ENVELOPE_MISMATCH": (
        "у всех Jasper SBP-оригиналов F1 hhea — один и тот же blob полного TinkoffSans "
        "(sha16=08c0a1c91858beca, n=56). SEQ после пересборки glyf переписывает hhea "
        "(minLSB/minRSB/xMaxExtent и т.п.), оставляя общий hmtx. Не вариативность текста. "
        "Обход с целым визуалом: копировать hhea целиком с банковского FontFile2, "
        "не пересчитывать метрики под subset"
    ),
    "TBANK_F2_HEAD_ENVELOPE_MISMATCH": (
        "у всех Jasper SBP-оригиналов F2 head — один и тот же blob TinkoffSans-Medium "
        "(sha16=d25ccb9e7b400baf, n=56), включая исходный checkSumAdjustment. SEQ после "
        "пересборки F2.glyf пересчитывает checksum (байты 8–11), оставляя created/modified/"
        "bbox. Не смена суммы/цифр. "
        "Обход с целым визуалом: копировать head целиком с банковского Medium FontFile2, "
        "не пересчитывать checkSumAdjustment"
    ),
    "TBANK_F2_MAXP_ENVELOPE_MISMATCH": (
        "у всех Jasper SBP-оригиналов F2 maxp — один blob Medium (sha16=2568c57650fd61c4, "
        "n=56). SEQ после пересборки digit-pad переписывает extrema/composite в maxp. "
        "Обход с целым визуалом: копировать maxp целиком с банковского Medium FontFile2"
    ),
    "TBANK_F1_HMTX_ENVELOPE_MISMATCH": (
        "у всех Jasper SBP-оригиналов F1 hmtx — один blob полного TinkoffSans "
        "(sha16=f3a867ade9a406be, n=56). SEQ иногда переписывает advances при пересборке. "
        "Обход с целым визуалом: копировать hmtx целиком с банковского FontFile2"
    ),
    "TBANK_F2_GLYF_LOCA_PADDING": (
        "у всех Jasper SBP-оригиналов F2 glyf заканчивается ровно на loca-end (pad=0). "
        "Хвост байт за последним glyph — residue digit-pad reassembly. "
        "Обход с целым визуалом: обрезать glyf по loca, не оставлять trailing bytes"
    ),
    "TBANK_F2_GLYF_DIGIT_CARD_FAT": (
        "размер F2.glyf должен соответствовать числу уникальных digit-outlines в ToUnicode: "
        "на genuines card2≤992, card3≤1320, card4≤1554, card5≤1654. SEQ после копирования "
        "F2.head всё ещё тащит synthetic-fat Medium (card3@1560+). Не смена суммы сама по себе. "
        "Обход с целым визуалом: subset Medium glyf под реально используемые цифры"
    ),
    "TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN": (
        "DIAGNOSTIC/IGNORE: точный whitelist F2.glyf×height — novelty atlas "
        "(finite n≠all future genuines). Не использовать как HARD."
    ),
    "TBANK_F2_GLYF_HEIGHT_MIDGAP": (
        "на height=451 F2.glyf в интервале (1106, 1226) и этого размера нет ни "
        "на одном genuine height. 1144 — нативный Medium (431/519/539), не midgap. "
        "SEQ phone сажает 1130. Не смена суммы. "
        "Обход с целым визуалом: нативный Medium subset этого height"
    ),
    "TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH": (
        "DIAGNOSTIC/IGNORE: известный F1 hmtx-kit может на genuines париться с "
        "новым F2.glyf (Receipt 15: kit 23b7d7… в атласе 856, факт 1044). "
        "Не использовать как HARD."
    ),
    "TBANK_BASEFONT_SUBSET_TAG_PAYLOAD_MISMATCH": (
        "OpenPDF пишет уникальный 6-буквенный subset-prefix в /BaseFont на каждый "
        "встроенный FontFile2. В genuines tag↔FF2sha16 биективен. SEQ клонирует "
        "shell донора, оставляя BaseFont-имена (DIHGIF+/KGBYTR+…), но подменяет "
        "Regular/Medium payloads под новый текст. Не novelty atlas по размеру — "
        "identity co-generation. Обход: нативный OpenPDF subset с новыми prefix"
    ),
    "TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH": (
        "DIAGNOSTIC/IGNORE: finite glyf_len→shape atlas. Genuine SBP can share "
        "F1.glyf length with a different cmap (Receipt 15: 12560 cmap 67 vs "
        "recorded 68). Same class as TWIN_SHAPE. Не использовать как HARD."
    ),
    "TBANK_F1_GLYF_SIZE_MULTISET_MISMATCH": (
        "DIAGNOSTIC/IGNORE: finite glyf_len→size-multiset atlas. Genuine SBP "
        "can share F1.glyf length with a different nonempty-outline set "
        "(новые чеки: 12784 / sha16 not in n=56 atlas). Same class as "
        "SHAPE_ENVELOPE. Не использовать как HARD."
    ),
    "TBANK_SFNT_TABLE_ORDER_MISMATCH": (
        "Jasper/OpenPDF пишет SFNT directory в фиксированном порядке "
        "cvt/fpgm/glyf/head/hhea/hmtx/loca/maxp/prep. Другой порядок — чужой subsetter. "
        "Обход: копировать directory order с банковского FontFile2"
    ),
    "TBANK_GLYF_ZERO_CONTOUR_STUB": (
        "у Jasper loca-слот с span>0 всегда имеет contours≠0; zero-contour stub "
        "(contours=0 при ненулевом span) — мусор после glyf/loca reassembly. "
        "Обход: не оставлять ghost glyph payloads"
    ),
    "TBANK_LOCA_ODD_OFFSET": (
        "long-format loca требует чётных byte-offset'ов; нечётный offset — "
        "сломанный loca writer. Обход: word-align glyph data"
    ),
    "TBANK_HMTX_METRIC_CARDINALITY": (
        "len(hmtx) = numberOfHMetrics×4 + (numGlyphs−numberOfHMetrics)×2. "
        "Нарушение — сломанная связка hhea/maxp/hmtx после transplant"
    ),
    "TBANK_COMPOSITE_EMPTY_COMPONENT": (
        "composite glyf ссылается на пустой component GID (loca a==b). "
        "Jasper так не эмитит — след сломанного glyf transplant"
    ),
    "TBANK_TOUNICODE_BFCHAR_PRESENT": (
        "Jasper Identity ToUnicode для F1/F2 — только beginbfrange; beginbfchar "
        "означает чужой CMap writer. Обход: эмитить только bfrange"
    ),
    "TBANK_FORBIDDEN_FONT_DESCRIPTOR_KEY": (
        "Jasper IB Receipt не пишет CIDSet/FontMatrix/MissingWidth/XHeight/"
        "AvgWidth/Leading/FontWeight в FontDescriptor. Наличие ключа — чужой PDF font stack"
    ),
    "TBANK_PROCSET_PRESENT": (
        "Jasper/OpenPDF IB Receipt не пишет /ProcSet. Наличие — legacy serializer"
    ),
    "TBANK_FLATE_PREDICTOR_PRESENT": (
        "Jasper IB Receipt использует Flate без /Predictor. Predictor — чужой encoder"
    ),
    "TBANK_STREAM_CRLF_EOL": (
        "Jasper/OpenPDF пишет stream\\n; stream\\r\\n — чужой byte-level serializer"
    ),
    "TBANK_CONTENT_TJ_PRESENT": (
        "Jasper IB Receipt эмитит только Tj; TJ (array showText) — чужой layout engine"
    ),
    "TBANK_MARKED_CONTENT_PRESENT": (
        "Jasper IB Receipt не использует BMC/BDC/EMC. Marked content — чужой emitter"
    ),
    "TBANK_BT_NESTING_VIOLATION": (
        "Jasper эмитит плоские BT…ET без вложенности. depth>1 или дисбаланс — сломанный content writer"
    ),
    "TBANK_TTF_UNEXPECTED_SFNT_TABLE": (
        "нативный F1 Jasper/OpenPDF subset имеет ровно 9 SFNT-таблиц; "
        "любой extra tag — след reconstructed FontFile2"
    ),
    "TBANK_TTF_REQUIRED_SFNT_TABLE_MISSING": (
        "в F1 FontFile2 отсутствуют обязательные таблицы "
        "cvt/fpgm/glyf/head/hhea/hmtx/loca/maxp/prep"
    ),
    "TBANK_TTF_INERT_PADDING_TABLE": (
        "таблица ZZZZ — инертный padding-маркер reconstructed subset; "
        "на 148 оригиналах отсутствует"
    ),
    "TBANK_F2_NOTDEF_GLYPH_EMPTY": (
        "нативный F2 TinkoffSans-Medium всегда содержит nonempty .notdef (GID 0); "
        "loca[0]==loca[1] — след stripped FontFile2"
    ),
    "TBANK_F2_NOTDEF_NATIVE_PROFILE_MISMATCH": (
        "для текущего fingerprint TinkoffSans-Medium длина .notdef = 58; "
        "любое другое значение на том же head/maxp/hhea — не банковский subset"
    ),
    "TBANK_FONT_NOTDEF_ASYMMETRY": (
        ".notdef удалён только из F2 при nonempty F1/F3 — характерный след пересборщика"
    ),
    "TBANK_AMOUNT_TEXT_SERIALIZATION_MISMATCH": (
        "верхний блок «Итого» без канонических разделителей тысяч в текстовом слое"
    ),
    "TBANK_F1_ORPHAN_SIMPLE_GLYPH": (
        "в F1 FontFile2 физически встроен glyph (simple/composite) вне "
        "ToUnicode,/W, content-stream и composite closure — остаток "
        "reconstructed subset"
    ),
    "TBANK_KNOWN_FAKE_SBP_SERIALIZER_V1": (
        "подтверждённое SBP serializer-семейство: DOCS-2035 + visible_second=0 + "
        "F2 unique nonempty glyph lengths ≥11"
    ),
    "TBANK_SBP_F1_GLYF_CMAP_UNKNOWN": (
        "для SBP OpenPDF h=519 длина glyf при данном cmap — конечный набор "
        "из корпуса (n=110); значение в min–max envelope, но вне exact set — "
        "SEQ-пересборка в зазоре, не новый банковский subset"
    ),
    "TBANK_F1_GLYF_CMAP_EXACT_UNKNOWN": (
        "для OpenPDF длина F1 glyf при данном cmap/height — конечный набор "
        "из корпуса; значение в min–max envelope, но вне exact set — "
        "SEQ-пересборка в зазоре, не новый банковский subset"
    ),
    "TBANK_F1_GLYF_TRAILING_JUNK": (
        "таблица F1 glyf длиннее loca[-1]: после последнего глифа остался "
        "хвост (pad>0). Корпус OpenPDF/Jasper всегда пишет glyf ровно по "
        "loca (pad=0) — хвост = residual SEQ-пересборки subset"
    ),
    "TBANK_F1_TWIN_SHAPE_MISMATCH": (
        "длина F1 glyf совпала с известным банковским twin (height+cmap), но "
        "тройка composite/nonempty/simple другая — скопирован размер таблицы, "
        "не состав глифов (пересборка). Не «вариативность суммы/ФИО»: другой "
        "текст обычно даёт другую длину glyf. "
        "Обход с целым визуалом: не копировать donor-длину вслепую; либо попасть "
        "в другой exact-twin с shape=эталону, либо собрать subset так, чтобы "
        "shape совпал с twin при той же длине — иначе снова HARD"
    ),
    "TBANK_CARD_OTHER_INTERNAL_WHITESPACE_PADDING": (
        "в page content stream вне literal/hex/comments есть ≥3 лишних "
        "байта whitespace — след постобработочной сериализации"
    ),
    "TBANK_KNOWN_FAKE_CARD_TBANK_SERIALIZER_V1": (
        "подтверждённое CARD_TBANK serializer-семейство: DOCS-2035 + "
        "visible_second=0 + raw∈[827,830] + whitespace/F2/CR branch"
    ),
    "TBANK_KNOWN_FAKE_NOCOMM_SERIALIZER_V1": (
        "подтверждённое NOCOMM serializer-семейство: DOCS-2035 + "
        "visible_second=0 + raw∈[765,767] + whitespace/decoded branch"
    ),
    "USED_CID_MISSING_FROM_CMAP": (
        "каждый used CID из Tj/TJ обязан иметь ToUnicode; пропуск — broken Identity-H subset"
    ),
    "PDF_TTF_BBOX_CROSS_LAYER_MISMATCH": (
        "на 128 оригиналах PDF FontBBox всегда совпадает с TTF head bbox"
    ),
    "TBANK_CONTENT_STREAM_EDIT": (
        "Jasper/OpenPDF не оставляет padding-комментарии и хвост после ET"
    ),
    "TBANK_CONTENT_TJ_TRAILING_WHITESPACE": (
        "Jasper/OpenPDF пишет «Tj\\n» без пробелов после оператора; "
        "trailing spaces/tabs после Tj — след правки /Contents"
    ),
    "TBANK_CONTENT_FLOAT_TRAILING_ZERO": (
        "OpenPDF сериализует float без лишних нулей в дробной части "
        "(187.1, не 187.10); trailing zero — чужой пересчёт Tm/координат"
    ),
    "TBANK_CONTENT_TD_SENTINEL": (
        "Jasper/OpenPDF IB Receipt никогда не пишет Td -500 -500; "
        "это sentinel чужого layout engine после вырезания logo-Td. "
        "Обход: не оставлять placeholder-координаты в /Contents"
    ),
    "TBANK_CONTENT_IMG_TD_SCALE_MISMATCH": (
        "у каждой картинки q a 0 0 d tx ty cm /imgN Do Jasper всегда "
        "эмитит пару «a 0 Td» / «-a 0 Td» (img1:a=28, img3:a=175). "
        "Обход: копировать Td-пары вместе с cm Do, не только XObject"
    ),
    "TBANK_CONTENT_TR_MODE_ANOMALY": (
        "для обводки рубля Jasper использует ровно Tr=[2, 0]; режимы "
        "вне {0,2} (в т.ч. Tr=3 invisible) или лишние переключения — "
        "след SEQ text-object. Обход: один stroke-блок как у банка"
    ),
    "TBANK_KEYWORDS_GENERATION_MISMATCH": (
        "у Jasper IB/Receipt /Keywords third token привязан и к дате PDF, "
        "и к напечатанной дате операции: до 10.07.2026 «991», с 10.07.2026 "
        "«DOCS-2035»; смешанная пара (в т.ч. лицо до 10.07 + DOCS-2035) — подделка"
    ),
    "TBANK_INFO_KEYWORDS_LEX_MISMATCH": (
        "Jasper/OpenPDF сериализует /Keywords( без пробела перед «(»; "
        "разделитель — признак постредактированного /Info"
    ),
    "TBANK_DEFLATE_PROFILE_MISMATCH": (
        "DEFLATE-профиль потока не совпадает с Java Deflater Jasper/OpenPDF "
        "при совпадении остальных потоков документа"
    ),
    "TBANK_RECEIPT_NUMBER_FORMAT": (
        "банковский номер квитанции всегда 1-XXX-XXX-XXX-XXX "
        "(четыре трёхзначных блока)"
    ),
    "TBANK_TRAILER_ID_REUSED": (
        "одна пара trailer /ID не может порождать документы с разным содержимым"
    ),
    "TBANK_TRAILER_ID_CANONICAL_CONTENT_MISMATCH": (
        "пара trailer /ID уже принадлежит подтверждённому оригиналу, но decoded "
        "/Contents отличается от его канонического SHA-256 — скопирован контейнер "
        "PDF с заменённым содержимым"
    ),
    "TBANK_FILE_SIZE_STRONG_OUTLIER": (
        "вес PDF сильно вне корпуса оригиналов (~58–61KB). Небольшой разброс "
        "ФИО/суммы не даёт +2–3KB сверх max; сильный сдвиг — другой serializer"
    ),
    "TBANK_FILE_SIZE_OUTLIER": (
        "вес PDF вне мягкого диапазона оригиналов — supporting, не solo-HARD"
    ),
    "TBANK_STREAM_INTEGRITY_VIOLATION": (
        "/Length, zlib framing и границы stream должны быть детерминированы "
        "независимо от терпимости парсера"
    ),
    "SBP_CIPHER_TIMESTAMP": (
        "временное ядро СБП-ID (UTC→MSK) должно совпадать с напечатанным "
        "временем операции с точностью 0–1 с"
    ),
    "SBP_CIPHER_STRUCTURE": (
        "структура 32-символьного ID фиксирована протоколом НСПК"
    ),
    "SBP_ROUTE_FIELD_CONTAMINATION": (
        "поля route/separator/class в СБП-ID должны соответствовать "
        "версионированному алфавиту текущего Jasper-поколения (route ∈ {0,B,G})"
    ),
    "SBP_CONTROL_TRIPLE_MISMATCH": (
        "control ID[15] жёстко связан с (route_marker, slot, suffix) на подтверждённом "
        "корпусе; подмена хвоста при неверном control — типичный clone-forgery"
    ),
    "SBP_LINKED_TUPLE_CONFLICT": (
        "для подтверждённой связки class+bank5+control+slot+suffix допустим только "
        "зафиксированный route_marker; его подмена нарушает внутреннюю связность СБП-ID"
    ),
    "SBP_LINKED_TUPLE_CROSS_CLASS": (
        "блок route_marker+control+slot+suffix взят из другого class/bank5 профиля "
        "(например B1-связка на G1-ID) — типичный splice grammar при подделке"
    ),
    "SBP_REFERENCE_NON_NUMERIC": (
        "самостоятельный HARD: трёхзначный reference-блок ID[11:14] содержит "
        "букву. У 60/60 проверенных оригинальных T-Банк SBP-ID он строго decimal; "
        "tuple, шрифт и atlas для решения не используются."
    ),
    "SBP_PROFILE_EPOCH_EXPIRED": (
        "самостоятельный bank-specific HARD: маршрут G1/00117/791103 уже не "
        "соответствует дате операции после 01.08.2026. Августовские оригиналы "
        "перешли на bank5=00118; это проверка внутренней эпохи СБП-ID."
    ),
    "SBP_PROFILE_EPOCH_SLOT_CONFLICT": (
        "самостоятельный bank-specific HARD: слот B1/013 жив у Т-Банка в "
        "марте–мае; июнь–август 2026 его не используют (июнь A+G100x/B+G101x, "
        "август B+00118). SEQ ставил августовский B1013 на июньские даты."
    ),
    "SBP_PROFILE_EPOCH_SUFFIX_CONFLICT": (
        "самостоятельный bank-specific HARD: генератор заменил bank5 на 00118, "
        "но оставил graft-suffix 891103 от старой ветки. Такая августовская "
        "связка не соответствует внутренней эпохе СБП-ID."
    ),
    "SBP_PROFILE_SUFFIX_OWNER_CONFLICT": (
        "самостоятельный bank-specific HARD: настоящий suffix нового профиля "
        "пересажен к чужому class/slot/marker/control. Проверяется внутренняя "
        "принадлежность suffix, а не комбинация внешних сигналов."
    ),
    "TBANK_SBP_G1_SLOT018_BINDING_CONFLICT": (
        "маршрут G1/00117 slot=018 suffix=791103 имеет связанные пары "
        "control/route_marker только H/0 и S/1. Произвольные A/G/B с markers 2–9 "
        "нарушают внутреннюю маршрутизацию СБП-ID; это не размерный/font atlas."
    ),
    "TBANK_FONT_GLYF_TRAILING_DATA": (
        "самостоятельный HARD: FontFile2 TinkoffSans физически повреждён — за "
        "объявленной границей glyf остаются лишние байты. SBP tuple, длина и "
        "atlas не используются; известная benign-ветка 405 исключена."
    ),
    "TBANK_SBP_TUPLE_GLYF_RESIDUE_SIGNATURE": (
        "целевые связки SBP-ID сами по себе могут быть живыми у банка; "
        "HARD только вместе с физическим FontFile2 glyf-residue (too much glyph data), "
        "не 405-byte benign. Пустой warn не считается — FP на сбп1.pdf."
    ),
    "TBANK_COMPETITOR_NOVELTY_COMBO_001": (
        "одновременное попадание в 4 независимых atlas-признака "
        "(content_len + F1 twin shape + F1 shape envelope + F1 size multiset) "
        "для одной квитанции. По текущему корпусу оригиналов Т-Банка эта комбо "
        "не встречается и является устойчивым маркером конкурентного ребилда."
    ),
    "TBANK_COMPETITOR_TUPLE_791103_COMBO_002": (
        "для серии SBP tuple 0|5|0|G1|014|00117|791103 одновременно выполняются "
        "два независимых структурных следа (content skeleton unknown + F2 glyf×height unknown) "
        "и характерная длина content 4405/4408. В проверенном корпусе оригиналов "
        "этой комбинации не найдено."
    ),
    "TBANK_COMPETITOR_TUPLE_017_791103_COMBO_003": (
        "для серии SBP tuple 1|D|0|G1|017|00117|791103 (и sibling 3|B|0|G1|017|00117|791103) "
        "одновременно выполняются "
        "два независимых следа пересборки (content skeleton exact unknown + "
        "F1 glyf×cmap exact unknown). В текущем корпусе оригиналов Т-Банка "
        "такая комбинация не встречается."
    ),
    "TBANK_COMPETITOR_TUPLE_018_NATIVE_COMBO_004": (
        "для нативной маршрутной пары slot 018 недостаточно одного нового "
        "размера: HARD требует одновременно неизвестные content skeleton, "
        "F1 glyf×cmap и F2 glyf×height при content_len 4405/4432/4436; для нового "
        "content_len=4432 дополнительно требуется exact-length novelty. "
        "На 133 оригиналах комбинация не встречается."
    ),
    "SBP_TBANK_BANK5_MISMATCH": (
        "bank5 вне исторического набора Т-Банка 00116/00117 — tier B "
        "(новый NSPK-эмитент возможен, как у Альфы с 00118); "
        "ФЕЙК только с второй независимой группой / HARD"
    ),
    "TBANK_DEBIT_ACCOUNT_PREFIX": (
        "счёт списания на чеке Т-Банка должен начинаться с 40817; "
        "префикс 40820 и др. — след чужого/нерезидентского шаблона"
    ),
    "KNOWN_FAKE_SBP_GRAMMAR_COMBINATION": (
        "route_marker и suffix-профиль одновременно вне подтверждённой "
        "грамматики Jasper SBP (K-TBANK-SBP-ROUTE-MARKER-001)"
    ),
    "SBP_PROFILE_EMPIRICAL": (
        "marker/suffix вне наблюдавшихся на подтверждённом корпусе для (class, bank5) — "
        "tier B, одна группа content_grammar_sbp; ФЕЙК только с второй независимой группой"
    ),
    "SBP_PROFILE_EPOCH_MISMATCH": (
        "class+bank5+suffix известны, но временное ядро ID и видимая дата существенно "
        "позже завершившегося корпусного периода этого профиля; само по себе это tier B"
    ),
    "SBP_PROFILE_EPOCH_TOO_EARLY": (
        "class+bank5+suffix известны в корпусе только с более поздней first_date, "
        "а ID→MSK и дата квитанции раньше этого окна (≥14 дн., n≥5) — "
        "временная стыковка поколения СБП невозможна (HARD)"
    ),
    "TBANK_F1_HEAD_MODIFIED_EPOCH": (
        "F1 TinkoffSans: head.created штатный, но head.modified ≠ корпусной "
        "константе 3722743619 (n=128) — признак стороннего subsetter/rebuild"
    ),
    "TBANK_F2_HEAD_MODIFIED_EPOCH": (
        "F2 TinkoffSansBold: head.created штатный, но head.modified ≠ корпусной "
        "константе 3724914673 (n=128) — признак стороннего subsetter/rebuild"
    ),
    "RECEIPT_STEM_REUSE_CONFLICT": (
        "первые три трёхзначных блока номера взяты из оригинального корпусного stem, "
        "но одновременно заменены последний блок, операция и дата; само по себе это tier B"
    ),
    "SBP_GRAMMAR_SUFFIX_PROFILE": (
        "suffix *60501 подтверждён только для class=B1, bank5=00117"
    ),
    "TBANK_TEXT_LAYOUT_FINGERPRINT": (
        "правая колонка ~250 pt: HARD только при dual-подтверждении raw CID/W "
        "и fitz + overlap/crop; иначе diagnostic/supporting"
    ),
    "TBANK_VALUE_RIGHT_EDGE_OVERSHOOT": (
        "строка value-колонки (x0≥100) вышла за дизайн R=250 pt "
        "(max overshoot >0.05; на 128 оригиналах ≤0.007) — типичный SEQ "
        "сдвиг footer amount+₽; не novelty atlas"
    ),
    "TBANK_VALUE_RIGHT_EDGE_OFF_LATTICE": (
        "квантованные residual value-колонки к R=250 на card/phone height "
        "должны быть только {-1.0, 0.0}; любой другой квант — SEQ layout"
    ),
    "TBANK_SBP_GEOMETRY_MISMATCH": (
        "правая граница SBP ID рассчитана по raw content stream (/W, Tm, CID) "
        "и не совпадает с колонкой значений ~250 pt"
    ),
    "TBANK_GLYPH_RENDER_GEOMETRY_MISMATCH": (
        "ширина глифа по цепочке Tj→CID→/W→hmtx не совпадает с fitz render "
        "(K-TBANK-GLYPH-ATLAS-001)"
    ),
    "USED_CID_EMPTY_GLYPH": (
        "реально использованный непробельный CID имеет пустой glyf — "
        "на 128 оригиналах не встречается"
    ),
    "GLYPH_SLOT_TRANSPLANT": (
        "контур буквы как у канона банка, но лежит в чужом GID и/или несёт "
        "hmtx|/W чужого слота — пересадка outline, не новый subset. "
        "Обход с целым визуалом: не двигать path между GID; буква в каноническом "
        "слоте с каноническими advance/LSB; нельзя «переклеить» только glyf, "
        "оставив метрики старого слота — HARD останется"
    ),
    "TBANK_TEXT_GLYPH_PARITY": (
        "decoded Unicode критического поля ≠ fitz render"
    ),
    "ANALYSIS_NOT_COMPLETED": (
        "незавершённый анализ не доказывает пересборку — только технический сбой"
    ),
    "TBANK_CATALOG_KEY_ORDER": (
        "словарь Catalog у оригиналов Т-Банка всегда начинается с /Names, "
        "и только потом идёт /Type/Catalog (133/133). Обратный порядок — "
        "другая программа записи того же словаря, не новая форма квитанции"
    ),
    "TBANK_STATIC_LABEL_CORRUPTED": (
        "JRXML печатает «Перевод» / «Телефон получателя» фиксированными CID; "
        "Latin homoglyph в ToUnicode (Перевiд, þелефон) — сломанный CMap, "
        "не новое ФИО. Банку пришлось бы сменить шаблон квитанции"
    ),
    "TBANK_DATE_LINE_CORRUPTED": (
        "первая строка IB/Receipt всегда DD.MM.YYYY (133/133 OpenPDF); "
        "кракозябры вместо даты — ToUnicode/CID, не новый формат отчёта"
    ),
}

_OBJECT_HINT: dict[str, str] = {
    "TBANK_CATALOG_KEY_ORDER": "Container: Catalog /Names before /Type",
    "PDF_TTF_BBOX_CROSS_LAYER_MISMATCH": "Font: F1/F2",
    "STATIC_EDITABLE_DIGIT_SUBSET_F2": "Font: F2",
    "K-FONT-002": "Font: F2",
    "TBANK_REASSEMBLED_BANK_ASSETS": "Provenance: reassembled bank assets",
    "TBANK_REASSEMBLED_BANK_ASSETS_V2": "Provenance: reassembled bank assets v2",
    "TBANK_REASSEMBLY_FAMILY_V3": "Provenance: F1/F2 reassembly family v3",
    "TBANK_SUBSET_CMAP_NOT_MINIMAL": "Font: ToUnicode minimality",
    "TBANK_W_ARRAY_NOT_MINIMAL": "Font: /W minimality",
    "TBANK_W_TTF_ADVANCE_MISMATCH": "Font: /W ↔ hmtx",
    "TBANK_CID_SERIALIZATION_BIJECTION_VIOLATION": "Font: used≡ToUnicode≡/W",
    "TBANK_FONT_SUBSET_EXACT_CLOSURE": "Font: FontFile2 exact closure",
    "TBANK_FONT_SUBSET_ORPHAN_RESIDUE": "Font: unmapped FontFile2 residue",
    "TBANK_F1_MAXP_RECOMPUTED_TO_SUBSET": "Font: F1 maxp recomputed to subset",
    "TBANK_F1_MAXP_COMPOSITE_ENVELOPE_MISMATCH": "Font: F1 maxp composite envelope",
    "TBANK_F1_HHEA_ENVELOPE_MISMATCH": "Font: F1 hhea envelope",
    "TBANK_F2_HEAD_ENVELOPE_MISMATCH": "Font: F2 head envelope",
    "TBANK_F2_MAXP_ENVELOPE_MISMATCH": "Font: F2 maxp envelope",
    "TBANK_F1_HMTX_ENVELOPE_MISMATCH": "Font: F1 hmtx envelope",
    "TBANK_F2_GLYF_LOCA_PADDING": "Font: F2 glyf↔loca padding",
    "TBANK_F2_GLYF_DIGIT_CARD_FAT": "Font: F2 glyf digit-card fat",
    "TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN": "Font: F2 glyf vs MediaBox height (ignored)",
    "TBANK_F2_GLYF_HEIGHT_MIDGAP": "Font: F2 glyf height-451 midgap",
    "TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH": "Font: F1 hmtx ↔ F2 glyf co-generation",
    "TBANK_BASEFONT_SUBSET_TAG_PAYLOAD_MISMATCH": "Font: BaseFont tag ↔ FF2 co-generation",
    "TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH": "Font: F1 glyf shape envelope",
    "TBANK_F1_GLYF_SIZE_MULTISET_MISMATCH": "Font: F1 glyf size multiset",
    "TBANK_SFNT_TABLE_ORDER_MISMATCH": "Font: SFNT table order",
    "TBANK_GLYF_ZERO_CONTOUR_STUB": "Font: zero-contour glyf stub",
    "TBANK_LOCA_ODD_OFFSET": "Font: odd loca offset",
    "TBANK_HMTX_METRIC_CARDINALITY": "Font: hmtx/hhea/maxp cardinality",
    "TBANK_COMPOSITE_EMPTY_COMPONENT": "Font: composite→empty component",
    "TBANK_TOUNICODE_BFCHAR_PRESENT": "Font: ToUnicode beginbfchar",
    "TBANK_FORBIDDEN_FONT_DESCRIPTOR_KEY": "Font: forbidden descriptor key",
    "TBANK_PROCSET_PRESENT": "PDF: /ProcSet present",
    "TBANK_FLATE_PREDICTOR_PRESENT": "PDF: /Predictor present",
    "TBANK_STREAM_CRLF_EOL": "PDF: stream CRLF EOL",
    "TBANK_CONTENT_TJ_PRESENT": "Stream: TJ operator",
    "TBANK_MARKED_CONTENT_PRESENT": "Stream: marked content",
    "TBANK_BT_NESTING_VIOLATION": "Stream: BT/ET nesting",
    "TBANK_TTF_UNEXPECTED_SFNT_TABLE": "Font: F1 SFNT inventory",
    "TBANK_TTF_REQUIRED_SFNT_TABLE_MISSING": "Font: F1 SFNT missing",
    "TBANK_TTF_INERT_PADDING_TABLE": "Font: F1 ZZZZ padding",
    "TBANK_F2_NOTDEF_GLYPH_EMPTY": "Font: F2 .notdef (GID 0)",
    "TBANK_F2_NOTDEF_NATIVE_PROFILE_MISMATCH": "Font: F2 .notdef native length",
    "TBANK_FONT_NOTDEF_ASYMMETRY": "Font: F1/F2/F3 .notdef asymmetry",
    "TBANK_AMOUNT_TEXT_SERIALIZATION_MISMATCH": "Field: Итого amount serialization",
    "TBANK_AMOUNT_LEADING_ZERO": "Field: Итого amount grammar",
    "TBANK_RECEIPT_ID_TRAILING_JUNK": "Field: Квитанция № trailing junk",
    "TBANK_PHONE_DEF_NOT_MOBILE": "Field: phone DEF not mobile 9xx",
    "TBANK_RECIPIENT_LEADING_WHITESPACE": "Field: Получатель leading spaces",
    "TBANK_TEXT_TRAILING_WHITESPACE": "Field: trailing ASCII spaces in text",
    "TEXT_TRAILING_NBSP_PADDING": "Field: trailing NBSP content-stream pad",
    "TBANK_SUPPORT_CONTACT_SPACING": "Field: Служба поддержки contact line",
    "TBANK_SUPPORT_CONTACT_CORRUPTED": "Field: Служба поддержки fb@tbank.ru missing/garbled",
    "TBANK_STATIC_LABEL_CORRUPTED": "Field: static label ToUnicode corrupted",
    "TBANK_DATE_LINE_CORRUPTED": "Field: first-line operation date ToUnicode",
    "UNUSED_CID_PRESENT": "Font: unused CMap symbols",
    "CMAP_EXTRA_SYMBOLS": "Font: CMap template leftovers",
    "TBANK_PARTY_NAME_CONSONANT_RUN": "Field: Отправитель/Получатель",
    "TBANK_CONTENT_ET_WHITESPACE_ANOMALY": "Stream: /Contents ET whitespace",
    "TBANK_CONTENT_INDENTED_OPERAND": "Stream: /Contents indented operands",
    "TBANK_CONTENT_TJ_TRAILING_WHITESPACE": "Stream: /Contents Tj trailing spaces",
    "TBANK_CONTENT_FLOAT_TRAILING_ZERO": "Stream: /Contents float trailing zero",
    "TBANK_CONTENT_TD_RUN_ANOMALY": "Stream: /Contents Td run after Tm",
    "TBANK_CONTENT_TD_SENTINEL": "Stream: Td -500 -500 sentinel",
    "TBANK_CONTENT_IMG_TD_SCALE_MISMATCH": "Stream: img cm scale ↔ Td pair",
    "TBANK_CONTENT_TR_MODE_ANOMALY": "Stream: Tr text-render mode",
    "TBANK_CONTENT_OPERATOR_SKELETON_UNKNOWN": "Stream: /Contents operator skeleton",
    "TBANK_CLIENT_CONTENT_SIZE_OUTLIER": "Stream: Клиенту /Contents size",
    "TBANK_GLYPH_INK_OVERLAP": "Font: glyph ink overlap",
    "TBANK_F1_COMPOSITE_FLOOR": "Font: F1 composite floor",
    "TBANK_F1_GLYF_CMAP_OUTLIER": "Font: F1 glyf↔cmap shape",
    "TBANK_F1_GLYF_CMAP_EXACT_UNKNOWN": "Font: F1 glyf exact atlas",
    "TBANK_SBP_F1_GLYF_CMAP_UNKNOWN": "Font: SBP F1 glyf exact atlas",
    "TBANK_F1_GLYF_TRAILING_JUNK": "Font: F1 glyf trailing junk past loca",
    "TBANK_F1_TWIN_SHAPE_MISMATCH": "Font: F1 twin shape mismatch",
    "TBANK_F1_CMAP_CARDINALITY_UNKNOWN": "Font: F1 cmap cardinality",
    "TBANK_F1_ORPHAN_SIMPLE_GLYPH": "Font: F1 orphan glyph",
    "TBANK_KNOWN_FAKE_SBP_SERIALIZER_V1": "Provenance: SBP serializer family v1",
    "TBANK_CARD_OTHER_INTERNAL_WHITESPACE_PADDING": "Stream: /Contents whitespace",
    "TBANK_KNOWN_FAKE_CARD_TBANK_SERIALIZER_V1": "Provenance: CARD_TBANK serializer family v1",
    "TBANK_KNOWN_FAKE_NOCOMM_SERIALIZER_V1": "Provenance: NOCOMM serializer family v1",
    "USED_CID_MISSING_FROM_CMAP": "Font: used CID → ToUnicode",
    "TBANK_CONTENT_STREAM_EDIT": "Stream: /Contents",
    "TBANK_KEYWORDS_GENERATION_MISMATCH": "Metadata: /Keywords",
    "TBANK_INFO_KEYWORDS_LEX_MISMATCH": "Metadata: /Info /Keywords",
    "TBANK_BT_ET_MISMATCH": "AST: BT/ET",
    "SBP_CIPHER_MISSING": "Field: СБП ID",
    "SBP_CIPHER_STRUCTURE": "Field: СБП ID",
    "SBP_CIPHER_TIMESTAMP": "Field: СБП ID",
    "SBP_ROUTE_FIELD_CONTAMINATION": "Field: СБП ID (route/class)",
    "SBP_CONTROL_TRIPLE_MISMATCH": "Field: СБП ID (control link)",
    "SBP_LINKED_TUPLE_CONFLICT": "Field: СБП ID (full linked tuple)",
    "SBP_LINKED_TUPLE_CROSS_CLASS": "Field: СБП ID (cross-class grammar splice)",
    "TBANK_FONT_GLYF_TRAILING_DATA": "FontFile2: standalone malformed glyf trailing data",
    "TBANK_SBP_TUPLE_GLYF_RESIDUE_SIGNATURE": "Field+Font: SBP tuple + FontFile2 glyf residue",
    "TBANK_COMPETITOR_NOVELTY_COMBO_001": "Provenance: competitor novelty combo x4",
    "TBANK_COMPETITOR_TUPLE_791103_COMBO_002": "Provenance: competitor tuple+structure combo",
    "TBANK_COMPETITOR_TUPLE_017_791103_COMBO_003": "Provenance: competitor tuple+structure combo",
    "SBP_TBANK_BANK5_MISMATCH": "Field: СБП ID (issuer bank5)",
    "TBANK_DEBIT_ACCOUNT_PREFIX": "Field: Счет списания (account prefix)",
    "KNOWN_FAKE_SBP_GRAMMAR_COMBINATION": "Field: СБП ID (route_marker+grammar)",
    "SBP_PROFILE_EMPIRICAL": "Field: СБП ID (empirical profile)",
    "SBP_PROFILE_EPOCH_MISMATCH": "Field: СБП ID (profile epoch)",
    "SBP_PROFILE_EPOCH_SLOT_CONFLICT": "Field: СБП ID (epoch slot B1013)",
    "SBP_PROFILE_EPOCH_TOO_EARLY": "Field: СБП ID (epoch too early)",
    "TBANK_F1_HEAD_MODIFIED_EPOCH": "Font: F1 head.modified epoch",
    "TBANK_F2_HEAD_MODIFIED_EPOCH": "Font: F2 head.modified epoch",
    "RECEIPT_STEM_REUSE_CONFLICT": "Field: Квитанция № (corpus stem)",
    "SBP_GRAMMAR_SUFFIX_PROFILE": "Field: СБП ID (suffix grammar)",
    "TBANK_SBP_GEOMETRY_MISMATCH": "Field: СБП ID (raw geometry)",
    "TBANK_GLYPH_RENDER_GEOMETRY_MISMATCH": "Font: glyph render chain",
    "USED_CID_EMPTY_GLYPH": "Font: used CID glyf",
    "GLYPH_SLOT_TRANSPLANT": "Font: glyph slot transplant",
    "TBANK_TEXT_GLYPH_PARITY": "Field: critical text render",
    "TBANK_TEXT_LAYOUT_FINGERPRINT": "Layout: правая колонка",
    "TBANK_VALUE_RIGHT_EDGE_SPREAD": "Layout: value right-edge constancy",
    "TBANK_VALUE_RIGHT_EDGE_OVERSHOOT": "Layout: value column past R=250",
    "TBANK_VALUE_RIGHT_EDGE_OFF_LATTICE": "Layout: value residual lattice",
}


def _flag_lines(flag: V6Flag, idx: int) -> list[str]:
    rule = flag.rule_id or flag.code
    lines = [f"{idx}. [{flag.code}] {flag.detail}"]
    if rule and rule != flag.code:
        lines.append(f"   Rule: {rule}")
    obj = _OBJECT_HINT.get(flag.code, "")
    if obj:
        lines.append(f"   Object: {obj}")
    if flag.group:
        lines.append(f"   Group: {flag.group}")
    why = _WHY_NOT_VARIABILITY.get(flag.code, "")
    if why:
        # Split "Обход…" into its own line for @kronlead readability.
        if "Обход с целым визуалом:" in why:
            head, _, bypass = why.partition("Обход с целым визуалом:")
            head = head.strip().rstrip(".")
            if head:
                lines.append(f"   Почему не вариативность: {head}")
            lines.append(f"   Обход с целым визуалом: {bypass.strip()}")
        else:
            lines.append(f"   Почему не вариативность: {why}")
    impact = _IMPACT_BY_TIER.get(flag.tier, _IMPACT_BY_TIER.get("A", ""))
    if impact:
        lines.append(f"   Влияние: {impact}")
    return lines


def _decisive_flags(pipeline: PipelineResult) -> list[V6Flag]:
    out: list[V6Flag] = []
    out.extend(pipeline.known_fake_flags)
    out.extend(pipeline.hard_flags)
    if pipeline.cross_document_identity_conflict:
        for f in pipeline.hard_flags:
            if f.code == "OPERATION_ID_REUSED":
                return out
    return out


def build_expert_report(
    pipeline: PipelineResult,
    verdict: str,
) -> dict:
    """
    Структурированный отчёт v6 для привилегированного пользователя.
    Только влияющие на вердикт признаки (HARD/KNOWN; supporting — лишь если дали ФЕЙК).
    """
    decisive = _decisive_flags(pipeline)
    supporting = list(pipeline.supporting_flags)

    body_lines: list[str] = []

    if not pipeline.analysis_complete:
        body_lines.append("❌ ФЕЙК — анализ не завершён")
        body_lines.append("")
        body_lines.append(
            "Причина: [ANALYSIS_NOT_COMPLETED] полный pipeline не выполнен."
        )
        body_lines.append(
            "Это технический сбой, а не доказанная пересборка чека."
        )
        if pipeline.stats.get("fitz_missing"):
            body_lines.append("Деталь: PyMuPDF (fitz) недоступен на сервере.")
        if pipeline.stats.get("encrypted"):
            body_lines.append("Деталь: PDF зашифрован — полная проверка невозможна.")
        if pipeline.stats.get("budget_exceeded"):
            body_lines.append(
                f"Деталь: превышен budget ({pipeline.stats['budget_exceeded']})."
            )
        return {
            "summary": "ФЕЙК (анализ не завершён)",
            "body_lines": body_lines,
            "ignored": [],
            "decisive_count": 0,
        }

    if pipeline.not_a_tbank_receipt:
        body_lines.append("❌ ФЕЙК — не квитанция Т-Банка")
        body_lines.append("")
        body_lines.append("[NOT_TBANK_RECEIPT] файл не распознан как чек Т-Банка.")
        return {
            "summary": "ФЕЙК (не Т-Банк)",
            "body_lines": body_lines,
            "ignored": [],
            "decisive_count": 0,
        }

    if verdict == "ФЕЙК":
        # @kronlead: only decisive HARD/KNOWN. No supporting / soft flags.
        hard_only = [
            f for f in decisive
            if (f.tier or "").upper() in ("A", "HARD", "KNOWN")
            or f in pipeline.known_fake_flags
            or f in pipeline.hard_flags
        ]
        if not hard_only:
            hard_only = list(decisive)
        n = len(hard_only)
        body_lines.append(f"❌ ФЕЙК — обнаружено {n} решающих HARD/KNOWN")
        body_lines.append("")
        idx = 1
        for f in hard_only:
            body_lines.extend(_flag_lines(f, idx))
            body_lines.append("")
            idx += 1
        if not hard_only and supporting:
            # Fallback: supporting-only FAKE (rare) — still list them as decisive.
            body_lines.append(
                "ФЕЙК без одиночного HARD: сработали supporting-группы "
                "(см. ниже). Новые soft/diagnostic флаги не показываем."
            )
            body_lines.append("")
            for f in supporting:
                body_lines.extend(_flag_lines(f, idx))
                body_lines.append("")
                idx += 1
    else:
        body_lines.append("✅ ОРИГИНАЛ")
        body_lines.append("")
        body_lines.append(
            "Полный pipeline завершён. Hard-нарушений и known-fake signatures "
            "не обнаружено."
        )

    summary = body_lines[0] if body_lines else ("ФЕЙК" if verdict == "ФЕЙК" else "ОРИГИНАЛ")
    return {
        "summary": summary.replace("❌ ", "").replace("✅ ", ""),
        "body_lines": body_lines,
        "ignored": [],
        "decisive_count": len(decisive),
    }
