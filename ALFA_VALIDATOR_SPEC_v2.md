# АЛЬФА-БАНК — VALIDATOR SPECIFICATION v2.1
## Как сейчас работает валидатор PDF-квитанций Альфа-Банка (фактическая реализация)

**Дата фиксации:** 21.07.2026  
**Статус:** Production (без shadow / без процентного rollout на live-пути)  
**Проект:** `pdf-checker-bot`  
**Движок:** `alfa_v2` / `VALIDATOR_VERSION = "2.1.0"`  
**Сервер:** `85.192.40.122`, сервис `pdfbot`, бот `@proton_pdf_bot`  
**Источник истины:** код в `detector/alfa_v2/` + `detector/alfa.py`  
**Зонтичный документ:** `PDFCHECKER_VALIDATOR_SPEC_v1*.md`  
**Аналоги:** `TBANK_VALIDATOR_SPEC_v6.md`, `SBER_VALIDATOR_SPEC_v2.md`  
**Директива v1 (не live):** `tools/_alfa_v1_spec_extracted.txt`

---

## 0. Назначение

Этот документ описывает **только Альфа-Банк**: роутинг, pipeline, каталоги HARD/KNOWN/B/IGNORE, **три подметода** (СБП / карта→карта / телефон), два emitter-профиля (Oracle BI / Quartz iOS), SBP-грамматику, шрифты, shell-clone, bot UX — **как реально работает код на 21.07.2026**.

| Термин | Значение |
|--------|----------|
| `alfa_v2` | Единственный **live** decision engine Альфы |
| `alfa_v1` | Код есть, **не** на live-входе `detector/alfa.py` |
| `alfa_legacy` | Старый score-engine — только через dormant v1 rollout |
| HARD | Один флаг → **ФЕЙК** |
| KNOWN | Подтверждённая сигнатура → **ФЕЙК** |
| Supporting (tier B) | ФЕЙК только при **≥2 разных группах** |
| IGNORE / DIAGNOSTIC | Не влияют на вердикт |
| `НЕИЗВЕСТНЫЙ ДОКУМЕНТ` | `manual_review_*` без HARD/KNOWN |
| Novelty | Новый FontFile2 / bank5 / subset ≠ фейк |

**Главный принцип:** новизна ≠ подделка. ФЕЙК только при **межслойном противоречии**, **известной сигнатуре**, или **согласии ≥2 независимых Tier-B групп**.

---

## Содержание

