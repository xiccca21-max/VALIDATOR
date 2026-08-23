# Т-Банк: полная спецификация проверки PDF-квитанций

**Состояние кода:** 19.08.2026  
**Движок:** `detector.tbank_v6`  
**Версия результата:** `6.5.5`  
**Источник истины:** фактически вызываемый код, а не старые спецификации и не комментарии к отключённым правилам.

## 1. Назначение и границы

Документ описывает полный путь проверки Т-Банка:

1. как общий маршрутизатор выбирает Т-Банк;
2. как определяется канал и подметод перевода;
3. какие проверки выполняются для всех чеков;
4. какие проверки включаются только для СБП, телефона или карты;
5. как анализируются PDF-контейнер, потоки, текст, координаты, шрифты и метаданные;
6. как работают известные сигнатуры, базы повторов и эмпирические атласы;
7. как флаги превращаются в `ЧИСТО` или `ФЕЙК`;
8. какие наблюдения намеренно не влияют на вердикт.

Проверка подлинности PDF и проверка статуса операции — разные задачи. Движок `tbank_v6` отвечает за подлинность документа. Сообщение «перевод не выполнен» формируется внешним status-слоем и само по себе не означает подделку PDF.

Также необходимо различать результат самого `tbank_v6` и окончательный ответ
бота. До движка работает global preflight, а после него бот может добавить
reputation-сигналы. Поэтому итог в Telegram в отдельных случаях строже, чем
чистый вызов `tbank_v6.engine.analyze`.

## 2. Основные понятия

- **HARD / tier A** — одного активного флага достаточно для `ФЕЙК`.
- **KNOWN** — подтверждённая сигнатура известного семейства подделок; одного флага достаточно.
- **Supporting / tier B** — слабое доказательство. `ФЕЙК` возникает только при двух и более разных supporting-группах.
- **IGNORE / diagnostic** — телеметрия. На вердикт не влияет.
- **Profile gate** — часть правил применяется только к документу, заявляющему штатный профиль JasperReports/OpenPDF.
- **Novelty** — новый размер, hash, subset или SBP-профиль. Новизна сама по себе не является подделкой.
- **Cross-layer contradiction** — несовместимость двух слоёв одного документа, например `/W` не совпадает с `hmtx`, использованный CID отсутствует в ToUnicode или старый BaseFont-тег связан с другим FontFile2.

## 3. Точка входа и результат

Основная функция:

`detector/tbank_v6/engine.py::analyze(pdf_bytes, file_hash="", privileged_user=False)`

Алгоритм:

1. Если SHA-256 не передан, вычисляется SHA-256 всего PDF.
2. Вызывается `stages.run_pipeline`.
3. `verdict.compute_verdict` формирует бинарный вердикт.
4. `explain.build_expert_report` собирает техническое объяснение.

`privileged_user` не меняет решение. Он нужен внешнему интерфейсу, чтобы решить, показывать ли экспертные детали.

Формат результата:

```text
verdict: ЧИСТО | ФЕЙК
emoji: ✅ | 🔴
score: 0 | 60
flags: только решающие доказательства
details:
  file_hash
  validator_version = 6.5.5
  engine = tbank_v6
  channel
  receipt_subtype
  receipt_subtype_label
  completed_checks
  stats
  hard_count
  known_fake_count
  supporting_count
  ignored_observations
  analysis_complete
  expert_report
  user_message
```

## 4. Как документ признаётся квитанцией Т-Банка

Внутренний gate `_is_tbank_receipt` считает документ квитанцией, если выполняется хотя бы одно условие:

1. в PDF есть `/Subject` с `/reports/IB/Receipt`;
2. в извлечённом тексте присутствуют минимум два маркера из `Перевод`, `Квитанция`, `Итого`, `Статус`;
3. если текст не извлечён, в байтах найден `Receipt` либо UTF-8-последовательность `Перевод`.

Если семантическая стадия не подтверждает квитанцию, устанавливается `not_a_tbank_receipt`, а итогом становится:

`[NOT_TBANK_RECEIPT] файл не является квитанцией Т-Банка`.

До входа в `tbank_v6` общий маршрутизатор также использует банковские маркеры (`т-банк`, `тинькофф`, `tinkoff`, `tbank`, `tbank.ru`, `fb@tbank`) и сведения Producer/Creator.

### 4.1. Внешние слои до и после `tbank_v6`

Полный production-путь:

```text
PDF
→ detector.route
→ определение банка
→ global preflight
→ tbank_v6.engine.analyze
→ reputation.check в bot.py
→ status engine
→ нормализация и пользовательское объяснение
```

Global preflight может немедленно вернуть `ФЕЙК` до запуска T-Bank pipeline.
Полный `run_hardening_v2` для T-Bank не сливается с результатом: используется
именно global preflight и отдельный status engine.

