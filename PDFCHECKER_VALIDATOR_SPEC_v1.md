# PDF-CHECKER — VALIDATOR MASTER SPECIFICATION v1.1
## Детектор PDF-квитанций (проект `pdf-checker-bot`) — полная реализация

**Дата:** 16.07.2026
**Статус:** Production
**Сервер:** `85.192.40.122`, сервис `pdfbot`, бот `@proton_pdf_bot` (PROTON PDF checker)

---

## 0. Назначение этого документа

`TBANK_MASTER_SPEC_v7.md` описывает **генератор** фейков (проект `samaya-ohuenaya-versiya`) и лишь поверхностно — что ловит «конкурент». **Этот проект (`pdf-checker-bot`) и есть тот самый валидатор/детектор.** Документ фиксирует **фактическую production-реализацию на 16.07.2026** со всеми модулями, правилами, кодами, порогами, движками банков, ботом, деплоем и регрессиями — то, чего нет в v7.

**Соответствие терминов:**

| v7 (генератор) | Этот проект (валидатор) |
|----------------|-------------------------|
| «конкурент», «валидатор» | **это мы** — `detector/` |
| «наш генератор» | внешний источник фейков, который мы ловим |
| «прошёл/не прошёл» | вердикт **ЧИСТО / ФЕЙК / НЕИЗВЕСТНЫЙ ДОКУМЕНТ** |

---

## Содержание

