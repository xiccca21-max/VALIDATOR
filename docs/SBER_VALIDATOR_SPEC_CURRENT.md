# Сбербанк: полная спецификация проверки PDF-квитанций

**Состояние кода:** 19.08.2026  
**Движок:** `detector.sber_v2`  
**Версия:** `2.1.1`  
**Режим:** `full`

## 1. Назначение

Документ описывает:

- все шесть поддерживаемых профилей Сбербанка;
- классификацию метода и PDF-generator;
- полный Sber v2 pipeline;
- контейнер, xref, streams и content grammar;
- dual-parser, overlay и geometry;
- fonts, glyph spacing и reassembly;
- SBP ID и семантические связи;
- cross-document базы;
- tiers и итоговый verdict.

## 2. Production-путь

```text
PDF
→ detector.route
→ profiles.identify: sber
→ global preflight
→ detector.sber / sber_v2.engine.analyze
→ sber_v2.stages.run_pipeline
→ sber_v2.verdict.compute_verdict
→ внешний reputation/status/UI
```

Global preflight и reputation находятся вне `sber_v2`. Итог бота может
содержать дополнительные внешние сигналы.

## 3. Точка входа

`detector/sber_v2/engine.py::analyze(pdf_bytes, file_hash="")`

Порядок:

1. SHA-256 файла;
2. полный pipeline;
3. verdict;
4. expert report;
5. common response.

Выход:

```text
verdict: ЧИСТО | ФЕЙК | НЕИЗВЕСТНЫЙ ДОКУМЕНТ
emoji: ✅ | 🔴 | ⚪
score: 0 | 60
details:
  validator_version = 2.1.1
  engine = sber_v2
  profile_id
  submethod
  submethod_label
  generator_path
  new_coherent_profile
  completed_checks
  stats
  hard/known/supporting counts
  ignored_observations
  analysis_complete
  cross_document_identity_conflict
  expert_report
```

## 4. Как определяется Сбербанк

`sber_profiles.is_sber_receipt` принимает документ, если:

- есть `Сбербанк` / `Sberbank`;
- есть `Перевод клиенту Сбербанка`;
- либо присутствует профильный текст перевода вместе с Jasper или Quartz;
- либо Jasper/Quartz shell содержит `Номер операции в СБП`;
- либо есть `Сумма перевода` и `Счёт отправителя`.

Отдельно исключаются чужие Jasper/iText issuer:

- Банк ДОМ.РФ;
- Газпромбанк-маркеры.

Одинаковый PDF toolkit не доказывает Сбербанк.

Если банк не подтверждён, итог:

`НЕИЗВЕСТНЫЙ ДОКУМЕНТ`, а не `ФЕЙК`.

## 5. Generator path

`detect_generator_path`:

- `ios_quartz` — Quartz PDFContext;
- `pdfium` — PDFium;
- `jasper_itext` — JasperReports или iText;
- `unknown_coherent` — другой согласованный generator.

Generator path участвует в:

- выборе submethod P2/P3;
- profile gates;
- font/container contracts;
- exact SBP profile;
- решении о новом целостном профиле.

## 6. Все поддерживаемые методы

### 6.1. SBR-P1 — `card_other_ios`

Метка: `Перевод в другой банк по номеру карты`.

Классификация:

`Перевод в другой банк по номеру карты`.

Типичный generator:

`ios_quartz`.

Поля:

- сколько/сумма;
- комиссия;
- списано;
- карта/получатель;
- дата/время;
- operation/document identity.

Специфическая семантика:

`Списано = Сколько + Комиссия`.

Несовпадение:

- `SBER_AMOUNT_ARITHMETIC_MISMATCH`;
- дополнительно `SBER_LINKED_SEMANTIC_TUPLE_CONFLICT`.

### 6.2. SBR-P2 — `sber_internal_jasper`

Метка: `Перевод клиенту СберБанка`.

Классификация:

- `Перевод клиенту Сбербанка`;
- либо поля `Номер карты получателя` / `Номер счёта получателя`;
- generator не PDFium.

Типичный generator:

`jasper_itext`.

Идентификатор документа:

внутренний `100` + 16 цифр, всего 19 цифр.

Специфические font floors:

- nonempty glyph ≥75;
- composite glyph ≥14.

HARD:

