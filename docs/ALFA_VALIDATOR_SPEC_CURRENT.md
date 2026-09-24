# Альфа-Банк: полная спецификация проверки PDF-квитанций

**Состояние кода:** 19.08.2026  
**Движок:** `detector.alfa_v2`  
**Версия:** `2.1.2`  
**Режим:** `full`

## 1. Назначение

Документ описывает фактическую проверку квитанций Альфа-Банка:

- маршрутизацию;
- три поддерживаемых метода;
- Oracle BI и Quartz/iOS профили;
- PDF-контейнер, streams, content, assets и шрифты;
- семантику полей и идентификаторов;
- SBP ID;
- cross-document базы;
- известные сигнатуры;
- HARD, KNOWN, supporting, manual и ignored policy;
- итоговые вердикты `ЧИСТО`, `ФЕЙК`, `НЕИЗВЕСТНЫЙ ДОКУМЕНТ`.

Код является источником истины. Наличие названия флага в `rules.py` ещё не
гарантирует, что его emitter вызывается для каждого метода.

## 2. Полный production-путь

```text
PDF bytes
→ detector.route
→ profiles.identify: Alfa
→ global preflight
→ detector.alfa / alfa_v2.engine.analyze
→ alfa_v2.stages.run_pipeline
→ alfa_v2.verdict.compute_verdict
→ внешний reputation/status/UI слой
```

Global preflight может отклонить опасный/повреждённый PDF до `alfa_v2`.
Reputation-слой бота может дополнить результат после движка. Для диагностики
следует различать прямой `alfa_v2.engine.analyze` и окончательный ответ бота.

## 3. Точка входа и формат результата

`detector/alfa_v2/engine.py::analyze(pdf_bytes, file_hash="", privileged_user=False)`

Порядок:

1. SHA-256 всего файла;
2. `run_pipeline`;
3. `compute_verdict`;
4. `build_expert_report`;
5. формирование общего ответа.

Основные поля:

```text
verdict: ЧИСТО | ФЕЙК | НЕИЗВЕСТНЫЙ ДОКУМЕНТ
emoji: ✅ | 🔴 | ⚪
score: 0 | 60
details:
  validator_version = 2.1.2
  engine = alfa_v2
  rollout_mode = full
  channel
  receipt_subtype
  generator_path
  completed_checks
  stats
  hard_flags
  known_fake_flags
  supporting_groups
  ignored_observations
  manual_review_required
  cross_document_identity_conflict
  expert_report
```

`privileged_user` не меняет verdict. Он добавляет расширенную evidence policy.

## 4. Как PDF признаётся квитанцией Альфа-Банка

`_is_alfa_receipt` использует:

- `квитанция о переводе`;
- `альфа-банк` / `alfa-bank`;
- `сформирована`;
- Producer `Oracle BI Publisher`;
- Producer `Quartz PDFContext`;
- поля `СБП`, `Номер операции`;
- 16-символьный operation ID;
- trailer `/ID` как последний fallback для узнаваемого Oracle/Quartz shell.

Обычный текстовый путь требует минимум два Alfa-маркера. Для Oracle/Quartz
допускается повреждение части текста: shell и оставшиеся поля могут подтвердить
банк.

Если документ не распознан:

`[NOT_ALFA_RECEIPT] файл не является квитанцией Альфа-Банка` → `ФЕЙК`.

## 5. Генераторные пути

### 5.1. `oracle_bi`

Обычно:

- Producer `Oracle BI Publisher 12.2.1.4.0`;
- PDF 1.6;
- около 16 объектов;
- один Tahoma subset;
- характерный resource graph;
- Java Deflater-потоки;
- Oracle-специфичная content/ToUnicode/font сборка.

### 5.2. `quartz_ios`

Обычно:

- Producer `iOS Version ... Quartz PDFContext`;
- PDF 1.3;
- около 18 объектов;
- ICCBased profile;
- Quartz resource naming (`font000000`, `/G1` и подобное);
- собственная stream/font lifecycle.