1. [Главный принцип детектора](#1-главный-принцип-детектора)
2. [Архитектура и точка входа](#2-архитектура-и-точка-входа)
3. [Идентификация и роутинг банков](#3-идентификация-и-роутинг-банков)
4. [Движки-детекторы](#4-движки-детекторы)
5. [Система вердиктов и tiers](#5-система-вердиктов-и-tiers)
6. [Полный каталог правил T-Bank v6](#6-полный-каталог-правил-t-bank-v6)
7. [T-Bank pipeline (стадии)](#7-t-bank-pipeline-стадии)
8. [T-Bank модули-детекторы (детально)](#8-t-bank-модули-детекторы-детально)
9. [СБП ID: структура, грамматика, профили](#9-сбп-id-структура-грамматика-профили)
10. [Шрифты и glyph-подсистема](#10-шрифты-и-glyph-подсистема)
11. [Корпусные профили и константы](#11-корпусные-профили-и-константы)
12. [Атлас-данные](#12-атлас-данные)
13. [Движки других банков](#13-движки-других-банков)
14. [hardening_v2 (пре-слой)](#14-hardening_v2-пре-слой)
15. [Telegram-бот](#15-telegram-бот)
16. [Reputation / analytics / blocklist](#16-reputation--analytics--blocklist)
17. [Деплой и инфраструктура](#17-деплой-и-инфраструктура)
18. [Регрессии и тестовые корпуса](#18-регрессии-и-тестовые-корпуса)
19. [Карта файлов проекта](#19-карта-файлов-проекта)
20. [История добавленных правил](#20-история-добавленных-правил)
21. [Приложения](#21-приложения)

---

## 1. Главный принцип детектора

| Параметр | Значение |
|----------|----------|
| Внешний вердикт | **ЧИСТО** / **ФЕЙК** / **НЕИЗВЕСТНЫЙ ДОКУМЕНТ** |
| Внутренний движок T-Bank | `tbank_v6`, `VALIDATOR_VERSION = "6.0.0"` |
| Порог фейка (все движки) | `FAKE_THRESHOLD = 60` |
| Главное правило | **Новизна ≠ подделка.** Новый hash / subset / сумма / ФИО / банк сами по себе НЕ дают ФЕЙК |
| Hard-триггер | Доказанное внутреннее противоречие: corruption, несогласованный SBP ID, font rebuilder, keywords lex, overlay, glyph transplant и т.д. |
| Философия | ФЕЙК только при **межслойном противоречии** или **известной сигнатуре**, а не при отличии от корпуса |

**Ключевые запреты (политика ложных срабатываний):**
- Не банить по неизвестному FontFile2 SHA
- Не банить по неизвестному glyf/loca hash
- Не банить по «шрифт не из пула»
- Не банить по новому subset prefix / trailer /ID / random keywords hash
- SBP empirical (`SBP_PROFILE_EMPIRICAL`) — только tier B; ФЕЙК только со 2-й независимой supporting-группой

**Два слоя проверки:**
1. **Структурный** — PDF container, xref, streams, fonts, content AST
2. **Семантический** — поля чека, арифметика, SBP ID grammar, metadata lex, glyph integrity

---

## 2. Архитектура и точка входа

### 2.1. Точка входа детектора — `detector/__init__.py::route()`

```
route(pdf_bytes) -> (bank_name, result_dict, is_tbank)
```

Поток (`detector/__init__.py:42-101`):
1. Открыть PDF через PyMuPDF (`fitz`) → извлечь `producer`, `text`
2. `profiles.identify(text, producer)` → `bank_key`, `bank_name`
3. **Все банки:** `run_global_preflight()` (`hardening_v2/global_preflight.py`) — глобальные hard-правила → мгновенный `ФЕЙК` score 95
4. **T-Bank:** `profiles.analyze_for("tbank")` + `analyze_status()` предупреждение, `is_tbank=True`
5. **Другие известные банки:** `run_hardening_v2()` → router + global rules + status conflict; может вернуть `НЕИЗВЕСТНЫЙ ДОКУМЕНТ` / hard `ФЕЙК`; иначе движок банка + `merge_hardening_into_result` + `apply_v2_priority`
6. **Неизвестный банк:** `full_bank.analyze(pdf_bytes, "unknown")`

### 2.2. Диспетчер движков — `detector/profiles.py::analyze_for()`

```python
if p.use_tbank_engine:  return analyze_tbank(...)   # tbank_v6
if p.use_alfa_engine:   return analyze_alfa(...)     # alfa_v1
if key == "sber":       return analyze_sber(...)     # sber_v1
if key == "ozon":       return analyze_ozon(...)     # ozon_v1
if key == "vtb":        return analyze_vtb(...)       # vtb_v1
if key == "gazprombank":return analyze_gazprombank() # gpb_v1 (+ Sber reroute)
if is_sparse9_bank(key):return analyze_sparse9(...)  # sparse9_v1
return full_analyze(...)                              # full_bank
```

Обёртки банков (`tbank.py`, `alfa.py`, …) делегируют в движки через `rollout.py` (shadow/percent → legacy). **T-Bank — 100% v6, без rollout.**

### 2.3. Выходной словарь `analyze()` (T-Bank v6, `engine.py:43-49`)

```python
{
  "verdict": "ЧИСТО" | "ФЕЙК",
  "emoji":   "✅" | "🔴",
  "score":   0 | 60,
  "flags":   [ "[CODE] detail", ... ],   # decisive evidence
  "details": {
     "file_hash", "validator_version"="6.0.0", "engine"="tbank_v6",
     "channel", "receipt_subtype", "receipt_subtype_label",
     "completed_checks": [...], "stats": {...},
     "hard_count", "known_fake_count", "supporting_count",
     "ignored_observations": [...], "analysis_complete": bool,
     "expert_report": {...},         # для privileged users
     "user_message": "Обнаружена подделка." | "Признаков подделки не найдено."
  }
}
```

### 2.4. VALIDATOR_VERSION по движкам

| Движок | Версия | Файл |
|--------|--------|------|
| tbank_v6 | `6.0.0` | `tbank_v6/engine.py:11` |
| alfa_v1 | `1.0.0-future-safe` | `alfa_v1/engine.py:11` |
| sber_v1 | `1.0.0-future-safe` | `sber_v1/engine.py:21` |
| ozon_v1 | `1.0.0-future-safe` | `ozon_v1/engine.py:21` |
| gpb_v1 | `1.0.0-future-safe` | `gpb_v1/engine.py:21` |
| vtb_v1 | `1.0.0-future-safe` | `vtb_v1/engine.py:21` |
| sparse9_v1 | `1.0.0-future-safe` | `sparse9_v1/engine.py:12` |
| full_bank | `full_bank_2.0` | `full_bank.py:153` |
| legacy tbank | `0.6.3-v55` | `tbank_legacy.py:54` |

---

## 3. Идентификация и роутинг банков

`profiles.identify(text, producer)` матчит по маркерам текста + producer. `min_score` по умолчанию 0.45 (T-Bank 0.4).

### 3.1. Профили банков (`profiles.py:40-…`)

| key | Название | Маркеры (текст) | Producer | Движок |
|-----|----------|-----------------|----------|--------|
| `tbank` | Т-Банк | т-банк, тинькофф, tinkoff, tbank, tbank.ru, fb@tbank | jasperreports, openpdf | **tbank_v6** |
| `alfa` | Альфа-Банк | квитанция о переводе, сформирована, альфа-банк, alfa-bank | oracle bi publisher | **alfa_v1** |
| `alfa_ios` | Альфа-Банк | сформирована, квитанция о переводе | quartz pdfcontext | **spec engine** |
| `sber` | Сбербанк | чек по операции, перевод клиенту сбербанка, сбербанк, сбер | itext 2.1.7 | **sber_v1** |
| `ozon` | Ozon Банк | озон банк, ozon банк, ozon bank, служба поддержки ozon | skia/pdf, chromium | **ozon_v1** |
| `vtb` | Банк ВТБ | банк втб, втб (пао), исходящий перевод сбп, перевод на карту | openhtmltopdf | **vtb_v1** |
| `gazprombank` | Газпромбанк | газпромбанк, gazprombank, mailbox@gazprombank.ru | itext® 7, itext 2.1.7, jasperreports | **gpb_v1** |
| `wbbank` | ВБ Банк | вб банк, wildberries bank, перевод по сбп | openpdf, jasperreports | **sparse9_v1** |

Плюс sparse9-семейство: `wbbank`, `otp`, `psb`, `bchpb`, `raif`, `rocket`, `sovkom`, `uralsib`, `yandex` (`sparse9_profiles.py:50-60`).

### 3.2. Спец-переходы

- **GPB → Sber** (`gazprombank.py:57-101`): при Sber-корпусном hash или Sber-эмиттере → `sber.analyze()`
- **alfa_ios**: отдельный Quartz PDFContext шаблон → spec-движок

---

## 4. Движки-детекторы

Восемь движков + оркестратор hardening_v2 + full_bank fallback.

| Движок | Каталог | Tier-модель | FAKE условия |
|--------|---------|-------------|--------------|
| **tbank_v6** | `detector/tbank_v6/` | A + KNOWN + B-группы + IGNORED | A / KNOWN; **≥2 B-групп**; cross-doc; incomplete/not-receipt |
| **alfa_v1** | `detector/alfa_v1/` | HARD + KNOWN + DIAGNOSTIC + DELETED | HARD/KNOWN; cross-doc; diagnostics **не** дают FAKE |
| **sber_v1** | `detector/sber_v1/` | future-safe (как alfa) | HARD/KNOWN/cross-doc |
| **ozon_v1** | `detector/ozon_v1/` | future-safe + serializer stage | HARD/KNOWN/cross-doc |
| **gpb_v1** | `detector/gpb_v1/` | future-safe | HARD/KNOWN/cross-doc |
| **vtb_v1** | `detector/vtb_v1/` | future-safe | HARD/KNOWN/cross-doc |
| **sparse9_v1** | `detector/sparse9_v1/` | future-safe (MB-* коды, 9 банков) | HARD/KNOWN/cross-doc |
| **full_bank** | `detector/full_bank.py` | score + policy_v5 | `finalize_verdict()` |
| **hardening_v2** | `detector/hardening_v2/` | глобальные G-правила | hard fake (95) / unknown doc (0) |

Файловая структура каждого v1/v6 движка: `engine.py`, `stages.py`, `rules.py`, `verdict.py`, `types.py`, `explain.py`, `__init__.py` (+ `rollout.py` у v1, `known_signatures.py` у tbank_v6).

### 4.1. Rollout (какой результат возвращается пользователю)

| Банк | Env | Default |
|------|-----|---------|
| Alfa | `ALFA_V1_ROLLOUT` | shadow |
| Sber | `SBER_V1_ROLLOUT` | shadow |
| Ozon | `OZON_V1_ROLLOUT` | shadow |
| GPB | `GPB_V1_ROLLOUT` | shadow |
| VTB | `VTB_V1_ROLLOUT` | shadow |
| Sparse9 | `SPARSE9_V1_ROLLOUT` + `SPARSE9_{BANK}_V1_ROLLOUT` | shadow |
| **T-Bank** | — | **100% v6** |

В shadow-режиме v1 считается, но пользователю возвращается legacy-вердикт; v1 пишется в `details.*_v1_shadow`.

---

## 5. Система вердиктов и tiers

### 5.1. T-Bank v6 (`tbank_v6/verdict.py:33-65`)

`compute_verdict()` → `ФЕЙК` если:
- `not analysis_complete` → `[ANALYSIS_NOT_COMPLETED]`
- `not_a_tbank_receipt` → `[NOT_TBANK_RECEIPT]`
- любой `known_fake_flags` или `hard_flags` (decisive)
- **≥2 различных tier-B supporting-групп**
- `cross_document_identity_conflict` → `OPERATION_ID_REUSED`

Иначе → `ЧИСТО`, score 0.

`ingest_flag()` маршрутизирует: KNOWN → `known_fake_flags`; A/HARD → `hard_flags`; B → `supporting_flags`; иначе → `ignored_observations`.

### 5.2. v1-движки (future-safe)

`FAKE_THRESHOLD = 60`. `ФЕЙК`: incomplete, `not_<bank>_receipt`, любой HARD/KNOWN, или cross-doc conflict. **DIAGNOSTIC-коды никогда не дают FAKE в одиночку** (нет tier-B агрегации, в отличие от tbank_v6).

### 5.3. full_bank + policy_v5

`finalize_verdict()` → `aggregate_policy()` (policy v5.2): `ФЕЙК` если любой Tier A **или** ≥2 различных Tier B групп. Fallback: `forgery_score_from_flags()` веса 50/65/95. `TIER_A_CODES` / `TIER_B_CODES` / `TIER_C_CODES` в `policy_v5.py`.

### 5.4. hardening_v2

| Функция | Вердикт | Score |
|---------|---------|-------|
| `hard_fake_result` | ФЕЙК | 95 |
| `unknown_document_result` | НЕИЗВЕСТНЫЙ ДОКУМЕНТ | 0 |
| `apply_v2_priority` | может понизить ФЕЙК банка → ЧИСТО если только diagnostic-флаги | 0 |

---

## 6. Полный каталог правил T-Bank v6

### 6.1. Tier A / HARD (один флаг = ФЕЙК) — `tbank_v6/rules.py:10-103`

**Container / structure:**
`ANALYSIS_NOT_COMPLETED`, `NOT_TBANK_RECEIPT`, `PDF_STRUCTURE_INVALID`, `MULTIPLE_PDF_HEADERS`, `TRAILER_INVALID`, `XREF_OFFSET_INVALID`, `MULTIPLE_STARTXREF_PRESENT`, `MULTIPLE_EOF_PRESENT`, `MULTIPLE_XREF_PRESENT`, `PREV_TRAILER_PRESENT`, `INCREMENTAL_UPDATE_PRESENT`, `DUPLICATE_ACTIVE_OBJECT_DEFINITION`, `BROKEN_OBJECT_STRUCTURE`, `TRAILING_DATA_AFTER_EOF`, `OBJECT_GRAPH_INCONSISTENT`

**Streams:**
`STREAM_DECOMPRESSION_FAILED`, `STREAM_LENGTH_MISMATCH`, `UNEXPECTED_STREAM_FILTER`

**Active content:**
`JAVASCRIPT_PRESENT`, `ACTIVE_CONTENT_PRESENT`, `OPENACTION_PRESENT`, `DANGEROUS_ACTION_PRESENT`, `EMBEDDED_FILE_PRESENT`, `EMBEDDED_PAYLOAD_PRESENT`, `ACROFORM_PRESENT`, `XFA_PRESENT`

**Content / visibility:**
`TBANK_BT_ET_MISMATCH`, `TBANK_CONTENT_STREAM_EDIT`, `TEXT_LAYER_INCONSISTENT`, `BROKEN_CYRILLIC_MAPPING`, `TEXT_EXTRACTION_MAPPING_ANOMALY`, `UNICODE_MAPPING_INVALID`, `OVERLAY_DETECTED`, `OVERLAY_TEXT_LAYER`, `RECEIPT_TEXT_LAYER_MISSING`

**Fonts / glyphs:**
`USED_CID_MISSING_FROM_CMAP`, `USED_CID_MISSING_FROM_W`, `USED_CID_CMAP_MISMATCH`, `CMAP_W_MISMATCH`, `CMAP_INVALID`, `FONTFILE2_CID_MISSING`, `FONTFILE2_MISSING`, `MISSING_FONT_OBJECT`, `MISSING_WIDTH_TABLE`, `W_ARRAY_PRETTY_PRINTED`, `W_ARRAY_SERIALIZATION_ANOMALY`, `PDF_TTF_BBOX_CROSS_LAYER_MISMATCH`, `BROKEN_GLYPH_ZERO_LENGTH`, **`USED_CID_EMPTY_GLYPH`**, **`GLYPH_SLOT_TRANSPLANT`**, **`TBANK_TEXT_GLYPH_PARITY`**, `GLYPH_BBOX_IMPOSSIBLE`, `LOCA_TABLE_BROKEN`, `GLYPH_OUTLINE_MISMATCH`, `F3_NOT_ALSRUBL`, `TBANK_RUBLE_GLYPH_SPACING`

**Semantics / SBP:**
`SBP_CIPHER_MISSING`, `SBP_CIPHER_STRUCTURE`, `SBP_CIPHER_TIMESTAMP`, `SBP_CIPHER_REFERENCE`, `SBP_ROUTE_FIELD_CONTAMINATION`, **`SBP_CONTROL_TRIPLE_MISMATCH`**, **`SBP_LINKED_TUPLE_CONFLICT`**, `SBP_GRAMMAR_SUFFIX_PROFILE`, `TBANK_SBP_GEOMETRY_MISMATCH`, `TBANK_GLYPH_RENDER_GEOMETRY_MISMATCH`, `FIELD_FORMAT_INVALID`, `STRING_FIELD_STRUCTURE_ANOMALY`, `FIELD_ORDER_MISMATCH`, `FIELD_SET_MISMATCH`, `MISSING_REQUIRED_FIELD_BLOCK`, `AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS`, `OPERATION_ID_REUSED`

**Known signatures / provenance:**
`TBANK_KNOWN_GENERATOR_SKELETON`, `TBANK_KEYWORDS_GENERATION_MISMATCH`, `TBANK_INFO_KEYWORDS_LEX_MISMATCH`, `MIXED_FLATE_SERIALIZER_PROVENANCE`, `TBANK_DEFLATE_PROFILE_MISMATCH`, `TBANK_FONT_CID_CLOSURE_VIOLATION`, `TBANK_RECEIPT_NUMBER_FORMAT`, `TBANK_TRAILER_ID_REUSED`, `TBANK_STREAM_INTEGRITY_VIOLATION`, `TBANK_FONT_TABLE_INTEGRITY_VIOLATION`, `TTF_CHECKSUM_ADJUSTMENT_INVALID`, `TTF_HMTX_COUNT_MISMATCH`, `W_MISSING_CID`

### 6.2. KNOWN_FAKE (`rules.py:105-109`)

`K-FONT-001`, `K-FONT-002`, `KNOWN_FAKE_SBP_GRAMMAR_COMBINATION`, `TBANK_REASSEMBLED_BANK_ASSETS`

### 6.3. Tier B supporting-группы (`SUPPORTING_GROUPS`, `rules.py:112-132`)

| Код | Группа |
|-----|--------|
| `FOREIGN_PRODUCER` | B6_metadata_version |
| `PDF_MODDATE_EDITED` | B6_metadata_version |
| `TBANK_SHELL_PRODUCER_MISMATCH` | B6_metadata_version |
| `TBANK_SHELL_CREATOR_MISMATCH` | B6_metadata_version |
| `TBANK_SHELL_SUBJECT_MISMATCH` | B6_metadata_version |
| `STREAM_COMPRESSION_RATIO_OUTLIER` | B1_serializer_container |
| `DECODED_STREAM_SIZE_OUTLIER` | B1_serializer_container |
| `STREAM_FILTER_ANOMALY` | B1_serializer_container |
| `TTF_NUMGLYPHS_MISMATCH` | B5_source_fonts |
| `TTF_HEAD_ANOMALY` | B5_source_fonts |
| `TTF_HMTX_PROFILE_SHIFT` | B5_source_fonts |
| `UNUSED_CID_PRESENT` | B5_source_fonts |
| `CMAP_EXTRA_SYMBOLS` | B5_source_fonts |
| `FONT_GLOBAL_TABLES_FOREIGN_SUBSETTER` | B5_font_rebuilder |
| `STATIC_EDITABLE_DIGIT_SUBSET_F2` | B5_font_rebuilder |
| `KNOWN_FAKE_FONT_REBUILDER_SIGNATURE` | B5_font_rebuilder |
| `EXTRA_UNUSED_GLYPHS_F1_F2` | B5_font_rebuilder |
| `TBANK_TEXT_LAYOUT_FINGERPRINT` | content_grammar_layout |
| `SBP_PROFILE_EMPIRICAL` | content_grammar_sbp |
| `SBP_PROFILE_EPOCH_MISMATCH` | content_grammar_sbp_epoch |
| `RECEIPT_STEM_REUSE_CONFLICT` | cross_document_receipt_stem |

**Правило:** ФЕЙК только при **≥2 различных группах**. Одна группа (например только `content_grammar_sbp`) → остаётся ЧИСТО. В частности, `SBP_PROFILE_EPOCH_MISMATCH` и `RECEIPT_STEM_REUSE_CONFLICT` по отдельности не блокируют документ, но их комбинация даёт ФЕЙК.

### 6.4. IGNORED (не влияют на вердикт) — `rules.py:135-199`

Render-forgery коды (`TBANK_RENDER_STRUCTURAL_FORGERY`, `TBANK_FONT_RENDER_FORGERY`, `TBANK_REASSEMBLY_FORGERY`, `TBANK_LAYERED_PROFILE_FORGERY`), template-drift (`TBANK_TEMPLATE_*`), per-font drift (`TBANK_F1/F2/F3_*`), `FF2_SUBSET_UNKNOWN`, `CMAP_BFRANGE_ANOMALY`, `TOUNICODE_PROFILE_SHIFT`, `CONTENT_STREAM_PROFILE_MISMATCH`, `PROFILE_CLUSTER_OUTLIER`, `FONT_AUTH_FOREIGN_FONT` и `_FORENSICS_STATS_ONLY`. Эти коды — реализация политики «новизна ≠ подделка».

---

## 7. T-Bank pipeline (стадии)

`run_pipeline(pdf_bytes, file_hash)` (`tbank_v6/stages.py:682-717`). Ранний выход при `analysis_complete=False`.

| # | Стадия | completed_checks | Что делает |
|---|--------|------------------|------------|
| 1 | `_stage_intake` | intake | лимит 8 000 000 байт |
| 2 | `_stage_preflight` | raw_preflight | `validate_pdf_structure`, incremental updates, xref; encrypted → stop |
| 3 | `_stage_streams` | streams | compression; A для decompress/length, B для outliers |
| 4 | `_stage_active_content` | active_content | JS/XFA/OpenAction/embedded |
| 5 | `_stage_content_ast` | content_ast | BT/ET баланс, content-edit trace, skeleton hash |
| 6 | `_stage_layout_fingerprint` | layout_fingerprint | T-TBANK-TEXT-LAYOUT-FINGERPRINT-001 |
| 7 | `_stage_fonts` | fonts_cmap_glyph | K-FONT-001/002, `run_pdf_forensics`, F3 |
| 8 | `_stage_internal_serialization` | internal_serialization | deflate, stream integrity, CID closure, **used-glyph integrity**, **slot transplant**, atlas, font tables, receipt format, trailer ID reuse |
| 9 | `_stage_metadata` | metadata_generation | info keywords lex, keywords generation |
| 10 | `_stage_semantics` | semantic_geometry | channel/subtype, text semantics, SBP, linked tuple, profile epoch, receipt-stem reuse, anti-edit |
| 11 | `_stage_parity` | differential_parity | fitz vs parser SBP-ID |
| 12 | — | cross_document_intelligence | trailer ID reuse / opid reuse |

Порядок вызова T-Bank модулей в стадии 8 (`stages.py:194-237`):
`check_deflate_profile` → `check_stream_integrity` → `check_font_cid_closure` → **`check_tbank_used_glyph_integrity`** → **`check_glyph_slot_transplant`** → `check_tbank_glyph_atlas` → `check_font_table_integrity` → `check_receipt_format` → `check_trailer_id_reuse`.

---

## 8. T-Bank модули-детекторы (детально)

Базовый gate почти для всех: `claims_confirmed_tbank_profile()` (`tbank_jasper_profile.py:20-45`) — Subject содержит `/reports/IB/Receipt`, Creator = `JasperReports Library version 6.20.3`, Producer = `OpenPDF 1.3.30.jaspersoft.2`. `PROFILE_ID = "jasper_6.20.3_openpdf_1.3.30_ib_receipt"`.

| Модуль | RULE_ID | HARD_CODE(s) | Что проверяет |
|--------|---------|--------------|---------------|
| `tbank_sbp_content.py` | K-TBANK-SBP-CONTENT-002 / TIME-001 / ROUTE-FIELD-001 / CONTROL-LINK-001 / LINKED-TUPLE-001 / ROUTE-MARKER-001 / PROFILE-EMPIRICAL-001 | `SBP_CIPHER_*`, `SBP_ROUTE_FIELD_CONTAMINATION`, `SBP_CONTROL_TRIPLE_MISMATCH`, `SBP_LINKED_TUPLE_CONFLICT`, `SBP_GRAMMAR_SUFFIX_PROFILE`, `KNOWN_FAKE_SBP_GRAMMAR_COMBINATION`, `SBP_PROFILE_EMPIRICAL` | структура/грамматика/timestamp/полная связность SBP ID (см. §9) |
| `tbank_sbp_epoch_reuse.py` | T-TBANK-SBP-PROFILE-EPOCH-001 / T-TBANK-RECEIPT-STEM-REUSE-001 | `SBP_PROFILE_EPOCH_MISMATCH`, `RECEIPT_STEM_REUSE_CONFLICT` (tier B) | исторический период class+bank5+suffix и повторное использование первых трёх трёхзначных блоков номера квитанции |
| `tbank_sbp_geometry.py` | K-TBANK-SBP-GEOMETRY-001 | `TBANK_SBP_GEOMETRY_MISMATCH` | правая граница SBP-ID по raw content stream vs колонка R≈250, подтверждение fitz |
| `tbank_glyph_atlas.py` | K-TBANK-GLYPH-ATLAS-001 (v3.0.0) | `USED_CID_MISSING_FROM_CMAP`, `BROKEN_GLYPH_ZERO_LENGTH`, `CMAP_W_MISMATCH`, `GLYPH_OUTLINE_MISMATCH`, `TBANK_GLYPH_RENDER_GEOMETRY_MISMATCH` | Unicode→CID→GID→glyf→hmtx→/W→fitz cross-layer atlas |
| `tbank_used_glyph_integrity.py` | A-FONT-USED-CID-EMPTY-GLYPH-001 / A-VIS-TEXT-GLYPH-PARITY-001 | `USED_CID_EMPTY_GLYPH`, `TBANK_TEXT_GLYPH_PARITY` | каждый used CID имеет непустой glyf; decoded text == fitz render для критических полей |
| `tbank_glyph_slot_transplant.py` | A-FONT-GLYPH-SLOT-TRANSPLANT-001 | `GLYPH_SLOT_TRANSPLANT` | outline символа в чужом GID / LSB≠xMin / hmtx слота-приёмника |
| `tbank_deflate_profile.py` | K-TBANK-DEFLATE-PROFILE-001 | `TBANK_DEFLATE_PROFILE_MISMATCH` | DEFLATE-профиль потока vs Java Deflater OpenPDF |
| `tbank_flate_profile.py` | — | — | enumerate Flate streams, decoded bytes, Java canonical match; точные роли page/F1/F2/F3/ToUnicode/image через PDF object graph |
| `tbank_stream_serializer.py` | K-TBANK-STREAM-SERIALIZER-001 | `MIXED_FLATE_SERIALIZER_PROVENANCE` | выборочное пересжатие page content либо split: images+F3 canonical, а page+F1/F2 FontFile2+ToUnicode одновременно non-canonical |
| `tbank_stream_integrity.py` | K-TBANK-STREAM-INTEGRITY-001 | `TBANK_STREAM_INTEGRITY_VIOLATION` | /Length (tol >2), zlib header 0x78, чистый EOF |
| `tbank_font_cid_closure.py` | K-TBANK-FONT-CID-CLOSURE-001 | `TBANK_FONT_CID_CLOSURE_VIOLATION` (+ underlying) | замыкание CID/CMap/W/FontFile2 |
| `tbank_font_table_integrity.py` | K-TBANK-FONT-TABLE-INTEGRITY-001 | `TBANK_FONT_TABLE_INTEGRITY_VIOLATION` | numGlyphs, glyph bbox, loca, checksumAdjustment, hmtx count |
| `tbank_receipt_format.py` | K-TBANK-RECEIPT-FORMAT-001 | `TBANK_RECEIPT_NUMBER_FORMAT` | номер `^1-\d{3}-\d{3}-\d{3}-\d{3}$` |
| `tbank_reassembled_subset.py` | K-TBANK-REASSEMBLED-SUBSET-001 | `TBANK_REASSEMBLED_BANK_ASSETS` (KNOWN) | доверенные F1/F2 glyph + F3/images, но неизвестная полная сборка и подтверждённая generator provenance |
| `tbank_id_reuse.py` | K-TBANK-ID-REUSE-001 | `TBANK_TRAILER_ID_REUSED` | одна пара trailer /ID + разный контент (SQLite `tbank_id_reuse.db`, лимит 2000) |
| `tbank_keywords_generation.py` | K-TBANK-KEYWORDS-GENERATION-001 | `TBANK_KEYWORDS_GENERATION_MISMATCH` | third token: до 10.07.2026 `991`, после — `DOCS-2035` |
| `tbank_info_keywords_lex.py` | K-TBANK-INFO-KEYWORDS-LEX-001 | `TBANK_INFO_KEYWORDS_LEX_MISMATCH` | `/Keywords(` без пробела; фейк `/Keywords[ \t\r\n]+\(` |
| `tbank_text_layout_fingerprint.py` | T-TBANK-TEXT-LAYOUT-FINGERPRINT-001 | `TBANK_TEXT_LAYOUT_FINGERPRINT` (tier B) | правая колонка R=250pt, hard только при dual-parser + структурном нарушении |
| `tbank_spec.py` | chadgpt-plus v0.4.0 | `F3_NOT_ALSRUBL`, `AMOUNT_MISMATCH_*`, `OVERLAY_DETECTED`, table codes, layout codes | §2-10 спека |
| `tbank_invariants.py` | — | — | загрузка `tbank_invariants.json`, channel envelopes |
| `tbank_legacy.py` | — (v0.6.3-v55) | `TBANK_KNOWN_GENERATOR_SKELETON`, `TBANK_SBP_STREAM_FIELD_ORDER`, `TBANK_RUBLE_GLYPH_SPACING`, `TBANK_CONTENT_STREAM_EDIT` | НЕ используется в v6 (legacy) |
| `font_layers.py` | — | `TOTAL_LABEL_FONT_LAYER_MISMATCH`, `USED_CID_*`, `CMAP_W_MISMATCH`, `FONT_SWITCH_INSIDE_WORD` и др. | font/amount слои, money cap 50M ₽ |
| `glyf_fingerprint.py` | — | `GLYPH_PIX_*`, `GLYPH_TTF_F1/F2/F3` | reference glyphs `glyf_reference.json` |
| `pdf_forensics.py` | — | множество (см. `_TBANK_PROFILE`) | deep forensic layers, risk buckets |
| `sbp_cipher.py` | — | `SBP_CIPHER_*` | generic NSPK cipher (все банки) |
| `java_deflater.py` | — | — | Java canonical zlib (`tools/java_deflater/CanonicalDeflater`) |

### 8.1. Ключевые пороги модулей

- **SBP geometry:** `_TOLERANCE_PT = 0.05`; `_DEFAULT_R = 250.0`, `_R_MIN = 235.0`, `_R_MAX = 265.0`; fitz confirm slack 0.15pt; F1 filter `8.5 ≤ font_size ≤ 9.5`
- **Glyph atlas:** `_RENDER_TOL_PT = 0.75`; `_MAX_POINTS_STORED = 512`; `CMAP_W_MISMATCH` при `|hmtx − /W| > 2`
- **Layout fingerprint:** `_TARGET_RIGHT_PT = 250.0`; `_TOLERANCE_ROUND/HARD = 0.05`; `_TOLERANCE_AMOUNT = 1.0`; `_TOLERANCE_DUAL = 0.15`; `_CROPBOX_RIGHT_DEFAULT = 280.0`
- **Stream integrity:** /Length tol `>2`; zlib header `0x78`
- **Stream serializer (старый path):** `unique_originals = 119`; требуется ≥9 canonical peers; `original_collisions == 0`
- **Stream serializer (усиленный path):** ровно 4 image streams + F3 FontFile2 должны совпасть с `decoded→Java CanonicalDeflater`; page content, F1 FontFile2, F1 ToUnicode, F2 FontFile2, F2 ToUnicode должны одновременно не совпасть. Размер, compression ratio и неизвестный hash в решении не участвуют
- **Used-glyph integrity:** labels x<80, values x>160; y-offset default −80.78; name regex `^[A-Za-zА-Яа-яЁё.\-\s]+$`

---

## 9. СБП ID: структура, грамматика, профили

### 9.1. Байтовая структура (32 символа) — `tbank_sbp_content.py`

| Slice | Поле | Значение |
|-------|------|----------|
| `[0]` | lead | `A` или `B` |
| `[1]` | enc_year_digit | UTC год mod 10 |
| `[2:5]` | enc_doy | UTC день года |
| `[5:7]` | enc_hour | UTC час |
| `[7:9]` | enc_min | UTC минута |
| `[9:11]` | enc_sec | UTC секунда (±1 от MSK) |
| `[11:14]` | ref3 | 3-символьный референс |
| `[14]` | route_marker | маркер маршрута |
| `[15]` | **control** | контрольный символ (связан с triple) |
| `[16]` | separator | всегда `0` |
| `[17]` | route_lead | `0` / `B` / `G` |
| `[17:19]` | sb_class | `00` / `B0` / `B1` / `G1` |
| `[19:22]` | slot | 3 цифры |
| `[22:26]` | profile_block | фикс `0011` |
| `[22:27]` | bank5 | `00116` / `00117` |
| `[26:32]` | suffix | 6 цифр (символ `[26]` общий с bank5) |

**Route→class:** `0`→{00}, `B`→{B0,B1}, `G`→{G1}.
**Time (K-TBANK-SBP-TIME-001):** UTC-ядро +3h → MSK, tolerance `delta ≤ 1` сек.

### 9.2. Правила SBP ID

| Код | Rule ID | Tier | Триггер |
|-----|---------|------|---------|
| `SBP_CIPHER_MISSING` | CONTENT-002 | A | нет opid |
| `SBP_CIPHER_STRUCTURE` | CONTENT-002 | A | len≠32, bad chars, profile_block≠0011 |
| `SBP_CIPHER_TIMESTAMP` | TIME-001 | A | MSK Δ>1s |
| `SBP_ROUTE_FIELD_CONTAMINATION` | ROUTE-FIELD-001 | A | separator/route/class несогласованы |
| `SBP_CONTROL_TRIPLE_MISMATCH` | CONTROL-LINK-001 | A | control ≠ корпусный для triple (marker,slot,suffix) |
| `SBP_LINKED_TUPLE_CONFLICT` | LINKED-TUPLE-001 | A | marker не согласован с подтверждённым tuple (class,bank5,control,slot,suffix) |
| `KNOWN_FAKE_SBP_GRAMMAR_COMBINATION` | ROUTE-MARKER-001 | KNOWN | bad marker + suffix `*60501` на wrong class |
| `SBP_GRAMMAR_SUFFIX_PROFILE` | ROUTE-MARKER-001 | A | `*60501` на не-B1/00117 |
| `SBP_PROFILE_EMPIRICAL` | PROFILE-EMPIRICAL-001 | B | marker/suffix вне корпуса для (class,bank5) |
| `SBP_PROFILE_EPOCH_MISMATCH` | PROFILE-EPOCH-001 | B | ID timestamp и видимая дата существенно позже завершившегося периода profile tuple |
| `RECEIPT_STEM_REUSE_CONFLICT` | RECEIPT-STEM-REUSE-001 | B | корпусный stem номера, но изменены последний блок, opid и дата |

### 9.3. K-TBANK-SBP-CONTROL-LINK-001 (наше правило)

Только для профилей `_CONTROL_LINK_TIER_A_PROFILES = {("00","00116"), ("B0","00116")}`. Для triple `(route_marker, slot, suffix)` control-символ `[15]` жёстко детерминирован корпусом. Если triple известен, но `control ≠ expected` → HARD `SBP_CONTROL_TRIPLE_MISMATCH`. Ловит clone-forgery, где хвост скопирован с оригинала, а control подставлен неверно (напр. `receipt_14.07.2026 (13)` — control `A` вместо `6`).

### 9.4. K-TBANK-SBP-LINKED-TUPLE-001

Обратная проверка полной шестикомпонентной связки:

```
sb_class + bank5 + route_marker + control + slot + suffix
```

Статическая карта `_CONFIRMED_LINKED_TUPLES` имеет ключ `(sb_class, bank5, control, slot, suffix)` и множество допустимых marker. Подтверждённая связка:

```python
("B1", "00117", "1", "013", "760501") -> {"1"}
```

При marker `8`, `2` или `3` → HARD `SBP_LINKED_TUPLE_CONFLICT`; при marker `1` правило не срабатывает. Проверка идёт **раньше** Tier-B empirical, поэтому подтверждённый tuple-конфликт не остаётся только наблюдением.

### 9.5. Эмпирические профили `_EMPIRICAL_PROFILES`

| (class, bank5) | corpus_n | markers | suffixes | control-link tier A |
|----------------|----------|---------|----------|---------------------|
| (G1, 00117) | 24 | {0,1} | {730902,770402,770901,791103} | нет |
| (00, 00116) | 9 | {0,1} | {640702,661101,670301,680301,681101} | **да** |
| (B1, 00117) | 20 | {0,1} | {700501,730501,760501,770302,770901,790502} | нет |
| (B0, 00116) | 2 | {6,7} | {680301} | **да** |

Каждый профиль содержит `triple_control` (map `(marker,slot,suffix)→control`) и `linked_tuples` (frozenset `(control,marker,slot,suffix)`). Полные дампы — Приложение A.

### 9.6. Grammar suffix `*60501` (ROUTE-MARKER-001)

`_SUFFIX_TAIL_B1_00117 = "60501"`; suffix с этим tail подтверждён только для B1/00117. `_SUFFIX_TAIL_FORBIDDEN = {("00","00116"), ("G1","00117")}`. Dual violation (bad marker + forbidden pair) → KNOWN combo.

### 9.7. Profile epoch + receipt-stem reuse

`tbank_sbp_epoch_reuse.py` загружает `atlas_data/tbank_sbp_epoch_stems.json`, построенный из 128 оригиналов:

- 17 временных профилей `(sb_class, bank5, suffix)`;
- 114 stems номера квитанции;
- максимальная дата корпуса: `2026-07-03`;
- исторический профиль `B1/00117/760501`: `2026-05-16`–`2026-05-19`, 4 образца.

`SBP_PROFILE_EPOCH_MISMATCH` возникает только для известного profile tuple, когда поколение завершилось относительно общего корпуса, а decoded ID→MSK и видимая дата обе более чем на 21 день позже последней даты профиля.

`RECEIPT_STEM_REUSE_CONFLICT`: номер `1-AAA-BBB-CCC-DDD` сворачивается в stem `1-AAA-BBB-CCC`. Флаг возникает, только если stem есть в оригинальном корпусе, но одновременно изменены `DDD`, operation ID и дата. Один новый номер или неизвестный stem ничего не доказывает.

Оба кода — разные Tier-B группы. Только их комбинация (либо другая независимая supporting-группа по общей политике v6) формирует ФЕЙК.

**Построение индекса:** `tools/build_tbank_sbp_epoch_stems.py`.

### 9.8. sbp_cipher.py (generic NSPK, все банки)

`_SBP_ID_RE = [AB][0-9A-Z]{31}`; `_CORE_SUFFIXES = {"00117","00116"}`; `_REF_MAX_LETTERS = 2`. Timestamp: `enc_doy = int(opid[1:5]) % 1000`, `real_utc = (dt.hour−3)%24`, doy tol >2, hour tol >3.

---

## 10. Шрифты и glyph-подсистема

### 10.1. Три шрифта

| Роль | Family | numGlyphs | upem | Назначение |
|------|--------|-----------|------|------------|
| F1 | TinkoffSans-Regular | 476 | 1000 | значения, ФИО, детали (9pt) |
| F2 | TinkoffSans-Medium | 479 | 1000 | «Итого» + крупная сумма (16pt) |
| F3 | ALSRubl | 23 | — | символ рубля `(i)Tj` |

F1 checksumAdjustment = `863796543` (при ng>200). F3 fontfile2 `(1874,1878)`, glyf `(342,346)`.

### 10.2. A-FONT-USED-CID-EMPTY-GLYPH-001

Для каждого реально использованного (через `_collect_used_by_font`) непробельного CID в F1/F2: получить Unicode (ToUnicode), GID (Identity), проверить loca[GID]:loca[GID+1]. Если glyph пустой (loca_len 0, contours 0, missing) → HARD `USED_CID_EMPTY_GLYPH`. Композитные (contours<0) считаются пустыми только при loca_len 0. Ловит `tsypin` (CID 259 «Ц», glyf 0), `zhuravlev` (CID 242 «Ж», glyf 0).

### 10.3. A-VIS-TEXT-GLYPH-PARITY-001

Для критических полей (отправитель/получатель): decoded Unicode из content stream != fitz-видимый текст → HARD `TBANK_TEXT_GLYPH_PARITY`.

### 10.4. A-FONT-GLYPH-SLOT-TRANSPLANT-001 (наше правило)

Канон `detector/atlas_data/tbank_glyph_slot_canon.json` (v1.0.0, 128 samples, F1 117 slots). Для used CID с каноном ловит:
- outline совпадает с каноном символа, но GID ≠ канонического
- `head.flags & 0x02` и `LSB ≠ glyph.xMin`
- outline перенесён, а hmtx/`/W` остались от слота-приёмника

→ HARD `GLYPH_SLOT_TRANSPLANT`. Регрессии: `zhuravlev` (Ж@241 canon 242, LSB 87≠xMin 28), `tsypin` (Ц@258 canon 259, LSB 50≠xMin 87). 0 FP на 128 оригиналах.

### 10.5. K-TBANK-GLYPH-ATLAS-001 v3

Цепочка Tj→CID→ToUnicode→GID→glyf→hmtx→/W→calc geometry→fitz. HARD только при доказанных межслойных противоречиях. Новый FontFile2 SHA сам по себе не банит. `TBANK_GLYPH_RENDER_GEOMETRY_MISMATCH` при Δ>0.75pt.

### 10.6. K-FONT-001/002 (known fake font packs)

- **K-FONT-001**: rebuilder A — head.modified ≈ CreationDate + bbox mismatch
- **K-FONT-002**: F2 glyf `e3bfdef6…` + loca `1d0acb89…` (0/128 originals)

`known_signatures.py::check_k_font_001`, `check_k_font_002`.

### 10.7. Важная семантика отсутствующего FontBBox

`PDF_TTF_BBOX_CROSS_LAYER_MISMATCH` допустим только когда **оба** значения существуют и численно различаются. Отсутствие профиля шрифта или пара `PDF FontBBox=None`, `TTF head=None` — недостаток данных, а не противоречие. Это исправлено после ложного срабатывания на оригинале `сбп т банк9.pdf`; после исправления файл даёт `ЧИСТО`, flags `[]`.

### 10.8. K-TBANK-REASSEMBLED-SUBSET-001

KNOWN `TBANK_REASSEMBLED_BANK_ASSETS` возникает только при одновременном выполнении пяти условий:

1. PDF точно заявляет JasperReports 6.20.3 + OpenPDF 1.3.30.jaspersoft.2 профиль Т-Банка.
2. Каждая реально использованная F1/F2 glyph-программа имеет точный `raw_glyf_hash` в доверенном glyph-атласе; неизвестный FontFile2 hash не используется.
3. Полный F3 FontFile2 и bundle ровно четырёх decoded image streams совпадают с доверенными статическими ресурсами.
4. Нормализованная комбинация `content AST + F1 used-set + F2 used-set + F1/F2 ToUnicode + F1/F2 /W` отсутствует среди 114 сочетаний из 128 оригиналов.
5. Файл уже находится в confirmed-fake series database либо его content-AST совпадает с versioned fingerprint `tbank_generator_content_ast_v1`.

Если хотя бы одно условие не доказано, правило молчит. Новый subset, новый hash, новая комбинация полей или неизвестный content AST сами по себе не дают ФЕЙК.

---

## 11. Корпусные профили и константы

### 11.1. `corpus_profiles.py` (PROFILE_VERSION `tbank_corpus_41_spec_2026_06`)

**TBANK_SHELL:** object_count 28, xref_count 1, eof_count 1, zlib_header `\x78\x9c`.

**CONTENT_PROFILE_SBP:** decoded 4350–4650, raw 1020–1100, bt_count 30, tj_count (33,34), tm_count 31, bfrange_count 2, bfchar_count 0.
**CONTENT_PROFILE_PHONE:** decoded 3350–3800, raw 860–980.
**CONTENT_PROFILE_CARD:** decoded 3600–3700, raw 870–900, bt_count 26, tj_count (26,27), tm_count 25.

**F1_CID_ENVELOPE:** (58, 77). **F2_CID_RANGE:** (7, 9). **F3_PROFILE:** num_glyphs 23.
**TTF_PROFILE:** f1_num_glyphs 476, f2_num_glyphs 479, units_per_em 1000, head_checksum_adj 863796543, tail_padding_bytes 2, f1_loca_len 954, f2_loca_len 960.

### 11.2. `pdf_forensics.py::_TBANK_PROFILE`

content_stream 3000–8000, text_ops_count 33, bfrange_min 30, glyph_counts {476,479}, cid_density_max 0.50, unused_glyph_ratio_max 0.48, zlib_header `\x78\x9c`, head_checksum_adj 863796543, hmtx_hashes {`f45b998da9da`,`6957d7a5e820`}, units_per_em 1000. Weight: HIGH=95, MEDIUM=65, LOW=30. Risk buckets: ≤20 LOW, ≤50 MEDIUM, else HIGH.

### 11.3. `glyf_fingerprint.py`

Anchor Y: total_label 106.61, commission_zero 203.22. Reference `glyf_reference.json` (source_count 124). Pixel scale 10, tolerance |Δy|>0.6 skip.

---

## 12. Атлас-данные

`detector/atlas_data/` (8 файлов) + legacy `detector/tbank_glyph_atlas.json` + `detector/glyf_reference.json`.

| Файл | Версия | rule_id | Содержимое |
|------|--------|---------|------------|
| `tbank_glyph_atlas_index.json` | 3.0.0 | K-TBANK-GLYPH-ATLAS-001 | total 426, render_stats (samples 230, max_delta 0.0), font_files map |
| `tbank_glyph_atlas_F1.json` | — | — | TinkoffSans-Regular, 225 глифов, ключи `unicode:cid` |
| `tbank_glyph_atlas_F2.json` | — | — | TinkoffSans-Medium, 120 глифов |
| `tbank_glyph_atlas_F3.json` | — | — | ALSRubl, 81 глиф |
| `tbank_subset_builder_atlas.json` | 3.0.0 | K-TBANK-GLYPH-ATLAS-001 | 213 наблюдений subset-builder |
| `tbank_glyph_slot_canon.json` | 1.0.0 | A-FONT-GLYPH-SLOT-TRANSPLANT-001 | corpus 128, F1 117 slots, per-slot outline/hmtx/xMin |
| `tbank_sbp_epoch_stems.json` | 1.0.0 | PROFILE-EPOCH-001 + RECEIPT-STEM-REUSE-001 | corpus 128, 17 profile epochs, 114 receipt stems, corpus_last_date 2026-07-03 |
| `tbank_reassembled_subset.json` | 1.0.0 | K-TBANK-REASSEMBLED-SUBSET-001 | 114 trusted assembly signatures, 1 F3 hash, 1 four-image bundle, generator content-AST provenance v1 |
| `tbank_glyph_atlas.json` (legacy) | 3.0.0 | K-TBANK-GLYPH-ATLAS-001 | 426 глифов, ключи `F1:unicode:cid` |
| `glyf_reference.json` | 1 | — | anchors + F1/F2/F3 glyf_md5 (source_count 124) |

Runtime предпочитает split `atlas_data/` (`tbank_glyph_atlas.py:38-41`), но legacy тоже деплоится.

**Сборка:** `tools/build_tbank_glyph_atlas.py` (atlas v3), `tools/build_glyph_slot_canon.py` (canon), `tools/build_tbank_sbp_epoch_stems.py` (epochs + receipt stems), `tools/build_tbank_reassembled_subset.py` (trusted complete assemblies/static assets).

---

## 13. Движки других банков

Каждый v1-движок — future-safe: только HARD/KNOWN/cross-doc дают ФЕЙК; DIAGNOSTIC не суммируются. Pipeline: intake → preflight → streams → active → content_ast → fonts → semantics → parity → cross_document_intelligence.

| Движок | NOT_*_RECEIPT | Префикс кодов | KNOWN код | Особенность |
|--------|---------------|---------------|-----------|-------------|
| alfa_v1 | NOT_ALFA_RECEIPT | ALFA_* | ALFA-KNOWN-FAKE-001 | iOS metadata conflict, parser parity |
| sber_v1 | NOT_SBER_RECEIPT | SBER_* | SBR-KNOWN-001 | card arithmetic, legacy doc, dynamic-in-static |
| ozon_v1 | NOT_OZON_RECEIPT | OZON_* | OZ-KNOWN-001 | `_stage_serializer_mix`, BDC/EMC, tag struct, cross-bank tail |
| gpb_v1 | NOT_GAZPROMBANK_RECEIPT | GPB_* | GPB-KNOWN-001 | total arithmetic; Sber reroute |
| vtb_v1 | NOT_VTB_RECEIPT | VTB_* | VTB-KNOWN-001 | CIDToGID identity, ToUnicode used-set |
| sparse9_v1 | NOT_BANK_RECEIPT | MB_* | — (нет KNOWN set) | 9 банков, bank_key параметризация, PDF 2.0 профиль |

Общие структурные/шрифтовые коды идентичны tbank (USED_CID_*, CMAP_*, FONTFILE2_*, GLYPH_OUTLINE_MISMATCH, LOCA_TABLE_BROKEN и т.д.).

---

## 14. hardening_v2 (пре-слой)

Для не-T-Bank банков (и global preflight для всех). Файлы: `engine.py`, `document_router.py`, `global_rules.py`, `global_preflight.py`, `verdict_merge.py`, `status_engine.py`, `bank_contracts.py`, `g_graph_003.py`, `master.json`.

**Global hard set** (`global_rules.py:62-75`): `PDF_STRUCTURE_INVALID`, `MULTIPLE_PDF_HEADERS`, `TRAILER_INVALID`, `XREF_OFFSET_INVALID`, `MULTIPLE_STARTXREF_PRESENT`, `MULTIPLE_EOF_PRESENT`, `INCREMENTAL_UPDATE_PRESENT`, `JAVASCRIPT_PRESENT`, `ACTIVE_CONTENT_PRESENT`, `EMBEDDED_FILE_PRESENT`, `EMBEDDED_PAYLOAD_PRESENT`, `XFA_PRESENT`.

**Дополнительные:** `AMOUNT_ARITHMETIC_MISMATCH` (G-SEM-001), `GLOBAL_TEXT_GLYPH_RENDER_MISMATCH` (G-FONT-005), `G_GRAPH_003_LATENT_CONFLICT` (G-GRAPH-003), `STATUS_INTERNAL_CONFLICT` (G-STATUS-002).

`document_router.route_document()` — классификация statement/certificate/receipt, issuer match, submethod. `RECEIPT_NEW_PROFILE` для неизвестных.

---

## 15. Telegram-бот

### 15.1. Стек

| Item | Значение |
|------|----------|
| Framework | aiogram 3.x (`bot.py`) |
| Entry | `asyncio.run(main())` → `dp.start_polling(bot)` |
| PDF | PyMuPDF (`fitz`) |
| Токен | `.env` → `BOT_TOKEN` (нет в коде; missing → RuntimeError) |
| Logging | INFO, `%(asctime)s | %(levelname)s | %(message)s` |
| Config | inline в `bot.py` + `.env` (нет `config_bot.py`) |

### 15.2. Константы (`bot.py`)

`FREE_CHECKS_PER_DAY = 999`, `STARS_PER_CHECK = 1`, `FAKE_THRESHOLD = 60`, `SUSPICIOUS_THRESHOLD = 25`, `REQUIRED_CHANNEL = @proton_newss`, `ARCHIVE_ENABLED` (env, default 1), `ARCHIVE_SKIP_USERNAMES = {kronlead, acterichee}`, `SUPPORT_USERNAME = @acterichee`, `VERBOSE_USERNAMES = {kronlead}`, stale receipt 7 дней.

### 15.3. Хендлеры

`/start`, `/help`, `/balance`, `/block` `/unblock` `/blocklist` `/stats` (privileged), кнопки `✅ Проверить чек` / `🏦 Проверяемые банки` / `📧 Почта` / `💬 Поддержка`, `handle_document` (основной PDF-путь), `report_fake_cb` / `report_genuine_cb`, Telegram Stars payment, `BlocklistMiddleware` (default blocked `p2plogger`).

### 15.4. Поток PDF (`handle_document`, `bot.py:977-1085`)

1. gate `.pdf`/`application/pdf` → 2. `⏳ Проверяю...` → 3. download → 4. magic `%PDF-` → 5. `route_bank(pdf_bytes)` → 6. reputation (T-Bank full / прочие `check_known_fake`) → 7. merge score → 8. `_normalize_binary_result` → 9. `record_seen` → 10. analytics → 11. `_format_result` → 12. inline button → 13. archive → 14. edit message.

### 15.5. Форматы сообщений

**Default:** `<code>{поля чека}</code>` + строка вердикта:
- `✅ Оригинал (Банк)` / `❌ Подделка (Банк)` / `⚪ Неизвестный документ` / `❓ Не распознан` / `❌ Перевод не выполнен` / `⚠️ Устаревший чек`

**Verbose (kronlead / ADMIN_IDS):** engine-specific expert report (tbank_v6/alfa_v1/…) с блоками «Почему:» / «Технически:» / рекомендация.

**Archive caption:** `🗂 Архив проверки / 👤 user / 🏦 bank / 📌 verdict (score) / 🆔 hash[:16] / ⚠️ first_flag`.

---

## 16. Reputation / analytics / blocklist

- **reputation** — T-Bank: полный `reputation.check()`; прочие: `check_known_fake()`. `record_seen()` нейтрален (не влияет на вердикт).
- **analytics** — `analytics.log_check(...)`.
- **blocklist.py** — `data/blocked_users.json`, default `p2plogger`; управление `/block` `/unblock` `/blocklist`.
- **tbank_id_reuse.db** — SQLite для trailer /ID reuse (лимит 2000 записей).

---

## 17. Деплой и инфраструктура

### 17.1. Сервер

| Параметр | Значение |
|----------|----------|
| Host | `85.192.40.122` |
| User | `root` |
| SSH key | `~/.ssh/pdfbot_deploy` |
| Remote dir | `/root/pdf-checker-bot` |
| Сервисы | `pdfbot` (бот), `pdfmail` (почта, restart только `redeploy.py`) |
| Config | `.deploy.env` → `deploy_config.py` |

### 17.2. Скрипты деплоя

| Скрипт | Область | Сервисы |
|--------|---------|---------|
| `tools/_deploy_v6.py` | T-Bank v6 стек, включая `tbank_sbp_epoch_reuse.py`, все atlas_data и java_deflater | pdfbot |
| `deploy_bot.py` | bot.py + explain.py | pdfbot |
| `redeploy.py` | 128+ файлов + bank_specs/symbol_libraries/font_libraries/tbank_template | pdfbot + pdfmail |

`_deploy_v6.py`: создаёт remote-каталоги, заливает все `atlas_data/*.json`, компилирует Java (`javac CanonicalDeflater.java`, `javac not found` не блокирует), `python3 -m py_compile`, `systemctl restart pdfbot`, health-check `systemctl is-active` + `journalctl -n 5`.

**Отсутствуют:** `requirements.txt`, `README`, `tests/`, `config_bot.py`. Deps (из импортов): aiogram, python-dotenv, PyMuPDF, paramiko, fontTools.

---

## 18. Регрессии и тестовые корпуса

Формальных pytest нет — валидация через `tools/_*regression*.py`.

| Скрипт | Что проверяет | Корпус / кейсы |
|--------|---------------|----------------|
| `_v6_regression.py` | T-Bank v6 | REG-O-002 Receipt(6)→ЧИСТО, REG-O-004 receipt_12.07(4)→ЧИСТО, REG-F-002 receipt_10.07(28)→ФЕЙК, 128 корпус→ЧИСТО, tbank_all25 fakes→ФЕЙК |
| `_tbank_empirical_regression.py` | SBP control-link + empirical | 5 кейсов: (8)/(13)→ФЕЙК `SBP_CONTROL_TRIPLE_MISMATCH`, (9)→ЧИСТО `SBP_PROFILE_EMPIRICAL`, Receipt(1)/(2)→ЧИСТО |
| `_tbank_sbp_route_marker_regression.py` | ROUTE-MARKER-001 | супер фейк/фейк/фейк(1)→ФЕЙК, ≥33 корпус-профилей→ЧИСТО |
| `_tbank_used_glyph_regression.py` | empty-glyph + transplant | zhuravlev/tsypin→ФЕЙК `GLYPH_SLOT_TRANSPLANT`, 01/03/04/05/06/07→ЧИСТО, корпус→0 FP |
| `_tbank_glyph_atlas_regression.py` | GLYPH-ATLAS-001 | Receipt(1)/(2)→ЧИСТО, (8)/(9) без atlas hard |
| `_tbank_layout_regression.py` / `_stage2` | layout fingerprint | Receipt(1)/(2), корпус→ЧИСТО |
| `_sbp_time_regression.py` | timestamp | корпус 0 hits, Receipt(2) чисто |
| `_stream_serializer_regression.py` | STREAM-SERIALIZER-001 | корпус 0 FP, receipt_13.07 tough, mutation_*.pdf→ФЕЙК |
| `_alfa_v1_regression.py` | alfa | `чеки\альфа` 40→ЧИСТО |
| `_sber_v1_regression.py` | sber | `Новая папка (2)` 22→ЧИСТО |
| `_ozon_v1_regression.py` | ozon | `озон чекии` 32→ЧИСТО |
| `_vtb_v1_regression.py` | vtb | `втб оригинал` 15→ЧИСТО |
| `_gpb_v1_regression.py` | gpb | `газпромбанк оригинал` 5 GPB→ЧИСТО, 2 Sber→reroute |
| `_sparse9_v1_regression.py` | 9 банков | `_sparse9_corpus_full/` 21 PDF→ЧИСТО |
| `_hardening_v2_regression.py` | не-T-Bank | 97 оригиналов 5 папок→ЧИСТО/ОРИГИНАЛ |

**Основной корпус:** `C:\Users\fanis\OneDrive\Desktop\чеки\т банк` (128 PDF). Тест-фейки: `samaya-ohuenaya-versiya\output\tbank_all25`, `ЗАПАСКА 13.07.26\output\test_sbp_10`.

---

## 19. Карта файлов проекта

### Корень
`bot.py`, `blocklist.py`, `deploy_config.py`, `deploy_bot.py`, `redeploy.py`, `test_run.py`, `.deploy.env`.

### detector/ — движки
`__init__.py` (route), `profiles.py` (registry), `tbank.py`/`alfa.py`/`sber.py`/`ozon.py`/`vtb.py`/`gazprombank.py`/`sparse9.py` (обёртки), `full_bank.py`, `verdict.py`, `policy_v5.py`, `rollout.py`, `reputation.py`, `analytics.py`.

Подпакеты: `tbank_v6/`, `alfa_v1/`, `sber_v1/`, `ozon_v1/`, `gpb_v1/`, `vtb_v1/`, `sparse9_v1/`, `hardening_v2/`.

### detector/ — T-Bank модули
См. таблицу §8. В актуальный стек добавлен `tbank_sbp_epoch_reuse.py`.

### detector/atlas_data/ + data
8 atlas JSON, включая `tbank_sbp_epoch_stems.json` и `tbank_reassembled_subset.json`; также `tbank_glyph_atlas.json`, `glyf_reference.json`, `tbank_invariants.json`, `tbank_id_reuse.db`, `bank_corpus.json`.

### tools/
122 файла: build_* (atlas, canon, glyph library, symbol library, skeletons), analyze_* (sbp cipher), `_*regression*.py` (15), probe/quick-check скрипты, `java_deflater/CanonicalDeflater.java`, `_deploy_v6.py`, `remote_exec.py`.

### docs/
`deep_scan_report.md/.json`, `editing_traces_report.md`, `alfa_sbp_cipher_analysis.md`.

---

## 20. История добавленных правил

| Дата | Правило | Коды |
|------|---------|------|
| — | K-TBANK-SBP-ROUTE-MARKER-001 | `SBP_GRAMMAR_SUFFIX_PROFILE`, `KNOWN_FAKE_SBP_GRAMMAR_COMBINATION` |
| — | K-TBANK-SBP-PROFILE-EMPIRICAL-001 | `SBP_PROFILE_EMPIRICAL` (tier B) |
| — | K-TBANK-GLYPH-ATLAS-001 v3 | atlas cross-layer |
| 14.07.2026 | **K-TBANK-SBP-CONTROL-LINK-001** | `SBP_CONTROL_TRIPLE_MISMATCH` — control↔triple для 00/00116, B0/00116 |
| 14.07.2026 | **A-FONT-USED-CID-EMPTY-GLYPH-001** | `USED_CID_EMPTY_GLYPH` — used CID с пустым glyf |
| 14.07.2026 | **A-VIS-TEXT-GLYPH-PARITY-001** | `TBANK_TEXT_GLYPH_PARITY` — decoded ≠ fitz для критполей |
| 14.07.2026 | **A-FONT-GLYPH-SLOT-TRANSPLANT-001** | `GLYPH_SLOT_TRANSPLANT` — outline в чужом GID / LSB≠xMin / hmtx приёмника |
| 16.07.2026 | **K-TBANK-SBP-LINKED-TUPLE-001** | `SBP_LINKED_TUPLE_CONFLICT` — полный tuple B1/00117/marker/control/slot/suffix |
| 16.07.2026 | **T-TBANK-SBP-PROFILE-EPOCH-001** | `SBP_PROFILE_EPOCH_MISMATCH` (tier B) — профиль использован после завершения исторического периода |
| 16.07.2026 | **T-TBANK-RECEIPT-STEM-REUSE-001** | `RECEIPT_STEM_REUSE_CONFLICT` (tier B) — корпусный stem с новым tail/opid/date |
| 16.07.2026 | **K-TBANK-STREAM-SERIALIZER-001 усилен** | HARD split provenance: images+F3 canonical, page+F1/F2 font+cmap non-canonical |
| 16.07.2026 | **FontBBox false-positive fix** | `None/None` больше не считается `PDF_TTF_BBOX_CROSS_LAYER_MISMATCH` |
| 16.07.2026 | **K-TBANK-REASSEMBLED-SUBSET-001** | KNOWN `TBANK_REASSEMBLED_BANK_ASSETS` — украденные банковские assets + невозможная corpus assembly + generator provenance |

Все перечисленные production-изменения задеплоены на `85.192.40.122`; сервис `pdfbot` активен.

---

## 21. Приложения

### A. Полный дамп `_EMPIRICAL_PROFILES`

**(G1, 00117)** — n=24, markers {0,1}, suffixes {730902,770402,770901,791103}
triple_control: (0,001,770402)→N, (0,003,770901)→D, (0,007,791103)→J, (0,008,770901)→W, (0,008,791103)→U, (0,012,730902)→O, (0,014,791103)→5, (0,017,770901)→Z, (0,018,791103)→H, (1,002,791103)→0, (1,004,770901)→6, (1,004,791103)→E, (1,006,791103)→D, (1,016,791103)→I, (1,017,791103)→D, (1,018,791103)→S

**(00, 00116)** — n=9, markers {0,1}, suffixes {640702,661101,670301,680301,681101}
triple_control: (0,003,670301)→B, (0,004,670301)→A, (0,004,681101)→3, (0,007,640702)→F, (0,007,670301)→9, (0,008,680301)→D, (1,014,661101)→R, (1,016,680301)→6

**(B1, 00117)** — n=20, markers {0,1}, suffixes {700501,730501,760501,770302,770901,790502}
triple_control: (0,002,760501)→V, (0,002,770901)→Y, (0,002,790502)→6, (0,006,770302)→D, (0,006,770901)→2, (0,010,790502)→L, (0,011,790502)→D, (0,013,700501)→D, (0,017,790502)→C, (0,018,770901)→L, (1,001,760501)→T, (1,011,730501)→7, (1,013,760501)→1, (1,020,790502)→A

**(B0, 00116)** — n=2, markers {6,7}, suffixes {680301}
triple_control: (6,016,680301)→1, (7,016,680301)→6

### B. SBP grammar decode

```python
def decode_sbp(opid32):
    return {
        "lead":         opid32[0],
        "enc_year":     opid32[1],
        "enc_doy":      opid32[2:5],
        "enc_hms":      opid32[5:11],
        "ref3":         opid32[11:14],
        "route_marker": opid32[14],
        "control":      opid32[15],
        "separator":    opid32[16],   # '0'
        "route_lead":   opid32[17],   # 0|B|G
        "sb_class":     opid32[17:19],
        "slot":         opid32[19:22],
        "profile_block":opid32[22:26],# '0011'
        "bank5":        opid32[22:27],
        "suffix":       opid32[26:32],
    }
```

### C. Быстрая проверка (Python)

```python
from detector.reputation import file_hash
from detector.tbank import analyze
data = open("receipt.pdf","rb").read()
r = analyze(data, file_hash(data))
print(r["verdict"], [f for f in r["flags"]])
```

### D. Быстрая регрессия перед деплоем

```
python tools/_tbank_empirical_regression.py
python tools/_tbank_used_glyph_regression.py
python tools/_v6_regression.py
python tools/_deploy_v6.py          # деплой + restart pdfbot
```

---

*PDFCHECKER VALIDATOR MASTER SPEC v1.1 — фактическая реализация детектора*
*Проект: pdf-checker-bot · сервер 85.192.40.122 · сервис pdfbot*