- `SBER_INTERNAL_GLYF_NONEMPTY_FLOOR`;
- `SBER_INTERNAL_GLYF_COMPOSITE_FLOOR`.

### 6.3. SBR-P3 — `sber_internal_pdfium`

Метка: `Перевод клиенту СберБанка (PDFium)`.

Тот же текстовый метод, но generator=`pdfium`.

Это отдельный штатный профиль, поэтому PDFium здесь не считается автоматически
чужим generator. К нему применяются собственные container/font/layout
контракты.

### 6.4. SBR-P4 — `legacy_phone`

Метка: `Перевод по номеру телефона (legacy)`.

Классификация:

`Перевод по номеру телефона`, если более приоритетные SBP/card/internal titles
не найдены.

Legacy document ID:

`14 цифр + 22 lowercase alnum`, всего 36 символов.

Проверяются:

- наличие/структура legacy document;
- связь с датой/полями;
- phone DEF;
- layout/font profile legacy shell.

### 6.5. SBR-P5 — `sbp_outgoing`

Метка: `Перевод по СБП`.

Классификация:

- `Перевод по СБП`;
- `Номер операции в СБП`.

Основной SBP-профиль. Проверяются:

- 32-символьный SBP ID;
- timestamp;
- linked tuple;
- exact Jasper SBP profile;
- sender/recipient FIO shape;
- телефон;
- банк;
- сумма;
- счёт отправителя;
- label/value geometry;
- font/content contracts.

### 6.6. SBR-P6 — `sbp_request`

Метка: `Перевод по запросу СБП`.

Классификация имеет наивысший приоритет:

`Перевод по запросу СБП`.

Получает SBP ID/timestamp/tuple checks, но использует отдельный profile_id и
layout/field contract.

### 6.7. `unknown`

Если метод не распознан:

- при согласованном неизвестном generator создаётся `unknown_coherent`;
- `new_coherent_profile=True`;
- без HARD/KNOWN итог `НЕИЗВЕСТНЫЙ ДОКУМЕНТ`.

QR, наличные и отдельный универсальный `other` не поддерживаются.

## 7. Приоритет классификации

`classify_submethod`:

1. `Перевод по запросу СБП` → P6;
2. `Перевод по СБП` / `Номер операции в СБП` → P5;
3. `Перевод в другой банк по номеру карты` → P1;
4. `Перевод клиенту Сбербанка` → P2/P3 по generator;
5. `Перевод по номеру телефона` → P4;
6. recipient card/account fields → P2/P3;
7. иначе unknown.

## 8. Фактический pipeline

Порядок:

1. `intake`;
2. text/metadata extraction;
3. `classify`;
4. `is_sber_receipt`;
5. `file_size`;
6. `xref_object_graph`;
7. `stream_integrity`;
8. `content_grammar`;
9. `dual_parser_parity`;
10. `overlay_hidden_text`;
11. `label_value_geometry`;
12. `font_contamination`;
13. `glyph_spacing`;
14. `sbp_exact_profile`;
15. `embedded_font_reassembly_forensics`;
16. `semantic_tuples`;
17. `sbp_linked_tuple`;
18. `legacy_document`;
19. `cross_document_identity`;
20. `reassembled_assets`;
21. `pipeline_complete`.

Pipeline выполняется внутри общего `try`. Любое необработанное исключение:

- `analysis_complete=False`;
- `pipeline_error`;
- итог `ФЕЙК`.

После intake нет CPU early exit по уже найденному HARD: остальные стадии обычно
продолжают собирать доказательства.

## 9. Intake

- пустой файл → incomplete;
- больше 8 000 000 B → incomplete;
- `/Encrypt` в первых 8000 байтах → incomplete.

## 10. File size

`file_size.check_file_size` сравнивает размер с envelope конкретного
`profile_id`.

Примеры atlas:

```text
sbp_outgoing:          102293–103469 B, soft 98000–106500 B
sber_internal_jasper:   44243–44948 B, soft 43500–47000 B
card_other_ios:         38736 B, soft 34000–45000 B
```

Модуль может создать strong/soft observations, но финальную силу всегда
определяет `ingest_flag`.

Текущая policy демотирует:

`SBER_FILE_SIZE_STRONG_OUTLIER`.

То есть сейчас даже strong file-size code не решает verdict. Причина — длина
ФИО/банка и новые genuine templates меняют размер.