После движка `bot.py` вызывает reputation-слой. Его score и flags добавляются к
результату; `known_fake` либо высокий reputation score может принудительно
сделать итог `ФЕЙК`. Этот слой не является частью `tbank_v6/rules.py`, поэтому
при отладке нужно отдельно сравнивать:

- прямой результат `tbank_v6.engine.analyze`;
- результат `detector.route`;
- окончательный результат после `reputation.check`.

## 5. Каналы и все поддерживаемые подметоды

### 5.1. Каналы, влияющие на проверки

В движке три канала:

- `sbp`;
- `phone`;
- `card`.

Решающий branching выполняет `_detect_v6_channel`.

Приоритет определения:

1. Любой маркер SBP ID:
   - `идентификатор операции`;
   - `id операции в сбп`;
   - `id операции сбп`;
   - `идентификатор операции в сбп`;
   - `номер операции в сбп`;
   - `сбп id`.
   Результат: `sbp`.
2. `клиенту т-банка` — канал `card`.
3. `по номеру карты`, `с карты на карту`, `перевод на карту` — `card`.
4. `на карту` вместе с `перевод` или `итого` — `card`.
5. `карта получателя` без `телефон получателя` — `card`.
6. `по номеру телефона` или `телефон получателя` — `phone`.
7. Fallback `corpus_profiles.detect_receipt_channel`.
8. Пустой или нераспознанный текст по умолчанию относится к `phone`.

### 5.2. Подметоды

`detect_receipt_subtype` формирует более детальную метку:

#### `sbp_phone`

UI: `СБП Т-Банк`.

Условия:

- канал `sbp`;
- нет явного маркера `по номеру карты`.

Дополнительные проверки:

- обязательное извлечение 32-символьного SBP ID;
- полная SBP-грамматика;
- связь timestamp внутри ID с напечатанной датой;
- route/control/class/profile;
- SBP epoch и receipt-stem;
- DEF и uniform-subscriber телефона, если телефон присутствует;
- SBP layout обычно соответствует высоте страницы 519 или 539 pt.

Строгая функция `_phone_format_flag` для SBP не вызывается: она ограничена
каналом `phone`. Формат SBP-телефона частично контролируется общим
`content_profile`.

#### `sbp_card`

UI: `СБП Т-Банк`.

Условия:

- канал `sbp`;
- одновременно найдено `по номеру карты`.

В текущем коде отдельного независимого валидатора для этого подтипа нет. Он
проходит общий SBP-стек. Проверки `TBANK_CARD_LAST4_*` из `content_profile`
ориентируются на определённый там канал и для обычного `sbp_card` не
включаются, потому что SBP-маркер имеет приоритет над карточной лексикой.

#### `intrabank_phone`

UI: `Чек Т-Банк, по телефону`.

Условия:

- нет SBP ID;
- нет карточных маркеров;
- обычный phone fallback.

Дополнительные проверки:

- формат телефона `+7 (XXX) XXX-XX-XX`;
- мобильный DEF должен начинаться на `9`;
- семизначная абонентская часть не должна состоять из одной повторяющейся цифры;
- типовые phone-shell высоты: 451, 471 или 473 pt.

SBP-грамматика для этого подметода не запускается.

#### `card_number`

UI: `Чек Т-Банк, по номеру карты`.

Условия:

- канал `card`;
- найдено `по номеру карты`;
- нет более приоритетного `клиенту т-банка`.

Дополнительные проверки:

- маска карты;
- последовательные last4 (`2345`, `4567` и подобные);
- нулевые шаблоны `0000`, BIN `200000` или `220000`;
- соответствие card-shell;
- минимальное количество composite glyph в F1 для высоты 471 pt.

#### `card_transfer`

UI: `Чек Т-Банк, на карту другого банка`.

Условия:

- канал `card`;
- `на карту` или карточный fallback;
- нет более точного подтипа.

Получает те же карточные проверки маски, shell, content layout и F1 subset shape.

#### `intrabank_client`

UI: `Чек Т-Банк, клиенту Т-Банка`.

Условия:

- `клиенту т-банка` или `клиенту т банка`.

Технический канал — `card`, но подтип хранится отдельно. Дополнительно используется точный диапазон decoded `/Contents` для известного shell height 431:

- 3129–3155 байт;
- выход за диапазон даёт `TBANK_CLIENT_CONTENT_SIZE_OUTLIER`.

### 5.3. Важное ограничение архитектуры подметодов

Подтип в основном используется для UI и статистики. Основные различия в реально запускаемых правилах определяются:

- каналом `sbp/phone/card`;
- текстовыми маркерами;
- высотой MediaBox;
- наличием конкретных полей.

Отдельных шести полностью изолированных pipeline нет.

### 5.4. Неподдерживаемые подметоды

В текущей таксономии нет отдельных веток для:

- QR-платежей;
- наличных;
- перевода по реквизитам/номеру счёта как отдельного подтипа;
- произвольного `other`.