1. [Главный принцип и запреты](#1-главный-принцип-и-запреты)
2. [Точка входа и роутинг](#2-точка-входа-и-роутинг)
3. [Карта файлов](#3-карта-файлов)
4. [Выходной словарь и типы](#4-выходной-словарь-и-типы)
5. [Вердикт (ЧИСТО / ФЕЙК / НЕИЗВЕСТНЫЙ)](#5-вердикт-чисто--фейк--неизвестный)
6. [Каталог правил](#6-каталог-правил)
7. [Подметоды (все каналы)](#7-подметоды-все-каналы)
8. [Emitter-профили Oracle / Quartz](#8-emitter-профили-oracle--quartz)
9. [Pipeline по стадиям](#9-pipeline-по-стадиям)
10. [Модули-детекторы (детально)](#10-модули-детекторы-детально)
11. [СБП ID: структура и грамматика](#11-сбп-id-структура-и-грамматика)
12. [Номер операции C16 / Z09 / C07](#12-номер-операции-c16--z09--c07)
13. [Шрифты и glyph](#13-шрифты-и-glyph)
14. [Streams / static assets / shell](#14-streams--static-assets--shell)
15. [Telegram-бот](#15-telegram-бот)
16. [Деплой, env, регрессии](#16-деплой-env-регрессии)
17. [Запрещённые ложные признаки](#17-запрещённые-ложные-признаки)
18. [Расхождения с v1 / dormant](#18-расхождения-с-v1--dormant)
19. [Приложения](#19-приложения)

---

## 1. Главный принцип и запреты

| Параметр | Значение |
|----------|----------|
| Внешний вердикт | **ЧИСТО** / **ФЕЙК** / **НЕИЗВЕСТНЫЙ ДОКУМЕНТ** |
| Score | **0** или **60** (`FAKE_THRESHOLD`) |
| Engine | `alfa_v2` |
| Rollout на live | нет — `rollout_mode: "full"` захардкожен в `engine.py` |

**Не банить за:**
- неизвестный FontFile2 SHA / subset prefix (`ALFA_FONT_HASH_NEW` → Tier-B alone)
- новый SBP bank5/suffix (`ALFA_NEW_SBP_PROFILE_OBSERVED` → IGNORE)
- один supporting-флаг без второй группы
- empirical SBP marker/tail alone (Tier-B)
- «Producer не из базы» без cross-layer conflict
- render rows / foreign stripes (IGNORE)

**Два слоя:**
1. Структурный — container, incremental/xref (у Альфы **строже**, чем у Сбера), streams, fonts, shell ID  
2. Семантический — method contract, operation ID, SBP grammar, amounts, cross-doc

**Отличие от Сбера:** incremental update / multiple EOF / Prev trailer → у Альфы **HARD**, у Сбера **IGNORE**.

---

## 2. Точка входа и роутинг

### 2.1. Общий поток

```
PDF bytes
  → detector/__init__.py::route()
       → fitz: text + producer
       → profiles.identify(...)          # key == "alfa" | "alfa_ios"?
       → run_global_preflight()
       → profiles.analyze_for(...)
            → detector/alfa.py
                 → alfa_v2.engine.analyze()
       → (опционально) hardening / status
  → (bank_name="Альфа-Банк", result)
```

### 2.2. Профили — `profiles.py`

| `key` | Markers | Producers | Analyzer |
|-------|---------|-----------|----------|
| `alfa` | квитанция о переводе, сформирована, альфа-банк, alfa-bank | `oracle bi publisher` | `use_alfa_engine=True` |
| `alfa_ios` | сформирована, квитанция о переводе | `quartz pdfcontext` | тот же `alfa_v2` |

**Boost:** Quartz + «Сформирована» + «Квитанция о переводе» → score **1.0**.  
**Exclusive producer:** `oracle bi publisher` → alfa.

### 2.3. Обёртка — `detector/alfa.py`

```python
from .alfa_v2.engine import VALIDATOR_VERSION, analyze
# alfa_v1 / legacy НЕ вызываются
```

### 2.4. Receipt gate — `stages._is_alfa_receipt`

Принимает файл если:
- ≥2 маркера из `{квитанция о переводе, альфа-банк, alfa-bank, сформирована}`, **или**
- Producer Oracle/Quartz + soft text / `C…`/`Z…` op-id / trailer `/ID` (устойчиво к glyph transplant).

Иначе → `not_alfa_receipt` → **ФЕЙК** `[NOT_ALFA_RECEIPT]`.

---

## 3. Карта файлов

### Decision engine (`alfa_v2/`)

| Файл | Роль |
|------|------|
| `engine.py` | Entry: SHA-256 → pipeline → verdict → expert_report |
| `stages.py` | Полный pipeline |
| `verdict.py` | Бинарный + НЕИЗВЕСТНЫЙ, `ingest_flag` |
| `rules.py` | HARD / KNOWN / SUPPORTING / IGNORE |
| `types.py` | `AlfaFlag`, `PipelineResult` |
| `explain.py` | Expert report |
| `profile_semantics.py` | Подметод + field contract + op ID + amounts + emitter |
| `sbp.py` | 32-char SBP structure/time/atlas |
| `fonts.py` | CID/glyph/TTF (Oracle-gated HARD) |
| `streams.py` | Serializer / Deflate provenance |
| `static_assets.py` | Image/ICC atlas |
| `content.py` | Content layout fingerprints |
| `shell_clone.py` | Trailer ID / shell rewrite |
| `identity.py` | Cross-doc identity |
| `unconfirmed_profiles.py` | New bank5/suffix observe-only |
| `pdfutil.py` | Low-level PDF helpers |
| `atlas_data/*` | SBP, glyph, fonts, streams, shells |

### Shared / dormant

| Модуль | Роль |
|--------|------|
| `detector/alfa_profiles.py` | Richer subtype labels (v1/bot); live v2 использует только sbp/card/phone |
| `detector/alfa_sbp_cipher.py` | Legacy cipher helpers |
| `detector/alfa_v1/` | Reference + `ALFA_V1_ROLLOUT` (не live) |
| `detector/alfa_legacy.py` | Dead for verdict |

---

## 4. Выходной словарь и типы

```python
{
  "verdict": "ЧИСТО" | "ФЕЙК" | "НЕИЗВЕСТНЫЙ ДОКУМЕНТ",
  "emoji": "✅" | "🔴" | "⚪",
  "score": 0 | 60,
  "flags": [...],          # decisive / supporting lines при ФЕЙК
  "details": {
     "file_hash": "...",
     "validator_version": "2.1.0",
     "engine": "alfa_v2",
     "rollout_mode": "full",
     "channel": "sbp" | "card" | "phone" | "unknown",
     "receipt_subtype": ...,   # = channel в live v2
     "receipt_subtype_label": "...",
     "generator_path": "oracle_bi" | "quartz_ios" | "unknown",
     "completed_checks": [...],
     "stats": {...},
     "hard_flags": [...],
     "known_fake_flags": [...],
     "hard_count", "known_fake_count",
     "supporting_count", "supporting_groups", "supporting_group_count",
     "ignored_observations": [...],
     "analysis_complete": bool,
     "cross_document_identity_conflict": bool,
     "manual_review_required": bool,
     "manual_review_flags": [...],
     "expert_report": {...},
     "user_message": "Обнаружена подделка."
                     | "Неподтверждённый профиль — требуется ручная проверка."
                     | "Признаков подделки не найдено."
  }
}
```

---

## 5. Вердикт (ЧИСТО / ФЕЙК / НЕИЗВЕСТНЫЙ)

`alfa_v2/verdict.py` — порядок строго такой:

```
1. !analysis_complete                → ФЕЙК [ANALYSIS_NOT_COMPLETED] score 60
2. not_alfa_receipt                  → ФЕЙК [NOT_ALFA_RECEIPT] score 60
3. known_fake ∪ hard_flags           → ФЕЙК (все decisive lines) score 60
4. cross_document_identity_conflict  → ФЕЙК [ALFA_OPERATION_IDENTITY_CONFLICT] score 60
5. ≥2 distinct supporting groups     → ФЕЙК (все B-flags) score 60
6. manual_review_required / flags    → НЕИЗВЕСТНЫЙ ДОКУМЕНТ score 0
7. иначе                             → ЧИСТО score 0 flags=[]
```

`ingest_flag`:
- tier DIAGNOSTIC/IGNORE → `ignored_observations`
- tier MANUAL → `manual_review_*`
- code ∈ KNOWN или tier=KNOWN → `known_fake_flags`
- code ∈ HARD или tier HARD/A → `hard_flags`
- code ∈ SUPPORTING_GROUPS или tier=B → `supporting_flags`
- иначе → `ignored_observations`

Один supporting-флаг **никогда** не даёт ФЕЙК.

---

## 6. Каталог правил

Источник: `detector/alfa_v2/rules.py`.

### 6.1. HARD (один → ФЕЙК)

**Intake / identity:**  
`ANALYSIS_NOT_COMPLETED`, `NOT_ALFA_RECEIPT`

**Container (строже Сбера):**  
`PDF_STRUCTURE_INVALID`, `MULTIPLE_PDF_HEADERS`, `TRAILER_INVALID`, `XREF_OFFSET_INVALID`,  
`MULTIPLE_STARTXREF_PRESENT`, `MULTIPLE_EOF_PRESENT`, `MULTIPLE_XREF_PRESENT`,  
`PREV_TRAILER_PRESENT`, `INCREMENTAL_UPDATE_PRESENT`,  
`DUPLICATE_ACTIVE_OBJECT_DEFINITION`, `BROKEN_OBJECT_STRUCTURE`, `TRAILING_DATA_AFTER_EOF`,  
`OBJECT_GRAPH_INCONSISTENT`

**Streams / active content:**  
`STREAM_DECOMPRESSION_FAILED`, `STREAM_LENGTH_MISMATCH`, `UNEXPECTED_STREAM_FILTER`,  
`JAVASCRIPT_PRESENT`, `ACTIVE_CONTENT_PRESENT`, `OPENACTION_PRESENT`, `DANGEROUS_ACTION_PRESENT`,  
`EMBEDDED_FILE_PRESENT`, `EMBEDDED_PAYLOAD_PRESENT`, `ACROFORM_PRESENT`, `XFA_PRESENT`

**Provenance / shell:**  
`ALFA_PROFILE_CROSS_LAYER_CONFLICT`, `ALFA_MIXED_SERIALIZER_PROVENANCE`,  
`ALFA_MIXED_ZLIB_SERIALIZER_PROVENANCE`, `ALFA_ORACLE_FULL_DEFLATE_PROVENANCE_MISMATCH`,  
`ALFA_STATIC_ASSET_PARTIAL_REPLACEMENT`, `ALFA_CLONED_ORIGINAL_SHELL_CONTENT_REWRITE`,  
`ALFA_TRAILER_ID_REUSED_WITH_DIFFERENT_CONTENT`

**Semantics / IDs:**  
`ALFA_OPERATION_NUMBER_FORMAT`, `ALFA_OPERATION_DATE_LINK_MISMATCH`,  
`ALFA_SBP_ID_STRUCTURE_INVALID`, `ALFA_SBP_ID_CALENDAR_CONFLICT`,  
`ALFA_SBP_ID_TIME_ORDER_CONFLICT`, `ALFA_SBP_LINKED_TUPLE_CONFLICT`,  
`ALFA_SBP_ATLAS_LINK_MISMATCH`, `ALFA_FIELD_SET_METHOD_CONFLICT`,  
`ALFA_AMOUNT_ARITHMETIC_MISMATCH`, `ALFA_OPERATION_IDENTITY_CONFLICT`

**Fonts / content:**  
`ALFA_USED_CID_EMPTY_GLYPH`, `ALFA_FONT_CID_CLOSURE_VIOLATION`, `ALFA_GLYPH_OUTLINE_MISMATCH`,  
`ALFA_GLYPH_SLOT_TRANSPLANT`, `ALFA_TEXT_GLYPH_RENDER_MISMATCH`,  
`ALFA_FONTFILE2_LENGTH1_MISMATCH`, `ALFA_FONT_TABLE_INTEGRITY_VIOLATION`,  
`ALFA_BROKEN_UNICODE_MAPPING`, `ALFA_ORACLE_TTF_HEAD_MECHANICS_CONFLICT`,  
`ALFA_FONT_DESCRIPTOR_HEAD_BBOX_CONFLICT`, `ALFA_USED_GLYPH_OUTLINE_ATLAS_CONFLICT`,  
`ALFA_USED_GLYPH_METRIC_CONFLICT`, `ALFA_CONTENT_STREAM_EDIT`, `ALFA_OVERLAY_TEXT_LAYER`

### 6.2. KNOWN

| Code | Смысл |
|------|--------|
| `ALFA-KNOWN-FAKE-001` / `ALFA_KNOWN_FAKE_SIGNATURE` | точная known-fake сигнатура |
| `ALFA_KNOWN_GENERATOR_OPERATION_TIME_EMBEDDING` | `C16`+`DDMMYY`+`HHMMSS`+digit = видимое время |
| `ALFA_KNOWN_GENERATOR_FULL_RESERIALIZATION` | Oracle shell + Java Deflater(6) **и** time-embedding |
| `ALFA_ORACLE_FONT_SUBSET_CLOSURE_VIOLATION` | Oracle subset closure |

### 6.3. Supporting (tier B) — группы

| Группа | Коды |
|--------|------|
| `B1_serializer_container` | `STREAM_COMPRESSION_RATIO_OUTLIER`, `DECODED_STREAM_SIZE_OUTLIER`, `STREAM_FILTER_ANOMALY`, `ALFA_SERIALIZER_PROFILE_SHIFT`, `ALFA_CONTAINER_PROFILE_SHIFT` |
| `B2_metadata_profile` | `FOREIGN_PRODUCER`, `PDF_MODDATE_EDITED`, `ALFA_METADATA_PROFILE_SHIFT`, `ALFA_PRODUCER_PROFILE_SHIFT` |
| `B3_static_assets` | `ALFA_STATIC_ASSET_PROFILE_SHIFT`, `ALFA_STATIC_ASSET_HASH_NEW`, `ALFA_IMAGE_PROFILE_SHIFT` |
| `B4_font_subsetter` | `ALFA_FONT_SUBSETTER_PROFILE_SHIFT`, `ALFA_FONT_HASH_NEW`, `TTF_NUMGLYPHS_MISMATCH`, `TTF_HMTX_PROFILE_SHIFT`, `TTF_HEAD_ANOMALY` |
| `B5_content_layout` | `ALFA_CONTENT_LAYOUT_PROFILE_SHIFT`, `CONTENT_STREAM_PROFILE_MISMATCH`, `RIGHT_EDGE_ALIGNMENT_DRIFT`, `TEXT_OPERATOR_SEQUENCE_ANOMALY`, **`ALFA_FIELD_CONTRACT_MISMATCH`** |
| `B6_sbp_empirical` | `ALFA_SBP_EMPIRICAL_PROFILE`, `ALFA_SBP_TAIL_UNKNOWN`, `ALFA_SBP_SEPARATOR_DIGIT` |
| `B7_cross_document_weak` | `ALFA_CROSS_DOCUMENT_WEAK_MATCH`, `ALFA_OPERATION_ID_WEAK_REUSE`, `ALFA_RECEIPT_STEM_WEAK_REUSE` |

### 6.4. IGNORE (выборка)

`ALFA_PRODUCER_OBSERVATION`, `ALFA_GENERATOR_PATH`, `ALFA_NEW_PROFILE`, `ALFA_NEW_SBP_PROFILE_OBSERVED`,  
`ALFA_OPERATION_ID_UNKNOWN`, `ALFA_SBP_ID_MISSING` (не в HARD — missing SBP без structure fail не банит сам),  
`FF2_SUBSET_UNKNOWN`, `ALFA_RENDER_*`, `ALFA_CONTENT_SKELETON_UNKNOWN`, …

---

## 7. Подметоды (все каналы)

Классификатор: `alfa_v2.profile_semantics.classify_submethod(text)`.  
Имя файла **не** используется. Title сильнее смешанных семейств.

### 7.1. Карта подметодов

| Method | Корпус (v1) | Title / evidence | Op ID prefix | SBP stage |
|--------|-------------|------------------|--------------|-----------|
| **`sbp`** | 37 | «Квитанция о переводе по СБП»; SBP ID; `C16…` | `C16` | **да** |
| **`card`** | 2 | «…с карты на карту» / поля карт; `Z09…` | `Z09` | нет |
| **`phone`** | 1 | «…клиенту Альфа-Банка»; `C07…` | `C07` | нет |
| **`unknown`** | — | нет доказательств | — | нет |

**Важно:** телефон получателя на СБП-квитанции **не** является evidence для `phone`.

Смешанные proven families без однозначного title → HARD `ALFA_FIELD_SET_METHOD_CONFLICT`.

### 7.2. Field contracts (`validate_field_contract`)

**Общие обязательные:** сумма перевода; комиссия; дата и время перевода; номер операции.

| Method | Доп. required | Forbidden | Условие |
|--------|---------------|-----------|---------|
| **sbp** | получатель; телефон получателя; банк получателя; идентификатор операции в СБП | — | если fee>0 → «списано с учетом/учётом комиссии» |
| **card** | номер карты отправителя; номер карты получателя | — | interbank markers → код авторизации + терминал |
| **phone** | получатель; телефон получателя | банк получателя/отправителя; SBP ID | — |

Нарушение contract → **`ALFA_FIELD_CONTRACT_MISMATCH` Tier-B** (`B5_content_layout`), не HARD.

### 7.3. Amounts (все методы)

`parse_amounts` + arithmetic: amount + fee должен согласоваться с debit и/или total → HARD `ALFA_AMOUNT_ARITHMETIC_MISMATCH`.

### 7.4. Labels в bot / details

| `channel` | `receipt_subtype_label` |
|-----------|-------------------------|
| `sbp` | СБП Альфа-Банк |
| `card` | Альфа-Банк, с карты на карту |
| `phone` | Альфа-Банк, клиенту по телефону |
| иначе | Квитанция Альфа-Банка |

### 7.5. Опциональные subtypes (`alfa_profiles.py`, не live verdict)

Для отображения/v1: `sbp`, `intrabank_phone`, `card_intrabank`, `card_interbank` (BIN + банк получателя).  
**Live v2 `receipt_subtype` = channel** (`sbp`/`card`/`phone`).

### 7.6. Неизвестный будущий подметод

Архив не содержит других семейств. Новый согласованный подметод идёт через generic pipeline; без HARD → **ЧИСТО** (или MANUAL только если явно выставлен), **не** бан за отсутствие в таблице корпуса.

---

## 8. Emitter-профили Oracle / Quartz

| Признак | Oracle BI | Quartz iOS |
|---------|-----------|------------|
| Producer | `Oracle BI Publisher 12.2.1.4.0` | `iOS … Quartz PDFContext` |
| PDF version | 1.6 | 1.3 |
| Object count (типично) | 16 | ~17–18 |
| Fonts | Tahoma / F1 | Font000000 / G1 |
| Color | DeviceRGB | ICCBased (+ Interpolate) |
| `generator_path` | `oracle_bi` | `quartz_ios` |

`classify_emitter`: conflict Oracle vs Quartz на **≥2 независимых слоях** → HARD `ALFA_PROFILE_CROSS_LAYER_CONFLICT`.  
Один только Producer без второго слоя → не HARD.

---

## 9. Pipeline по стадиям

`alfa_v2/stages.py` → `run_pipeline`:

```
1. intake                 — size ≤ 8MB
2. container              — structure + incremental + xref
3. streams_active         — compression + active content
4. receipt gate           — _is_alfa_receipt
5. profile_semantics      — method + contracts + op IDs + amounts + emitter
   └─ if method==sbp → validate_sbp_text
6. serializer_assets      — streams + static assets
   └─ combo Deflater + time-embed → KNOWN full reserialization
7. shell_clone
8. content_fonts          — content + fonts
9. cross_document_identity
10. new_sbp_profile       — observe-only (bank5/suffix)
11. complete
```

---

## 10. Модули-детекторы (детально)

### 10.1. `profile_semantics.py`
- classify method / emitter  
- field contracts (B)  
- operation ID format + date link (HARD) + synthetic time-embed (KNOWN)  
- amount arithmetic (HARD)

### 10.2. `sbp.py` (только `method==sbp`)
См. §11.

### 10.3. `streams.py` / `static_assets.py`
Смешанный serializer / полный Java Deflater(6) на Oracle shell → HARD.  
Partial static asset replacement → HARD. Profile shift → Tier-B.

### 10.4. `shell_clone.py`
Reuse trailer `/ID` с другим content → HARD.  
Cloned shell rewrite → HARD.

### 10.5. `fonts.py`
Oracle-gated TTF/`head`/descriptor/bbox/outline atlas.  
Glyph transplant / empty CID / outline mismatch → HARD.  
Subset closure violation → **KNOWN**.

### 10.6. `content.py`
Overlay text layer / content stream edit → HARD. Layout drift → Tier-B.

### 10.7. `identity.py`
Conflict operation identity across docs → `cross_document_identity_conflict` → ФЕЙК.

### 10.8. `unconfirmed_profiles.py`
Новый bank5/suffix → `ALFA_NEW_SBP_PROFILE_OBSERVED` IGNORE; **не** форсит MANUAL/UNKNOWN.

---

## 11. СБП ID: структура и грамматика

Формат: **ровно 32** символа `[0-9A-Z]`. Маркер обычно `A`/`B`.

```
[0]       marker
[1:5]     calendar  (year = 2020 + cal//1000 … — см. _decode_datetime)
[5:11]    HHMMSS UTC
[11:17]   reference  (последний символ [16] должен быть '0')
[17]      control
[18:22]   route
[22:27]   core / bank5
[27:32]   tail
```

**Linked-tuple segmentation** (`_route_segments`): lead / timestamp / reference / route_marker[14] / control / separator / class / slot / bank5 / suffix.

| Правило | Tier |
|---------|------|
| length≠32 / alphabet / reference[-1]≠`0` / slot structure | HARD `ALFA_SBP_ID_STRUCTURE_INVALID` |
| calendar vs visible date ∉ {day, day−1} | HARD `ALFA_SBP_ID_CALENDAR_CONFLICT` |
| encoded local (UTC+3) lag ∉ [0, **3h5m**] или negative | HARD `ALFA_SBP_ID_TIME_ORDER_CONFLICT` |
| atlas deterministic link mismatch | HARD `ALFA_SBP_ATLAS_LINK_MISMATCH` |
| route_marker reuse conflict on linked key | HARD `ALFA_SBP_LINKED_TUPLE_CONFLICT` |
| unknown marker/control | Tier-B `ALFA_SBP_EMPIRICAL_PROFILE` (+ tail/separator codes) |
| unknown channel/core/tail/combination | IGNORE `ALFA_SBP_PROFILE_NOVELTY` — закрытый корпус до 2026-06-29; живой core 00118 с 2026-07 |
| SBP ID отсутствует в тексте | IGNORE `ALFA_SBP_ID_MISSING` (не HARD) |

`_MAX_COMPLETION_LAG = timedelta(hours=3, minutes=5)`.

---

## 12. Номер операции C16 / Z09 / C07

Формат: **16** символов `^[A-Z]\d{15}$`.

| Method | Regex / prefix |
|--------|----------------|
| sbp | `^C16\d{13}$` |
| card | prefix `Z09` |
| phone | prefix `C07` |

| Правило | Tier |
|---------|------|
| неверный формат / чужой prefix | HARD `ALFA_OPERATION_NUMBER_FORMAT` |
| `[3:9] != DDMMYY` видимой даты | HARD `ALFA_OPERATION_DATE_LINK_MISMATCH` |
| `C16`+`DDMMYY`+`HHMMSS`+digit = visible datetime | **KNOWN** `ALFA_KNOWN_GENERATOR_OPERATION_TIME_EMBEDDING` |

Комбо: KNOWN time-embedding **+** `ALFA_ORACLE_FULL_DEFLATE_PROVENANCE_MISMATCH` → дополнительно KNOWN `ALFA_KNOWN_GENERATOR_FULL_RESERIALIZATION`.

---

## 13. Шрифты и glyph

- Тяжёлые HARD на Oracle TTF mechanics / descriptor bbox / used glyph atlas  
- Transplant / empty glyph / outline mismatch → HARD  
- `ALFA_ORACLE_FONT_SUBSET_CLOSURE_VIOLATION` → KNOWN  
- Новый FontFile2 / subsetter profile → Tier-B alone (нужна вторая группа)

---

## 14. Streams / static assets / shell

| Сигнал | Tier |
|--------|------|
| Mixed serializer / zlib provenance | HARD |
| Oracle full Deflater(6) mismatch | HARD |
| Partial image/ICC replacement | HARD |
| Asset/hash profile shift | B3 |
| Trailer ID reused, different content | HARD |
| Cloned shell content rewrite | HARD |

---

## 15. Telegram-бот

`bot.py`:
- `engine in {alfa_v1, alfa_v2}` или shadow → expert body из `expert_report`  
- Live путь отдаёт `alfa_v2` details (`channel`, `supporting_groups`, …)  
- Shadow `alfa_v1_shadow` в production **не** прикрепляется обёрткой `alfa.py`

---

## 16. Деплой, env, регрессии

| Параметр | Значение |
|----------|----------|
| Live entry | `detector/alfa.py` → `alfa_v2` |
| `VALIDATOR_VERSION` | `2.1.0` |
| Env (dormant) | `ALFA_V1_ROLLOUT` — не влияет на live |
| Max PDF | 8_000_000 bytes |
| FAKE_THRESHOLD | 60 |

Регрессии: корпус Oracle+Quartz × sbp/card/phone; known synthetic C16 time-embed; incremental PDF → HARD.

---

## 17. Запрещённые ложные признаки

Нельзя считать ФЕЙК только из-за:
- нового producer / PDF version / object count alone  
- нового FontFile2 hash / subset  
- нового SBP bank5/suffix  
- одного Tier-B сигнала  
- render rows / perceptual stripes  
- «не из таблицы корпуса 40 PDF»

---

## 18. Расхождения с v1 / dormant

| Тема | v1 extracted spec | Live v2 |
|------|-------------------|---------|
| Verdict soft aggregation | запрещал «2 soft = fake» | **≥2 Tier-B groups → ФЕЙК** |
| Entry | future-safe v1 package | `alfa_v2` only |
| Incremental / multi-EOF | diagnostic | **HARD** |
| New SBP profile | manual path possible | observe-only CLEAN |
| Subtypes | card intra/inter | live = 3 channels |

При расхождении с `tools/_alfa_v1_spec_extracted.txt` — **верить коду `alfa_v2/`**.

---

## 19. Приложения

### A. Flow

```
PDF → identify(alfa|alfa_ios) → alfa_v2.analyze
  → container/streams → receipt gate
  → classify sbp|card|phone → semantics (+ SBP if sbp)
  → serializer/assets/shell → fonts/content → identity
  → verdict: ЧИСТО / ФЕЙК / НЕИЗВЕСТНЫЙ
```

### B. Ключевые константы

| Константа | Где | Значение |
|-----------|-----|----------|
| `VALIDATOR_VERSION` | `alfa_v2/engine.py` | `"2.1.0"` |
| `FAKE_THRESHOLD` | `verdict.py` | `60` |
| `_MAX_BYTES` | `stages.py` | `8_000_000` |
| `_MAX_COMPLETION_LAG` | `sbp.py` | `3h5m` |
| Op prefixes | `profile_semantics` | C16 / Z09 / C07 |
| Corpus contracts | stats | sbp:37 card:2 phone:1 |

### C. `completed_checks` (типичный успех)

```
intake
container
streams_active
profile_semantics
serializer_assets
shell_clone
content_fonts
cross_document_identity
new_sbp_profile
complete
```

### D. Связанные документы

| Документ | Роль |
|----------|------|
| `TBANK_VALIDATOR_SPEC_v6.md` | Т-Банк |
| `SBER_VALIDATOR_SPEC_v2.md` | Сбер (6 подметодов) |
| `PDFCHECKER_VALIDATOR_SPEC_v1*.md` | зонтик |
| `tools/_alfa_v1_spec_extracted.txt` | директива v1 (не live) |
| `docs/alfa_sbp_cipher_analysis.md` | разбор SBP layout |
| `detector/alfa_v2/` | код — источник истины |

### E. Быстрая шпаргалка

| Ситуация | Результат |
|----------|-----------|
| Incremental / multi-EOF | ФЕЙК HARD |
| Смесь Oracle+Quartz слоёв | ФЕЙК HARD |
| SBP lag > 3h5m / calendar conflict | ФЕЙК HARD |
| C16 embeds DDMMYYHHMMSS | ФЕЙК KNOWN |
| Field contract mismatch alone | Tier-B → ЧИСТО |
| Field contract + font hash new (≥2 групп) | ФЕЙК |
| Новый bank5 alone | IGNORE → ЧИСТО |
| Glyph transplant / empty CID | ФЕЙК HARD |
| Согласованный новый подметод без противоречий | ЧИСТО (PDF-only) |

---

*Конец спецификации. При расхождении с любым текстом вне репозитория — верить коду `detector/alfa_v2/` и `detector/alfa.py`.*