## 11. Xref и object graph

`container.check_xref_object_graph` проверяет:

- header/trailer/startxref;
- xref offsets;
- object definitions;
- object references;
- дубли;
- trailing bytes;
- expected object graph profile.

HARD:

- `SBER_XREF_OBJECT_GRAPH_CONFLICT`;
- общие structural-коды.

Incremental/repeated EOF/xref:

- собираются;
- `MULTIPLE_EOF_PRESENT`, `MULTIPLE_XREF_PRESENT`, `PREV_TRAILER_PRESENT`,
  `INCREMENTAL_UPDATE_PRESENT` сейчас находятся в IGNORE.

То есть incremental marker без активного противоречия не считается подделкой.

## 12. Stream integrity

`streams.check_stream_integrity` проверяет:

- decompression;
- `/Length`;
- filters;
- stream boundaries;
- serializer consistency;
- raw/decoded profile.

Практические допуски:

- отличие declared `/Length` от фактического больше 2 байт — нарушение;
- неиспользованный хвост после zlib больше 2 байт — нарушение.

HARD:

- `SBER_STREAM_INTEGRITY_VIOLATION`;
- `STREAM_DECOMPRESSION_FAILED`;
- `STREAM_LENGTH_MISMATCH`;
- `UNEXPECTED_STREAM_FILTER`.

Supporting:

- compression ratio;
- decoded size;
- filter anomaly;
- serializer profile shift.

Raw content length novelty демотирована.

## 13. Content grammar

`content.check_content_grammar` получает `profile_id`.

Проверяются:

- operator grammar;
- `q/Q`;
- `BT/ET`;
- text-state operators;
- tracking `Tc`;
- word spacing `Tw`;
- `TJ` kerning;
- header/footer serialization;
- profile skeleton;
- labels/static text.

Допустимые q/Q-пары:

```text
sbp_outgoing:          (7,4), (8,4), (8,5)
sber_internal_jasper: (10,4), (11,4), (13,4)
```

HARD:

- `SBER_CONTENT_OPERATOR_GRAMMAR_CONFLICT`;
- `SBER_CONTENT_QQ_PROFILE`;
- `SBER_BT_ET_MISMATCH`;
- `SBER_CONTENT_TC_TRACKING`;
- `SBER_CONTENT_TW_WORD_SPACING`;
- `SBER_CONTENT_TJ_KERNING`;
- `SBER_HEADER_TRAILING_PADDING`.

Ignored:

- `SBER_CONTENT_SKELETON_DRIFT`;
- `SBER_CONTENT_RAW_LENGTH_OUTLIER`.

## 14. Dual-parser parity

`parity.check_dual_parser_parity` сравнивает:

- PyMuPDF text;
- direct/content parser;
- SBP ID;
- legacy document;
- internal document;
- критические поля.

Несовпадение:

`SBER_DUAL_PARSER_FIELD_PARITY` — HARD.

Если оба parser не нашли обязательное поле и точный profile разрешает правило:

`SBER_REQUIRED_FIELD_MISSING`.

## 15. Overlay и hidden text

`overlay.check_overlay_hidden_text` ищет:

- второй текстовый слой;
- скрытые поля;
- overlapping replacement text;
- невидимые значения.

Порог decisive hidden layer — не менее трёх hidden spans.

HARD:

`SBER_OVERLAY_HIDDEN_TEXT_LAYER`.

## 16. Label/value geometry

`geometry.check_label_value_geometry` анализирует:

- координаты labels;
- координаты values;
- expected relationship по profile;
- left edge labels;
- header date centering;
- separators;
- amount/ruble spacing.

HARD:

- `SBER_LABEL_VALUE_GEOMETRY_CONFLICT`;
- `SBER_LABEL_LEFT_EDGE_SPREAD`;
- `SBER_HEADER_DATE_CENTER_MISMATCH`;
- `SBER_STATIC_TEXT_ADVANCE_MISMATCH`;
- `SBER_STATIC_LABEL_OUTLINE_MISMATCH`;
- `SBER_SEPARATOR_ADVANCE_MISMATCH`;
- `SBER_AMOUNT_RUBLE_SPACING_INVALID`.

Если exact profile не подтверждён, corpus novelty не должна превращаться в
ложный HARD.

## 17. Font contamination

`fonts.check_font_contamination` получает:

- Producer/Creator;
- profile_id;
- PDF font graph.

Проверочная цепочка:

```text
font resource
→ used CID
→ ToUnicode
→ /W
→ FontFile2
→ loca/glyf/hmtx
→ outlines/advances
→ static labels
```

HARD:

- `SBER_FONT_LAYER_CONTAMINATION`;
- missing CID/CMap/W/FontFile2;
- empty used glyph;
- slot transplant;
- outline mismatch;
- `SBER_FONT_CID_CLOSURE_VIOLATION`;
- `SBER_FONT_W_QUANTIZER_MISMATCH`;
- `SBER_FONT_REVERSE_GLYPH_CLOSURE`;
- `SBER_FONT_GLYF_UNIQ_LENS`;
- `SBER_FONT_GLYF_NONEMPTY_COUNT`;
- loca/contour mismatch;
- hmtx advance vocabulary;
- internal Jasper packing floors;
- raw FontFile2 too small.

Ignored novelty:

- новый FontFile2 SHA;
- exact decoded FontFile2 profile;
- strong FF2 size outlier;
- новый subset prefix.

Ключевые profile-пороги:

```text
sbp_outgoing:
  unique nonempty glyf lengths 52–56
  nonempty/contour glyphs 66–73
  unique positive hmtx advances 425
  compressed FontFile2 ≥22000 B

sber_internal_jasper exact shell:
  decoded FontFile2 {55136, 55476, 56064}
  nonempty glyphs ≥75
  composite glyphs ≥14
```

## 18. Glyph spacing

`glyph_spacing.check_glyph_spacing` измеряет:

- ink overlap;
- слишком широкий gap;
- min/max profile;
- число glyph pairs.

Пороги Jasper/iText:

```text
overlap >0                → HARD
wide gap >650 units       → HARD
sbp_outgoing pairs <238   → HARD
sbp_outgoing ink max <550 → HARD
allowed ink min: 21, 22, 33, 43, 52
```

HARD:

- `SBER_GLYPH_INK_OVERLAP`;
- `SBER_GLYPH_INK_WIDE_GAP`;
- `SBER_GLYPH_INK_MAX_TOO_LOW`;
- `SBER_GLYPH_INK_MIN_OUT_OF_BAND`;
- `SBER_GLYPH_PAIRS_TOO_FEW`.

Exact discrete `SBER_GLYPH_INK_MAX_PROFILE` демотирован.

## 19. Exact SBP profile

`sbp_exact_profile.check_sbp_exact_profile` получает:

- PDF;
- profile_id;
- generator_path;
- Creator/Producer.

Точные HARD включаются только при подтверждённом SBP/Jasper contract.

Exact `sbp_outgoing` contract:

```text
profile_id: sbp_outgoing
generator: jasper_itext
Creator: JasperReports Library version 6.18.1-9d75d1969e774d4f179fb3be8401e98a0e6d1611
Producer: iText 2.1.7 by 1T3XT
MediaBox: 300×795 pt
content skeleton: присутствует в atlas
```

Внутри exact-проверок:

- static label advances: tolerance `0.015 pt`;
- separator start `(22.24, 697.74)`, end x `289.756 ±0.03`;
- header date center x `153.000 ±0.01`;
- SBP marker около y=`304.74`;
- profile-specific ruble CID spacing;
- static glyph outline atlas.

Если документ явно `sbp_outgoing + Jasper`, но page/skeleton новый относительно
малого atlas:

- exact HARD пропускаются;
- добавляется diagnostic `SBER_SBP_EXACT_NEAR_MISS`;
- банк остаётся Сбербанком;
- документ не становится UNKNOWN только из-за exact novelty.

## 20. Embedded font reassembly

`embedded_font_reassembly.check_embedded_font_reassembly(bank="sber")`
проверяет:

- raw NUL в тексте;
- control bytes в text operands;
- content/font cross-product;
- used-glyph subset cardinality;
- Jasper object family.

HARD:

- `SBER_REBUILD_RAW_NUL_IN_TEXT_001`;
- `SBER_REBUILD_TEXT_OPERAND_CONTROL_BYTE_005`;
- `SBER_REBUILD_CONTENT_FONT_CROSSPRODUCT_002`;
- `SBER_REBUILD_USED_GLYPH_SUBSET_CARDINALITY_003`;
- `SBER_REBUILD_JASPER_OBJECT_FAMILY_CONFLICT_004`.