`Счёт списания` является полем существующих чеков, а не самостоятельным
подметодом. Неизвестный формат обычно попадёт в fallback `phone`, а затем может
быть отклонён как не-квитанция или по несовместимости shell/полей.

## 6. Фактический порядок pipeline

Текущий pipeline шире старого «12 стадий». Фактический порядок:

1. `intake`;
2. `file_size`;
3. `fontfile2_size`;
4. `f1_subset_shape`;
5. `f2_subset_shape`;
6. `basefont_subset_cogen`;
7. `subset_orphan_residue`;
8. `f1_maxp_recomputed`;
9. `emitter_invariants`;
10. `glyph_spacing`;
11. `content_profile`;
12. `raw_preflight`;
13. `streams`;
14. `active_content`;
15. `content_ast`;
16. извлечение текста и metadata одним открытием PyMuPDF;
17. `layout_fingerprint`;
18. `fonts_cmap_glyph`;
19. `internal_serialization`;
20. `embedded_font_reassembly_forensics` внутри serialization;
21. `metadata_generation`;
22. `semantic_geometry`;
23. `differential_parity`;
24. `cross_document_intelligence`.

### 6.1. Early exit

Pipeline прекращает дорогие проверки, если уже найден HARD/KNOWN, документ не является квитанцией либо установлен cross-document conflict:

- после preflight;
- после streams + active content;
- после fonts;
- после internal serialization.

Семантика не может отменить уже найденный HARD.

## 7. Intake и технические отказы

### 7.1. Пустой файл

`analysis_complete=False`.

### 7.2. Ограничение размера

Максимум для анализа: `8_000_000` байт. Превышение означает незавершённый анализ и итоговый `ФЕЙК` через `ANALYSIS_NOT_COMPLETED`.

### 7.3. Шифрование

Если `/Encrypt` найден в первых 8000 байтах, анализ помечается незавершённым.

### 7.4. Зависимость от PyMuPDF

Если на parity-стадии отсутствует `fitz` или повторный parse завершается ошибкой, `analysis_complete=False`.

## 8. Предварительные size/subset/content-проверки

Эти модули выполняются до raw preflight.

### 8.1. Размер всего PDF

`tbank_v6/file_size.py`.

Ориентиры:

- корпус: 58 214–61 100 B;
- сильный диапазон: 52 000–62 000 B;
- soft: 55 000–62 500 B.

Важно: `TBANK_FILE_SIZE_STRONG_OUTLIER` находится в `IGNORED_CODES`. Даже если модуль создаёт tier A, policy отправляет его в diagnostics. Причина — размер является corpus novelty, а не самостоятельным доказательством.

### 8.2. Размеры FontFile2 по высоте страницы

`fontfile2_size.py`.

Извлекаются decoded-размеры F1/F2 и сравниваются с диапазонами по MediaBox:

- 411;
- 431;
- 451;
- 471;
- 473;
- 519;
- 539 pt.

Жёсткая проверка в модуле оставлена только для SBP shell height 519. Однако код `TBANK_FONTFILE2_SIZE_STRONG_OUTLIER` глобально демотирован в IGNORE, поэтому фактический verdict не меняет.

### 8.3. F1 subset shape

`f1_subset_shape.py`.

Проверяются:

- число simple/composite/nonempty glyph;
- cardinality ToUnicode;
- длина `glyf`;
- decoded FontFile2;
- соответствие `loca[-1]` концу `glyf`;
- card composite floor;
- envelope `glyf ↔ cmap` по высоте;
- exact corpus twins и FontFile2 hash — только telemetry.

Активные HARD:

- `TBANK_F1_GLYF_TRAILING_JUNK`;
- `TBANK_F1_COMPOSITE_FLOOR`;
- `TBANK_F1_GLYF_CMAP_OUTLIER`.

Намеренно ignored:

- неизвестная точная комбинация glyf/cmap;
- неизвестная cardinality;
- twin-shape;
- exact FF2 SHA.

### 8.4. F2 subset shape и совместная генерация F1/F2

`f2_subset_shape.py`.

Для F1 вычисляется анонимный hash мультимножества advance widths непустых glyph. Если этот известный F1 fingerprint в корпусе всегда связан с конкретными длинами F2 `glyf`, а документ содержит другую длину, возникает:

`TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH`.

Неизвестный F1 fingerprint не блокируется.

Exact whitelist F2 `glyf` по высоте — diagnostic.

### 8.5. BaseFont subset tag ↔ FontFile2

`basefont_subset_cogen.py`.

OpenPDF создаёт шестисимвольный subset-prefix вида `ABCDEF+TinkoffSans-Regular`. Для известных тегов атлас хранит SHA-16 соответствующего FontFile2.

Если известный тег остался от донора, а FontFile2 заменён:

`TBANK_BASEFONT_SUBSET_TAG_PAYLOAD_MISMATCH`.

Новый тег безопасен: отсутствие тега в атласе не является ошибкой.

### 8.6. Orphan residue и maxp recomputation

До early exit выполняются:

- `check_tbank_subset_orphan_residue`;
- `check_tbank_f1_maxp_recomputed_to_subset`.

Они ищут:

- непустые glyph, не представленные активным CMap/текстом;
- характерные остаточные пары;
- пересчитанные под subset поля `maxp`, тогда как штатный Jasper сохраняет envelope исходного шрифта;
- несогласованность `maxp`, `hhea`, `hmtx`, composite limits.

Ключевые HARD:

- `TBANK_FONT_SUBSET_ORPHAN_RESIDUE`;
- `TBANK_F1_MAXP_RECOMPUTED_TO_SUBSET`;
- `TBANK_F1_MAXP_COMPOSITE_ENVELOPE_MISMATCH`;
- `TBANK_F1_HHEA_ENVELOPE_MISMATCH`;
- `TBANK_F2_HEAD_ENVELOPE_MISMATCH`;
- `TBANK_F2_MAXP_ENVELOPE_MISMATCH`;
- `TBANK_F1_HMTX_ENVELOPE_MISMATCH`;
- `TBANK_F2_GLYF_LOCA_PADDING`;
- `TBANK_F2_GLYF_DIGIT_CARD_FAT`;
- `TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH`;
- `TBANK_F1_GLYF_SIZE_MULTISET_MISMATCH`.

### 8.7. Glyph ink spacing

Считается ink-gap соседних glyph:

`gap = advance(left) + xMin(right) - xMax(left)`.

Отрицательный gap означает наложение букв. Модуль создаёт `TBANK_GLYPH_INK_OVERLAP`, но этот код сейчас демотирован в IGNORE.

## 9. Jasper/OpenPDF emitter invariants

Модуль `tbank_v6/emitter_invariants.py` применяется только после profile gate.

Подтверждённый профиль требует:

1. Subject `/reports/IB/Receipt`;
2. Creator JasperReports 6.20.3;
3. Producer OpenPDF 1.3.30 Jaspersoft.

### 9.1. SFNT

Для F1/F2 ожидается порядок таблиц:

`cvt `, `fpgm`, `glyf`, `head`, `hhea`, `hmtx`, `loca`, `maxp`, `prep`.

Проверяются:

- нулевые contour stubs с непустым loca-span;
- нечётные offsets long-loca;
- точная cardinality `hmtx` из `numGlyphs` и `numberOfHMetrics`;
- composite glyph, ссылающиеся на пустые компоненты;
- отсутствие `beginbfchar` в ToUnicode: штатный emitter использует `beginbfrange`.

Активные коды:

- `TBANK_SFNT_TABLE_ORDER_MISMATCH`;
- `TBANK_GLYF_ZERO_CONTOUR_STUB`;
- `TBANK_LOCA_ODD_OFFSET`;
- `TBANK_HMTX_METRIC_CARDINALITY`;
- `TBANK_COMPOSITE_EMPTY_COMPONENT`;
- `TBANK_TOUNICODE_BFCHAR_PRESENT`.

### 9.2. PDF serializer

Запрещены:

- `/CIDSet`;
- `/FontMatrix`;
- `/MissingWidth`;
- `/XHeight`;
- `/AvgWidth`;
- `/Leading`;
- `/FontWeight`;
- `/ProcSet`;
- stream `/Predictor`;
- CRLF сразу после `stream`;
- оператор `TJ`;
- marked content `BMC/BDC/EMC`;
- вложенные или некорректно сбалансированные `BT/ET`.

## 10. Raw PDF preflight

### 10.1. Структура

`validate_pdf_structure` проверяет:

- PDF header;
- trailer;
- xref;
- object boundaries;
- ссылки;
- EOF;
- лишние байты после EOF;
- несколько headers/xref/startxref/EOF;
- дубли активных объектов.

### 10.2. Incremental updates

Проверяются `/Prev`, повторные trailer/xref и переопределения объектов. Активные структурные противоречия являются HARD.

### 10.3. Xref

Каждый используемый offset должен вести к правильному объекту.

## 11. Потоки и активное содержимое

### 11.1. Stream compression

HARD:

- `STREAM_DECOMPRESSION_FAILED`;
- `STREAM_LENGTH_MISMATCH`.

Supporting:

- `STREAM_COMPRESSION_RATIO_OUTLIER`;
- `DECODED_STREAM_SIZE_OUTLIER`;
- `STREAM_FILTER_ANOMALY`.

### 11.2. Active content

HARD:

- JavaScript;
- OpenAction;
- dangerous actions;
- embedded files/payloads;
- AcroForm;
- XFA.

Банковская квитанция рассматривается как статический документ.

## 12. Content stream