### 5.3. `unknown`

Если Producer не определён, проверки всё равно продолжаются. Несогласованные
слои могут дать HARD или несколько tier-B. Сам неизвестный producer/profile
не всегда является фейком.

### 5.4. Межслойное определение emitter

`EmitterEvidence` сравнивает:

- Producer;
- PDF version;
- object count;
- object graph;
- resource naming;
- ICC profile.

Если разные слои одновременно заявляют Oracle и Quartz:

`ALFA_PROFILE_CROSS_LAYER_CONFLICT`.

## 6. Все поддерживаемые методы

В активном `alfa_v2` три метода:

- `sbp`;
- `card`;
- `phone`.

QR, наличные и отдельный перевод по реквизитам счёта не имеют самостоятельных
подметодов.

## 7. Классификация метода

`profile_semantics.classify_submethod` сначала собирает evidence по каждому
методу.

Если доказан один метод — выбирается он. Если доказано несколько:

1. title имеет высший приоритет;
2. затем порядок `sbp`, `card`, `phone`.

Телефон получателя сам по себе не доказывает `phone`: он обычен на SBP-чеке.

### 7.1. `sbp`

Основные доказательства:

- заголовок квитанции о переводе по СБП;
- `Идентификатор операции в СБП`;
- характерный SBP field family.

UI: `СБП Альфа-Банк`.

### 7.2. `card`

Доказательства:

- карточный title;
- `Номер карты отправителя`;
- `Номер карты получателя`;
- interbank-поля `Код авторизации`, `Код/номер терминала`.

UI: `Альфа-Банк, с карты на карту`.

### 7.3. `phone`

Надёжный marker:

`Квитанция о переводе клиенту Альфа-Банка`.

UI: `Альфа-Банк, клиенту по телефону`.

Телефон без этого title не должен перетянуть SBP в phone.

### 7.4. `unknown`

Если метод не доказан, channel/subtype=`unknown`. Общие forensic-проверки
сохраняются, но method-specific field contract ограничен общими полями.

## 8. Field contract по методам

Общие обязательные группы:

- `Сумма перевода`;
- `Комиссия`;
- `Дата и время перевода`;
- `Номер операции`.

### 8.1. SBP

Дополнительно требуются:

- `Получатель`;
- `Телефон/номер телефона получателя`;
- `Банк получателя`;
- `Идентификатор операции в СБП`.

Если комиссия больше нуля, требуется:

- `Списано с учетом комиссии` либо `Списано с учётом комиссии`.

### 8.2. Card

Дополнительно:

- `Номер карты отправителя`;
- `Номер карты получателя`.

Для межбанковской карты:

- `Код авторизации`;
- `Код терминала` или `Номер терминала`.

### 8.3. Phone

Дополнительно:

- `Получатель`;
- `Телефон/номер телефона получателя`.

Запрещены SBP/interbank-поля:

- `Банк получателя` / `Банк отправителя`;
- `Идентификатор операции в СБП`.

### 8.4. Реакция на field contract

Смешение доказанных семей:

`ALFA_FIELD_SET_METHOD_CONFLICT` — HARD.

Missing/forbidden fields:

`ALFA_FIELD_CONTRACT_MISMATCH` создаётся emitter с `tier=B`, но код отсутствует
в `SUPPORTING_GROUPS`. `ingest_flag` сначала получает для него классификацию
`IGNORE`, поэтому фактически это только `ignored_observations` и на verdict не
влияет.

## 9. Фактический pipeline

Порядок `run_pipeline`:

1. `intake`;
2. `container`;
3. `streams_active`;
4. PyMuPDF text + metadata;
5. проверка принадлежности Альфа-Банку;
6. exact known-file SHA;
7. emitter evidence и method classification;
8. `file_size`;
9. `profile_semantics`;
10. SBP semantic validator для метода `sbp`;
11. `serializer_assets`;
12. `shell_clone`;
13. `content_fonts`;
14. `embedded_font_reassembly_forensics`;
15. `cross_document_identity`;
16. `new_sbp_profile`;
17. Quartz composite novelty/manual;
18. `complete`.

В отличие от T-Bank, здесь нет нескольких `_has_decisive` early exit. Большая
часть стадий выполняется даже после найденного флага, чтобы собрать полный
отчёт. Немедленные возвраты:

- intake error;
- ошибка/отсутствие PyMuPDF;
- файл не признан Alfa.

Весь pipeline обёрнут логикой модулей; ошибка embedded font analysis может
установить `analysis_complete=False`.

## 10. Intake

- пустой файл → incomplete;
- размер больше 8 000 000 B → incomplete;
- SHA-256 вычисляется до pipeline.

`analysis_complete=False` всегда превращается в `ФЕЙК`.

## 11. Container и active content

Shared `structure.py` проверяет:

- PDF header;
- trailer;
- xref offsets;
- object graph;
- несколько headers/startxref/xref/EOF;
- `/Prev` и incremental updates;
- дубли объектов;
- trailing bytes;
- stream decompression и `/Length`;
- неожиданные filters;
- JavaScript/OpenAction;
- embedded files;
- AcroForm/XFA.

Структурные нарушения и active content относятся к HARD.

## 12. Размер файла

`alfa_v2/file_size.py` использует отдельные профили Oracle и Quartz.

```text
quartz_ios: atlas 69706–71632 B; strong 67500–73000 B
oracle_bi:  atlas 55326–59087 B; strong 53000–59087 B
```

Активные HARD:

- `ALFA_FILE_SIZE_UNDERSIZE`;
- `ALFA_FILE_SIZE_STRONG_OUTLIER`.

Сильный outlier привязан к подтверждённому emitter/profile, а не к одному
глобальному размеру.

## 13. Семантика operation ID

Ищется ID формата:

`[A-Z]\d{15}` — ровно 16 символов.

Проверки:

- наличие;
- длина и структура;
- позиции `[3:9]` должны равняться видимой дате `DDMMYY`;
- семейство первой буквы/кода не прибивается к одному allowlist;
- literal embedding видимого времени после `C16`.

Если ID вообще не найден, создаётся `ALFA_OPERATION_ID_STRUCTURE`, но этот код
не включён ни в HARD, ни в supporting policy и фактически игнорируется.

HARD:

- `ALFA_OPERATION_NUMBER_FORMAT`;
- `ALFA_OPERATION_DATE_LINK_MISMATCH`.

KNOWN:

- `ALFA_KNOWN_GENERATOR_OPERATION_TIME_EMBEDDING`, если ID содержит
  `C16+DDMMYY+HHMMSS+digit`.

Если одновременно Oracle shell имеет 0/6 canonical Java streams и synthetic
operation time embedding:

`ALFA_KNOWN_GENERATOR_FULL_RESERIALIZATION`.

## 14. Field-value binding

Только SBP.

Проверяется, что сразу после label расположен value ожидаемого типа:

- `Списано с учетом комиссии` → денежная сумма;
- `Дата и время перевода` → дата/время;
- `Номер операции` → 16-символьный ID.

Одна ошибка недостаточна. Две и более:

`ALFA_FIELD_VALUE_BINDING_CONFLICT` — HARD.

Это ловит сдвиг строк шаблона, а не странное содержание ФИО.

## 15. Суммы и комиссия

`parse_amounts` извлекает amount, fee и debit-with-fee.

Проверки:

- арифметика amount + fee;
- соответствие `Списано с учетом комиссии`;
- денежная типографика;
- десятичные разделители;
- `RUR`;
- NBSP;
- асимметрия trailing NBSP между amount и fee.

HARD:

- `ALFA_AMOUNT_ARITHMETIC_MISMATCH`;
- `ALFA_AMOUNT_TYPOGRAPHY_ANOMALY`;
- `ALFA_RUR_TRAILING_NBSP_ASYMMETRY`.

## 16. Card-specific semantics

Проверяются:

- BIN отправителя и получателя;
- маска карты;
- last4;
- повторяющийся ABAB-паттерн;
- interbank authorization/terminal fields;
- соответствие набора полей методу.

Активный v2 BIN-контракт узкий: карта должна попадать в диапазон МИР
`220000–220499`. Более широкий legacy-список BIN из старых модулей здесь не
используется. Last4 вида `6161`, `5050` и аналогичный ABAB считается
синтетическим паттерном.

HARD:

- `ALFA_CARD_BIN_INVALID`;
- `ALFA_CARD_LAST4_ABAB`;
- `ALFA_FIELD_SET_METHOD_CONFLICT`.

## 17. Phone/SBP field artifacts

Активные проверки:

- recipient phone DEF должен быть мобильным;
- masked phone DEF;
- phone-receipt recipient initials;
- для phone-метода имя не должно быть полностью раскрыто там, где шаблон
  ожидает маскирование;
- debit account не должен быть пустым;
- sequential/periodic account-паттерны;
- content whitespace/ET;
- FIO alphabet/consonant runs сохраняются только как diagnostics.

HARD:

- `ALFA_PHONE_DEF_NOT_MOBILE`;
- `ALFA_MASKED_PHONE_DEF_NOT_MOBILE`;
- `ALFA_PHONE_RECIPIENT_INITIALS`;
- `ALFA_PHONE_NAME_UNMASKED`;
- `ALFA_DEBIT_ACCOUNT_SEQUENTIAL`;
- `ALFA_DEBIT_ACCOUNT_PERIODIC`;
- `ALFA_DEBIT_ACCOUNT_EMPTY`;
- `ALFA_CONTENT_ET_WHITESPACE_ANOMALY`.

## 18. SBP ID Альфа-Банка

SBP validator запускается только для метода `sbp`.

### 18.1. Каноническая разметка

```text
[0]      type
[1:5]    year/day
[5:7]    UTC hour
[7:9]    minute
[9:11]   second
[11:17]  reference
[17]     control
[18:22]  channel
[22:27]  core
[27:32]  tail
```

Overlapping T-Bank slicing `[14]`, `[17:19]`, `[26:32]` к Альфа-ID не
применяется.

### 18.2. HARD

- `ALFA_SBP_ID_STRUCTURE_INVALID`;
- `ALFA_SBP_ID_CALENDAR_CONFLICT`;
- `ALFA_SBP_ID_TIME_ORDER_CONFLICT`.

Проверяется:

- 32 символа;
- alphabet;
- календарный год/day-of-year;
- embedded UTC time;
- допустимый порядок относительно видимой операции.

### 18.3. Supporting

- `ALFA_SBP_EMPIRICAL_PROFILE` (только unknown marker/control; unknown channel/core/tail/combination — IGNORE `ALFA_SBP_PROFILE_NOVELTY`);
- `ALFA_SBP_TAIL_UNKNOWN`;
- `ALFA_SBP_SEPARATOR_DIGIT`.

Один эмпирический новый профиль не блокируется.

### 18.4. Ignored

- `ALFA_SBP_ATLAS_LINK_MISMATCH`;
- `ALFA_SBP_LINKED_TUPLE_CONFLICT`.

Причина: старый linked-tuple parser использовал чужую T-Bank-разметку.

## 19. New SBP profile

`unconfirmed_profiles.check_new_sbp_profile` наблюдает новые пары core/tail.

`ALFA_NEW_SBP_PROFILE_OBSERVED`:

- сохраняется в observations;
- не меняет verdict;
- не является whitelist-баном.

## 20. Stream provenance

`streams.check_streams`:

- определяет Oracle/Quartz serializer;
- декомпрессирует все Flate streams;
- сравнивает с canonical zlib/Java output;
- ищет смешение serializer;
- анализирует stream roles и sizes.

Для exact Oracle BI ожидаются шесть Flate streams и byte-identical результат
Java Deflater level 6:

- 6/6 canonical → serializer stage завершается без provenance-флагов;
- 0/6 canonical → full provenance mismatch;
- смесь canonical/foreign → mixed provenance.

HARD:

- `ALFA_MIXED_SERIALIZER_PROVENANCE`;
- `ALFA_MIXED_ZLIB_SERIALIZER_PROVENANCE`;
- `ALFA_ORACLE_FULL_DEFLATE_PROVENANCE_MISMATCH`.

Supporting:

- `ALFA_SERIALIZER_PROFILE_SHIFT`;
- общие ratio/size/filter outliers.

## 21. Static assets

`static_assets.check_static_assets` проверяет:

- image bundle;
- ICC/static resources;
- stamp presence;
- partial replacement;
- связь asset profile с emitter;
- static hashes.

HARD:

- `ALFA_STATIC_ASSET_PARTIAL_REPLACEMENT`;
- `ALFA_STATIC_ASSET_STAMP_MISSING`.

Supporting:

- `ALFA_STATIC_ASSET_PROFILE_SHIFT`;
- `ALFA_STATIC_ASSET_HASH_NEW`;
- `ALFA_IMAGE_PROFILE_SHIFT`.

Новый image hash сам по себе не HARD.

## 22. Shell clone

`shell_clone.check_shell_clone` сопоставляет:

- trailer ID;
- content hash;
- object shell;
- динамические реквизиты;
- сохранённую identity shell.

HARD:

- `ALFA_CLONED_ORIGINAL_SHELL_CONTENT_REWRITE`;
- `ALFA_TRAILER_ID_REUSED_WITH_DIFFERENT_CONTENT`.

Проверяется конфликт, а не просто новый или повторный trailer ID.

## 23. Content

`content.check_content` анализирует:

- decoded `/Contents`;
- operator grammar;
- BT/ET;
- hidden/overlay text;
- exact body/skeleton telemetry;
- emitter-specific size bands;
- Quartz midgap;
- Oracle card/SBP midgap.

Пороговые профили:

```text
Quartz: max decoded <4912 B → strong outlier
Quartz: 5012 < max decoded <6004 B → midgap
Oracle: промежуток между card {3413, 4152} и SBP [5091, 5542] → midgap
Oracle: max decoded >5692 B → strong outlier
```

HARD:

- `ALFA_CONTENT_SIZE_STRONG_OUTLIER`;
- `ALFA_QUARTZ_CONTENT_MIDGAP`;
- `ALFA_ORACLE_CONTENT_MIDGAP`;
- `ALFA_CONTENT_STREAM_EDIT`;
- `ALFA_OVERLAY_TEXT_LAYER`.

Ignored novelty:

- `ALFA_CONTENT_DECODED_EXACT_UNKNOWN`;
- `ALFA_CONTENT_BODY_EXACT_UNKNOWN`;
- `ALFA_CONTENT_SKELETON_UNKNOWN`.

## 24. Fonts

`fonts.check_fonts` строит цепочку:

```text
content font resource
→ used CID
→ ToUnicode
→ /W
→ CIDToGIDMap/Identity
→ FontFile2
→ loca/glyf/hmtx
→ outline/metrics
→ rendered text
```

Проверяются:

- used CID closure;
- пустые используемые glyph;
- `/Length1`;
- TTF table integrity;
- head mechanics;
- FontDescriptor bbox;
- Oracle hinting tables;
- outline atlas;
- metric atlas;
- glyph-slot transplant;
- Oracle exact subset closure.

Коды зарегистрированы как HARD:

- `ALFA_USED_CID_EMPTY_GLYPH`;
- `ALFA_FONT_CID_CLOSURE_VIOLATION`;
- `ALFA_GLYPH_OUTLINE_MISMATCH`;
- `ALFA_GLYPH_SLOT_TRANSPLANT`;
- `ALFA_TEXT_GLYPH_RENDER_MISMATCH`;
- `ALFA_FONTFILE2_LENGTH1_MISMATCH`;
- `ALFA_FONTFILE2_SIZE_UNDERSIZE`;
- `ALFA_FONT_TABLE_INTEGRITY_VIOLATION`;
- `ALFA_BROKEN_UNICODE_MAPPING`;
- `ALFA_ORACLE_TTF_HEAD_MECHANICS_CONFLICT`;
- `ALFA_FONT_DESCRIPTOR_HEAD_BBOX_CONFLICT`;
- `ALFA_ORACLE_SFNT_HINTING_TABLES_MISSING`.

Но итоговый tier определяется ещё и конкретным emitter. Например,
`ALFA_GLYPH_OUTLINE_MISMATCH` и `ALFA_GLYPH_SLOT_TRANSPLANT` в ряде веток
создаются как `DIAGNOSTIC`; такие экземпляры `ingest_flag` отправляет в ignored,
несмотря на присутствие code в `HARD_CODES`.

Oracle FontFile2 atlas: decoded `20570–22582 B`; undersize становится HARD
только при дополнительных признаках rebuild, а exact/new size сам по себе
игнорируется. Отсутствие `cvt/fpgm/prep` или наличие PADD в подтверждённом
Oracle-профиле даёт `ALFA_ORACLE_SFNT_HINTING_TABLES_MISSING`.

KNOWN:

- `ALFA_ORACLE_FONT_SUBSET_CLOSURE_VIOLATION` при встроенных неиспользуемых
  printable glyph, одновременно присутствующих в ToUnicode, `/W`, glyf и hmtx.

Ignored novelty:

- новый FontFile2 SHA;
- exact FontFile2 size;
- неизвестный used-glyph outline/metric;
- glyph count outlier;
- trailing padding.

## 25. Embedded font reassembly

Shared `embedded_font_reassembly.check_embedded_font_reassembly(bank="alfa")`
анализирует TTF lifecycle и cross-layer происхождение.

HARD-коды:

- `ALFA_REBUILD_TTF_HEAD_EPOCH_001`;
- `ALFA_REBUILD_FONT_EPOCH_PDF_TIME_CONFLICT_002`;
- `ALFA_REBUILD_SUBSET_SOURCE_IDENTITY_003`;
- `ALFA_REBUILD_EMITTER_FONT_LIFECYCLE_004`;
- `ALFA_REBUILD_TTF_MODIFIED_VARIABILITY_005`.

Если анализ технически не завершён, весь pipeline помечается incomplete.

## 26. Cross-document identity

`identity.extract_and_check_identity` получает:

- operation ID;
- amount;
- fee;
- operation datetime;
- method;
- file SHA;
- PDF bytes;
- прочие parsed fields.

Используются локальные базы:

- `detector/alfa_v2/alfa_v2_identity.db`;
- `detector/alfa_v2/alfa_v2_trailer_id.db`.

HARD:

`ALFA_OPERATION_IDENTITY_CONFLICT`.

Supporting:

- `ALFA_CROSS_DOCUMENT_WEAK_MATCH`;
- `ALFA_OPERATION_ID_WEAK_REUSE`;
- `ALFA_RECEIPT_STEM_WEAK_REUSE`.

Weak match не решает один.

## 27. Known file signatures

`known_signatures.KNOWN_FAKE_FILE_SHA256` содержит точные SHA подтверждённых
подделок.

Совпадение:

`ALFA_KNOWN_FAKE_SIGNATURE` — KNOWN.

Это точечная блокировка конкретного файла, а не структурное семейство.

## 28. Quartz composite manual profile

Для `quartz_ios` формируется manual review, если одновременно:

1. новый SBP core/tail;
2. unknown exact decoded content;
3. unknown exact FontFile2 size;
4. file size вне atlas min/max.

Флаг:

`ALFA_QUARTZ_UNCONFIRMED_COMPOSITE_PROFILE`.

Tier `MANUAL` не означает `ФЕЙК`; итог:

`НЕИЗВЕСТНЫЙ ДОКУМЕНТ`.

## 29. Verdict policy

Порядок:

1. incomplete → `ФЕЙК`, score 60;
2. not Alfa receipt → `ФЕЙК`, score 60;
3. KNOWN/HARD → `ФЕЙК`, score 60;
4. cross-document identity conflict → `ФЕЙК`, score 60;
5. минимум две distinct supporting-группы → `ФЕЙК`, score 60;
6. manual review → `НЕИЗВЕСТНЫЙ ДОКУМЕНТ`, score 0;
7. иначе `ЧИСТО`, score 0.

### 29.1. Supporting-группы

- `B1_serializer_container`;
- `B2_metadata_profile`;
- `B3_static_assets`;
- `B4_font_subsetter`;
- `B5_content_layout`;
- `B6_sbp_empirical`;
- `B7_cross_document_weak`.

Два флага одной группы считаются одним источником.

## 30. Policy override

`ingest_flag` сначала применяет `rules.classify_code`.

Поэтому emitter может создать `HARD`, но код попадёт в ignored, если он
демотирован в `IGNORED_CODES`.

Ключевые ignored:

- новый producer/profile;
- новый SBP core/tail;
- linked-tuple/atlas mismatch;
- exact content/font novelty;
- unknown glyph atlas;
- FIO gibberish heuristics;
- render/profile novelty;
- size envelope FontFile2.

## 31. Что проверяется по каждому методу

```text
Все:
container, xref, streams, active content, emitter coherence,
file size, common fields, operation ID/date, amount/fee,
static assets, shell clone, content, fonts, reassembly, identity.

SBP:
+ recipient/phone/bank/SBP ID;
+ SBP calendar/time;
+ field-value binding;
+ positive-fee debit field;
+ new profile observation.

Card:
+ sender/recipient card;
+ BIN/mask/last4;
+ authorization/terminal for interbank;
+ Oracle/Quartz card content profile.

Phone:
+ recipient/phone;
+ forbidden bank/SBP fields;
+ masked-name/phone artifacts;
+ phone content profile.
```

## 32. Active и legacy

Активный decision engine:

- `detector/alfa_v2/*`;
- shared `structure.py`;
- shared `embedded_font_reassembly.py`;
- внешние routing/reputation/status layers.

Legacy Alfa modules и старые weighted policies не являются источником verdict,
если явно не импортированы текущим pipeline.

## 33. Основные файлы

- `detector/alfa_v2/engine.py`;
- `detector/alfa_v2/stages.py`;
- `detector/alfa_v2/rules.py`;
- `detector/alfa_v2/verdict.py`;
- `detector/alfa_v2/profile_semantics.py`;
- `detector/alfa_v2/sbp.py`;
- `detector/alfa_v2/streams.py`;
- `detector/alfa_v2/content.py`;
- `detector/alfa_v2/fonts.py`;
- `detector/alfa_v2/static_assets.py`;
- `detector/alfa_v2/shell_clone.py`;
- `detector/alfa_v2/identity.py`;
- `detector/alfa_v2/unconfirmed_profiles.py`;
- `detector/embedded_font_reassembly.py`.

## 34. Интерпретация

`ЧИСТО` означает отсутствие достаточных доказательств подделки, а не
криптографическое подтверждение транзакции банковским backend.

Новый корректный Oracle/Quartz subset, новый SBP core/tail или новый content
body не должны блокироваться отдельно. Решение строится на внутренних
противоречиях, подтверждённых сигнатурах либо нескольких независимых слоях.