## 21. Общая семантика

`check_semantic_tuples` проверяет:

- invisible control characters;
- NUL/U+FFFD/битый рубль;
- literal `сейчас`;
- required fields при dual-parser miss;
- phone DEF;
- header date whitespace;
- FIO leading/trailing padding;
- amount leading whitespace;
- bank-name trailing whitespace;
- profile-specific arithmetic.

HARD:

- `TEXT_LAYER_INCONSISTENT`;
- `SBER_LINKED_SEMANTIC_TUPLE_CONFLICT`;
- `SBER_REQUIRED_FIELD_MISSING`;
- whitespace/padding-коды;
- `SBER_PHONE_DEF_NOT_MOBILE`.

FIO alphabet/consonant-run эвристики считаются diagnostics.

## 22. FIO правила SBP

Для `sbp_outgoing`:

- получатель: `Имя Отчество И`;
- отправитель: `Имя Отчество И.`.

HARD:

- `SBER_SBP_RECIPIENT_FIO_FORMAT`;
- `SBER_SBP_SENDER_FIO_FORMAT`;
- `SBER_RECIPIENT_INITIAL_PUNCTUATION`;
- `SBER_FIO_TRAILING_PADDING`.

Проверяется форма банковского поля, а не морфологический суффикс отчества.
Правила типа «обязано оканчиваться на -ович/-евна» в активном detector нет.

## 23. SBP ID

Применяется только к:

- `sbp_outgoing`;
- `sbp_request`.

ID:

`A/B + 31 alnum`, всего 32 символа.

Извлечение:

- рядом с `Номер операции в СБП`;
- следующие 1–3 строки;
- fallback по compact text.

Проверки:

- наличие;
- alphabet/length;
- embedded date/time;
- linked tuple;
- profile-specific marker/tail;
- timestamp delta.

HARD:

- `SBER_SBP_LINKED_TUPLE_CONFLICT`;
- `SBER_SBP_TIMESTAMP_MISMATCH`.

Для `sbp_outgoing` corpus-bound:

`|Δt| ≤ 10 секунд`.

Shared cipher допускает более широкий технический предел, но Sber semantics
повышает превышение 10 секунд до linked-tuple HARD.

Supporting:

- `SBER_SBP_EMPIRICAL_PROFILE`;
- `SBER_SBP_TAIL_UNKNOWN`;
- `SBER_SBP_MARKER_UNKNOWN`.

## 24. Legacy/internal document IDs

`check_legacy_document` применяется по profile:

- P4 legacy: `14 digits + 22 lowercase alnum`;
- P2/P3 internal: `100` + 16 digits.

Проверяется:

- формат;
- присутствие;
- связь с method/profile;
- dual-parser parity;
- cross-document identity.

## 25. Card arithmetic

Только `card_other_ios`:

```text
Списано = Сколько + Комиссия
```

Допуск:

`0.02 ₽`.

Несоответствие даёт HARD.

## 26. Cross-document identity

`cross_document.check_cross_document_identity` получает:

- PDF;
- text;
- file SHA;
- profile_id.

Проверяет повтор/конфликт:

- SBP ID;
- legacy document;
- internal document;
- реквизиты операции;
- content identity.

HARD:

- `SBER_CROSS_DOCUMENT_IDENTITY_CONFLICT`;
- `OPERATION_ID_REUSED`.

Supporting:

`SBER_CROSS_DOCUMENT_WEAK_MATCH`.

## 27. Reassembled bank assets

`check_reassembled_bank_assets` объединяет:

- profile shell;
- static assets;
- content;
- fonts;
- уже найденные independent forensic groups.

KNOWN:

`SBER_REASSEMBLED_BANK_ASSETS`.

Он требует подтверждённой комбинации и
`generator_confirmed_malicious=True`, а не одного нового hash. В текущей
конфигурации эта ветка фактически deferred.

## 28. Known signatures

`known_signatures.py` содержит exact SHA подтверждённых подделок.

Совпадение:

`SBER_KNOWN_FAKE_SIGNATURE`.

Текущий registry содержит один подтверждённый file SHA-256; registry
generator skeletons пуст.

Старый `SBER_KNOWN_FAKE_FONTFILE2` удалён: pin на FontFile2 SHA создавал false
positives на новых genuine subsets.