### 12.1. Базовая AST-проверка

- количество `BT` должно совпадать с `ET`;
- известный generator skeleton блокируется;
- padding-комментарии `%...` длиннее 12 байт блокируются;
- whitespace-tail после последнего `ET` более 8 байт блокируется;
- footer-padding после `2 J` более 2 байт блокируется.

### 12.2. Profile по MediaBox

Для известных высот заданы ожидаемые `BT/Tm`:

- 411 → 20/19;
- 431 → 22/21;
- 451 → 24/23;
- 471 → 26/25;
- 473 → 26/26;
- 519 → 30/31;
- 539 → 32/33.

Несовпадение даёт `TBANK_CONTENT_BT_TM_PROFILE`.

Exact content length и exact skeleton существуют как telemetry, но их неизвестность демотирована.

### 12.3. Низкоуровневая сериализация

Активно проверяются:

- длинная возрастающая CID-лестница внутри одного `Tj`;
- пробел или пустая строка перед `ET`;
- отступы перед numeric operands;
- пробелы после `Tj`;
- лишний trailing zero в float (`187.10` вместо `187.1`);
- слишком много `Td` после `Tm`;
- `Tj/TJ` между парой `Td`;
- sentinel `-500 -500 Td`;
- связь image `cm.a` с парой `±a 0 Td`;
- режимы `Tr`: ожидается ровно `[2, 0]`;
- ведущие/хвостовые пробелы в именах и суммах;
- сумма с ведущим нулём;
- канал на shell-height другого канала;
- точная строка поддержки;
- повреждённый статический label телефона.

### 12.4. Shell heights по каналам

- card: 411, 431, 471;
- phone: 451, 471, 473;
- sbp: 519, 539.

Неизвестная новая высота не блокируется. Блокируется известная высота чужого канала.

## 13. Layout и геометрия

### 13.1. Layout fingerprint

`tbank_text_layout_fingerprint.py` сопоставляет raw PDF coordinates/CID widths с PyMuPDF.

- подтверждённое межслойное противоречие может быть HARD;
- более слабое отклонение — `TBANK_TEXT_LAYOUT_FINGERPRINT`, tier B;
- diagnostics сохраняются отдельно.

### 13.2. Правый край значений

`field_edge_alignment.check_tbank_value_right_edge` проверяет относительную вертикаль правой колонки:

- spread между значениями;
- overshoot;
- off-lattice размещение.

Проверяется внутренняя согласованность одного документа, а не только абсолютная координата.

### 13.3. SBP geometry

Старый абсолютный pin правого края SBP ID около 250 pt сохранён как diagnostic: `TBANK_SBP_GEOMETRY_MISMATCH` находится в IGNORE из-за parser/rounding false positives.

## 14. Шрифтовый стек

Типовые роли:

- F1 — TinkoffSans-Regular;
- F2 — TinkoffSans-Medium;
- F3 — ALSRubl.

Проверочная цепочка:

```text
Tj CID
→ ToUnicode
→ /W
→ CID/GID
→ loca/glyf
→ hmtx
→ FontBBox/head bbox
→ rendered text/geometry
```

Проверяются:

- присутствие всех использованных CID в CMap;
- присутствие widths;
- соответствие PDF widths и TTF advances;
- валидность CMap;
- наличие FontFile2;
- loca и glyf;
- пустые используемые glyph;
- outline/slot transplant;
- table checksums;
- `checkSumAdjustment`;
- число метрик;
- glyph-render parity;
- F3/ALSRubl;
- exact subset closure.

`run_pdf_forensics` содержит больше наблюдений, чем реально решает verdict. HIGH-флаг становится HARD только если он включён в явный whitelist стадии либо отдельно повышен для OpenPDF.

OpenPDF-специальные HARD:

- `UNUSED_CID_PRESENT`;
- `CMAP_EXTRA_SYMBOLS`.

Позиционные HARD:

- `FIELD_POSITION_OUT_OF_PROFILE`;
- `TM_NOT_RECALCULATED`.

## 15. Internal serialization stack

Порядок внутри `_stage_internal_serialization`:

1. Deflate profile;
2. stream integrity;
3. font CID closure;
4. font table integrity;
5. F1 orphan simple glyph;
6. SFNT table inventory;
7. `.notdef` integrity;
8. reassembly family v3;
9. serializer families v1;
10. used glyph integrity;
11. glyph slot transplant;
12. glyph atlas;
13. reassembled bank assets;
14. embedded font reassembly;
15. receipt number;
16. trailer ID reuse.

### 15.1. Deflate

Штатные потоки сравниваются с canonical Java Deflater. Смешение разных serializer provenance и несовместимый page-content Deflate дают HARD.

### 15.2. Stream integrity

Проверяются границы Flate member, `/Length`, неоднозначные members и соответствие ранее собранным stream profiles.