## 29. New coherent profile

Если profile_id неизвестен, но generator и слои согласованы:

`new_coherent_profile=True`.

При отсутствии HARD/KNOWN/двух supporting-групп:

`НЕИЗВЕСТНЫЙ ДОКУМЕНТ`.

Это защита от автоматического признания нового целостного шаблона оригиналом.

## 30. Verdict

Порядок:

1. incomplete → `ФЕЙК`, score 60;
2. not Sber receipt → `НЕИЗВЕСТНЫЙ ДОКУМЕНТ`, score 0;
3. HARD/KNOWN → `ФЕЙК`, score 60;
4. cross-document conflict → `ФЕЙК`, score 60;
5. минимум две independent supporting-группы → `ФЕЙК`, score 60;
6. new coherent profile → `НЕИЗВЕСТНЫЙ ДОКУМЕНТ`, score 0;
7. иначе `ЧИСТО`, score 0.

## 31. Supporting-группы

- `B1_serializer_container`;
- `B2_layout_content`;
- `B3_metadata_profile`;
- `B4_static_assets`;
- `B4_font_subsetter`;
- `B5_sbp_empirical`;
- `B6_cross_document_weak`.

Один B-флаг недостаточен.

## 32. Ignored policy

Не решают verdict:

- content skeleton drift;
- новый producer;
- новый FontFile2 SHA;
- новая page size;
- новый image bundle;
- новый subset prefix;
- FIO alphabet/consonant/yery/length heuristics;
- file/content/FontFile2 size novelty;
- exact FontFile2 decoded profile;
- exact glyph ink max;
- incremental update markers без активного конфликта.

`ingest_flag` применяет IGNORE раньше tier emitter.

## 33. Матрица методов

```text
Все:
intake, classification, file size, xref, streams, content,
parity, overlay, geometry, fonts, glyph spacing, reassembly,
semantic controls, cross-document.

P1 card_other_ios:
+ Quartz/iOS profile;
+ card fields;
+ Списано = Сколько + Комиссия.

P2 internal Jasper:
+ internal 100... document;
+ Jasper/iText shell;
+ internal font floors.

P3 internal PDFium:
+ internal 100... document;
+ отдельный PDFium profile.

P4 legacy phone:
+ phone fields;
+ 36-char legacy document.

P5 SBP outgoing:
+ SBP ID/timestamp/tuple/exact profile;
+ sender/recipient FIO shape;
+ phone/bank/account fields.

P6 SBP request:
+ отдельный request profile;
+ SBP ID/timestamp/tuple.
```

## 34. Active и legacy

Активны:

- `detector/sber_v2/*`;
- `detector/sber_profiles.py`;
- `detector/embedded_font_reassembly.py`;
- shared routing/reputation/status.

Старые weighted Sber policies и legacy analyzer не являются источником verdict,
если текущий pipeline их явно не импортирует.

## 35. Основные файлы

- `detector/sber_v2/engine.py`;
- `detector/sber_v2/stages.py`;
- `detector/sber_v2/rules.py`;
- `detector/sber_v2/verdict.py`;
- `detector/sber_profiles.py`;
- `detector/sber_v2/container.py`;
- `detector/sber_v2/streams.py`;
- `detector/sber_v2/content.py`;
- `detector/sber_v2/parity.py`;
- `detector/sber_v2/overlay.py`;
- `detector/sber_v2/geometry.py`;
- `detector/sber_v2/fonts.py`;
- `detector/sber_v2/glyph_spacing.py`;
- `detector/sber_v2/sbp.py`;
- `detector/sber_v2/sbp_exact_profile.py`;
- `detector/sber_v2/semantics.py`;
- `detector/sber_v2/cross_document.py`;
- `detector/sber_v2/profile_gates.py`;
- `detector/sber_v2/known_signatures.py`;
- `detector/embedded_font_reassembly.py`.

## 36. Интерпретация

`ЧИСТО` — в известных профилях не найдено достаточных доказательств подделки.

`НЕИЗВЕСТНЫЙ ДОКУМЕНТ` — либо это не Сбербанк, либо найден новый внутренне
целостный профиль.

`ФЕЙК` — обнаружено самостоятельное противоречие, известная сигнатура,
cross-document conflict или минимум две независимые supporting-группы.