### 15.3. Exact font closure

Reassembly v3 проверяет:

- минимальность CMap;
- минимальность `/W`;
- `/W ↔ hmtx`;
- bijection CID serialization;
- точное замыкание subset.

Коды:

- `TBANK_SUBSET_CMAP_NOT_MINIMAL`;
- `TBANK_W_ARRAY_NOT_MINIMAL`;
- `TBANK_W_TTF_ADVANCE_MISMATCH`;
- `TBANK_CID_SERIALIZATION_BIJECTION_VIOLATION`;
- `TBANK_FONT_SUBSET_EXACT_CLOSURE`.

### 15.4. Serializer families v1

Подтверждённые сочетания структурных признаков дают KNOWN:

- `TBANK_KNOWN_FAKE_SBP_SERIALIZER_V1`;
- `TBANK_KNOWN_FAKE_CARD_TBANK_SERIALIZER_V1`;
- `TBANK_KNOWN_FAKE_NOCOMM_SERIALIZER_V1`.

Проверка построена как conjunction нескольких признаков, а не как запрет одного нового hash.

### 15.5. Reassembled assets

`TBANK_REASSEMBLED_BANK_ASSETS`, V2 и V3 требуют одновременной согласованной картины пересборки: штатные статические ресурсы плюс чужая динамическая сборка content/CMap/W/F1/F2.

### 15.6. Embedded font reassembly

Сравниваются:

- F1/F2/F3 lifecycle;
- `head.created/modified`;
- table order и padding;
- `glyf/loca`;
- structural fingerprint;
- совместная генерация F1/F2;
- статичность F3;
- заявленный Jasper shell.

KNOWN-коды:

- `TBANK_REBUILD_FONT_DUAL_DYNAMIC_001`;
- `TBANK_REBUILD_STATIC_F3_DYNAMIC_F12_SPLIT_002`;
- `TBANK_REBUILD_GLYPH_PAYLOAD_WITH_FROZEN_HEAD_003`;
- `TBANK_REBUILD_F1_F2_COGENERATION_004`;
- `TBANK_REBUILD_CANONICAL_SHELL_FOREIGN_SUBSETTER_005`;
- `TBANK_REASSEMBLY_FAMILY_V3`.

### 15.7. Номер квитанции

Штатная форма:

`1-NNN-NNN-NNN-NNN`.

Лишний текст/CID после номера отдельно ловится `TBANK_RECEIPT_ID_TRAILING_JUNK`.

### 15.8. Trailer ID

SQLite-проверка сопоставляет trailer `/ID` с content hash, номером квитанции, operation ID и датой.

Текущая политика:

`TBANK_TRAILER_ID_REUSED` — IGNORE.

Причина: повтор trailer ID наблюдался и на подтверждённых оригиналах, поэтому это provenance telemetry, а не доказательство подделки.

## 16. Metadata

### 16.1. Producer/Creator

Для текста квитанции Т-Банка ожидается JasperReports/OpenPDF/Jaspersoft. Чужой engine (Chromium, PDFium, ReportLab и подобные) даёт:

- `TBANK_FOREIGN_PRODUCER`;
- либо `FOREIGN_PRODUCER`.

### 16.2. `/Keywords` lexical form

Jasper/OpenPDF пишет `/Keywords(` без нестандартного разделителя. Нарушение:

`TBANK_INFO_KEYWORDS_LEX_MISMATCH`.

### 16.3. Переход поколения Keywords

Третий token `/Keywords`:

- до 10.07.2026 — `991`;
- с 10.07.2026 — `DOCS-2035`.

Для выбора поколения используется напечатанная дата чека, переданная в `check_keywords_generation`; CreationDate служит дополнительным источником.

Несоответствие эпохе:

`TBANK_KEYWORDS_GENERATION_MISMATCH`.

Правило применяется только к `/reports/IB/Receipt`.

## 17. Общая семантика полей

Для всех каналов:

- невидимые bidi/zero-width/NUL символы;
- латинские homoglyph в статических русских label;
- U+FFFD и необработанные `(cid:...)`;
- C1 controls;
- нештатная запись денежного значения;
- мусор после номера квитанции;
- префикс счёта списания;
- точная строка поддержки;
- leading/trailing whitespace;
- нулевые секунды;
- повреждённые статические labels.

### 17.1. Счёт списания

Если найден `Счёт списания`, ожидается префикс `40817`.

Другой префикс:

`TBANK_DEBIT_ACCOUNT_PREFIX`.

Это проверка типа счёта, а не полной банковской контрольной суммы.

### 17.2. Телефон

Для phone-канала ожидается:

`+7 (XXX) XXX-XX-XX`.

В content-profile дополнительно проверяются мобильный DEF и uniform subscriber.

### 17.3. Карта

Проверяется маска из BIN6 и last4. Полный PAN не восстанавливается и не валидируется.

### 17.4. Что присутствует в каталоге правил, но не вызывается

Коды `AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS`, `FIELD_ORDER_MISMATCH`,
`FIELD_SET_MISMATCH` и часть старого layout-контракта остаются в
`HARD_CODES`, однако полный `tbank_spec.run_tbank_spec_checks` текущим
pipeline не вызывается.

В частности, строгая арифметика `Итого = Сумма + Комиссия` в актуальном
`tbank_v6` отдельно не выполняется. Активны формат/сериализация суммы,
leading-zero/whitespace и FontFile2 `.notdef`-проверка amount operand.
Наличие кода в `HARD_CODES` не означает, что в текущем execution path существует
эмиттер этого кода.

## 18. Полная проверка SBP ID

SBP-стек запускается только при `channel == sbp`.

### 18.1. Извлечение

Приоритет:

1. геометрическое чтение value lines через PyMuPDF;
2. content-stream SBP block;
3. фрагменты рядом с label;
4. общий text extractor.

Это позволяет собрать ID, разбитый на несколько PDF text fragments.

### 18.2. Формат 32 символов

Разметка T-Банка:

```text
[0]      lead A/B
[1:5]    year digit + UTC day-of-year
[5:11]   UTC HHMMSS
[11:14]  ref3
[14]     route_marker
[15]     control
[16]     separator, ожидается 0
[17:19]  class: 00/B0/B1/G1
[19:22]  slot
[22:26]  profile block 0011
[22:27]  bank5
[26:32]  suffix
```

### 18.3. Активные проверки

- ID присутствует;
- длина и alphabet;
- валидная календарная дата;
- UTC time;
- связь с напечатанным московским временем;
- separator;
- class;
- route field;
- control triple;
- cross-class conflict;
- слишком ранняя epoch;
- известная malicious grammar combination.

### 18.4. Текущие уровни

HARD:

- `SBP_CIPHER_MISSING`;
- `SBP_CIPHER_STRUCTURE`;
- `SBP_CIPHER_TIMESTAMP`;
- `SBP_CIPHER_REFERENCE`;
- `SBP_ROUTE_FIELD_CONTAMINATION`;
- `SBP_CONTROL_TRIPLE_MISMATCH`;
- `SBP_LINKED_TUPLE_CROSS_CLASS`;
- `SBP_PROFILE_EPOCH_TOO_EARLY`.

KNOWN:

- `KNOWN_FAKE_SBP_GRAMMAR_COMBINATION`.

Supporting:

- `SBP_TBANK_BANK5_MISMATCH`;
- `SBP_PROFILE_EMPIRICAL`;
- `SBP_PROFILE_EPOCH_MISMATCH`;
- `RECEIPT_STEM_REUSE_CONFLICT`.

Ignored:

- `SBP_LINKED_TUPLE_CONFLICT`;
- `SBP_GRAMMAR_SUFFIX_PROFILE`;
- абсолютная `TBANK_SBP_GEOMETRY_MISMATCH`.

Unknown tuple не должен автоматически считаться подделкой.

## 19. Anti-edit и cross-document

`anti_edit.run_checks(bank_key="tbank")` получает:

- PDF bytes;
- извлечённый текст;
- decoded content length;
- CreationDate/ModDate;
- SHA-256.

Результаты:

- `OPERATION_ID_REUSED` — HARD и `cross_document_identity_conflict=True`;
- `RECEIPT_TEXT_LAYER_MISSING` — HARD;
- `PDF_MODDATE_EDITED` — tier B;
- остальные наблюдения — IGNORE.

Отдельная trailer-ID база сейчас не решает verdict.

## 20. Differential parity

Документ повторно читается PyMuPDF. Сравниваются SBP ID из основного текста и повторного parse.

Если оба ID найдены и различаются:

`TEXT_LAYER_INCONSISTENT`.

Это защита от двух несовпадающих текстовых представлений одного PDF.

## 21. Правила вердикта

Строгий порядок:

1. `analysis_complete=False` → `ФЕЙК`, score 60.
2. `not_a_tbank_receipt=True` → `ФЕЙК`, score 60.
3. Есть KNOWN или HARD → `ФЕЙК`, score 60.
4. Есть минимум две различные supporting-группы → `ФЕЙК`, score 60.
5. Есть cross-document identity conflict → `ФЕЙК`, score 60.
6. Иначе → `ЧИСТО`, score 0.

Один tier-B флаг всегда недостаточен.

### 21.1. Supporting-группы

- `B6_metadata_version`;
- `B1_serializer_container`;
- `B5_source_fonts`;
- `B5_font_rebuilder`;
- `content_grammar_layout`;
- `content_grammar_sbp`;
- `content_grammar_sbp_epoch`;
- `cross_document_receipt_stem`.

Два флага одной группы считаются одним источником доказательств.

### 21.2. Приоритет policy над tier модуля

`ingest_flag` сначала проверяет `IGNORED_CODES`. Поэтому код, записанный модулем как tier A, не влияет на решение, если он глобально демотирован.

Это относится, в частности, к:

- file-size novelty;
- FontFile2 size novelty;
- exact content/font atlases;
- F1 twin shape;
- glyph ink overlap;
- trailer ID reuse;
- SBP linked tuple conflict;
- SBP absolute geometry.

## 22. KNOWN-сигнатуры

Активные:

- `K-FONT-001`;
- `KNOWN_FAKE_SBP_GRAMMAR_COMBINATION`;
- `TBANK_REASSEMBLED_BANK_ASSETS`;
- `TBANK_REASSEMBLED_BANK_ASSETS_V2`;
- пять `TBANK_REBUILD_*`;
- `TBANK_REASSEMBLY_FAMILY_V3`;
- три `TBANK_KNOWN_FAKE_*_SERIALIZER_V1`.

`K-FONT-002` отключён. Функция сохранена как no-op для стабильности call sites. Причина: blacklist пары `glyf/loca` оказался проверкой новизны/клонирования, а не надёжным структурным доказательством.

## 23. Что намеренно не считается подделкой само по себе

- новый SHA всего PDF;
- новый FontFile2 SHA;
- новый subset prefix;
- новый content hash;
- новый trailer ID;
- новый корректный SBP tuple;
- неизвестный suffix;
- новый MediaBox height;
- новый operator skeleton;
- новый exact content length;
- размер файла вне старого корпуса;
- размер FontFile2 вне старого корпуса;
- неизвестный glyph atlas entry;
- FIO, которое просто выглядит необычно;
- один supporting-флаг;
- повтор trailer ID без доказанного конфликта операции.

## 24. Что реально различается между подметодами

```text
Общие для всех:
container, xref, streams, active content, metadata, producer,
content serializer, F1/F2/F3, CMap/W/glyf/hmtx, anti-edit, support line.

SBP:
+ 32-char SBP ID, timestamp, grammar, route/control/class/profile,
  epoch/stem, SBP-specific shell 519/539.

Phone без SBP:
+ phone format, mobile DEF, uniform subscriber,
  phone shell 451/471/473.

Card / на карту / клиенту Т-Банка:
+ card mask, last4/null template, card shell 411/431/471,
  F1 composite floor at 471.

Клиенту Т-Банка:
+ exact client content envelope at height 431.
```

## 25. Основные файлы

- `detector/tbank_v6/engine.py` — entry/result.
- `detector/tbank_v6/stages.py` — orchestration и channel-specific logic.
- `detector/tbank_v6/rules.py` — итоговая классификация кодов.
- `detector/tbank_v6/verdict.py` — вычисление решения.
- `detector/corpus_profiles.py` — каналы и подтипы.
- `detector/tbank_sbp_content.py` — SBP grammar.
- `detector/tbank_sbp_epoch_reuse.py` — epoch/stem.
- `detector/tbank_reassembly_family_v3.py` — exact subset closure/reassembly.
- `detector/tbank_serializer_families_v1.py` — подтверждённые serializer families.
- `detector/embedded_font_reassembly.py` — font lifecycle/reassembly.
- `detector/pdf_forensics.py` — общий font/CMap/content forensic layer.
- `detector/structure.py` — PDF structure, streams, active content.
- `detector/anti_edit.py` — operation reuse и edit traces.
- `detector/tbank_keywords_generation.py` — `991 → DOCS-2035`.
- `detector/__init__.py` и `detector/profiles.py` — внешний routing/global preflight.
- `bot.py` и `detector/reputation.py` — post-engine reputation и итоговый UI.

## 26. Active и legacy

Активны:

- `detector/tbank_v6/*`;
- перечисленные shared-модули `structure`, `pdf_forensics`, `anti_edit`,
  `tbank_sbp_*`, reassembly и serializer families;
- `tbank_spec.check_foreign_producer` как точечно импортированная функция.

Не участвуют как самостоятельный decision engine:

- `tbank_legacy.py`;
- `policy_v5.py`;
- полный `tbank_spec.run_tbank_spec_checks`;
- `tbank_template_profile.py`;
- legacy font-render/template scoring.

Некоторые helper-функции legacy/corpus-модулей могут импортироваться точечно.
Это не означает включение всего старого движка.

## 27. Практическая интерпретация

`ЧИСТО` означает: активные проверки не нашли достаточного набора доказательств подделки. Это не криптографическое подтверждение операции в банковском backend.

`ФЕЙК` означает одно из трёх:

1. найдено самостоятельное структурное/семантическое противоречие;
2. найдено подтверждённое семейство генератора;
3. совпали минимум две независимые supporting-группы.

Для изменения поведения необходимо менять не только emitter-модуль, но и `rules.py`: окончательное решение о tier принимает policy.

