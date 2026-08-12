# PDF Checker Bot (VALIDATOR)

Репозиторий: https://github.com/xiccca21-max/VALIDATOR

Telegram-бот для проверки PDF-чеков банков: отличает подделки от оригиналов по **структурной форензике** PDF (шрифты, content stream, shell, SBP), а не по «похожести» картинки.

**Путь проекта:** `C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot`

---

## Как это работает

```
PDF → bot.py → detector.route()
                    │
                    ├─ identify банк (текст + Producer)
                    ├─ global preflight (битый PDF / JS / опасный контент)
                    ├─ bank engine (tbank_v6 / sber_v2 / alfa_v2 / …)
                    ├─ hardening_v2 + policy (HARD / IGNORE)
                    └─ вердикт: ФЕЙК | ЧИСТО | НЕИЗВЕСТНЫЙ ДОКУМЕНТ
```

1. Пользователь кидает PDF в Telegram-бота (`bot.py`, aiogram).
2. Бот вызывает `detector.route(pdf_bytes)`.
3. Роутер узнаёт банк по маркерам в тексте и `Producer` (`detector/profiles.py`).
4. Запускается банковский движок: набор **правил** (stages). Срабатывание **HARD** (структурное противоречие с 0 FP на genuines) → **ФЕЙК**.
5. Soft/статистика без жёсткого доказательства не превращают оригинал в фейк. Novelty (новый SHA/size) — не бан.
6. Бот нормализует ответ и пишет пользователю вердикт + краткое объяснение.

---

## Вердикты

| Вердикт | Смысл |
|--------|--------|
| **ФЕЙК** | Есть decisive HARD / known signature / score ≥ 60 |
| **ЧИСТО** | Банк распознан, жёстких противоречий нет |
| **НЕИЗВЕСТНЫЙ ДОКУМЕНТ** | Не чек поддерживаемого банка / анализ не применим |

Политика доверия (T-Bank и аналоги): Tier A = жёсткий фейк, Tier B/C = обзор/аналитика (`detector/policy_v5.py`).

---

## Поддерживаемые банки (движки)

| Ключ | Папка | Примечание |
|------|--------|------------|
| `tbank` | `detector/tbank_v6/` | Основной объём правил (шрифты F1/F2, content, SBP) |
| `sber` | `detector/sber_v2/` | Сбер |
| `alfa` | `detector/alfa_v2/` | Альфа |
| `vtb` | `detector/vtb_v2/` | ВТБ |
| `ozon` | `detector/ozon_v1/` | Ozon |
| `gpb` | `detector/gpb_v1/` | Газпромбанк |
| `sparse9` | `detector/sparse9_v1/` | OTP / Raiffeisen / PSB и др. «редкие» |

Общий слой: `hardening_v2/`, `pdf_forensics`, SBP-cipher модули, atlas/pin JSON рядом с правилами.

---

## Структура репозитория

```
pdf-checker-bot/
├── bot.py                 # Telegram-бот (вход)
├── blocklist.py           # блок-лист пользователей
├── deploy_bot.py          # деплой на VPS
├── deploy_config.py       # SSH/пути сервера
├── detector/              # ядро валидатора
│   ├── __init__.py        # route()
│   ├── profiles.py        # банк → engine
│   ├── policy_v5.py       # tier HARD/IGNORE
│   ├── tbank_v6/ …        # банковские движки
│   └── hardening_v2/      # глобальный preflight
├── tools/                 # деплой, форензик, TG-watchers
│   ├── deploy_validator_sync.py
│   ├── tg_defender_watch.py
│   └── night_clean_streak.py
├── campaign/              # кампании / рефералы
├── docs/                  # спеки банков
├── data/                  # данные/корпуса (если есть)
└── .env                   # секреты (не в git)
```

---

## Локальный запуск бота

1. Python 3.11+ (на машине разработки — 3.13).
2. Зависимости: `aiogram`, `pymupdf` (`fitz`), `python-dotenv`, и др. из окружения проекта.
3. В `.env`:
   - `BOT_TOKEN` — токен Telegram-бота
   - `ADMIN_IDS` — через запятую
   - опционально `TELEGRAM_PROXY`, `ARCHIVE_CHANNEL`
4. Запуск:

```bash
python bot.py
```

Проверка PDF без бота:

```python
from detector import route
bank, result, is_tbank = route(open("check.pdf", "rb").read())
print(bank, result["verdict"], result.get("flags"))
```

---

## Деплой на VPS

Синхронизация `detector/` + `bot.py` и рестарт сервиса:

```bash
python tools/deploy_validator_sync.py
# или отдельные файлы:
python tools/deploy_validator_sync.py detector/tbank_v6/rules.py
```

Конфиг SSH/пути: `deploy_config.py` + `.deploy.env` (локально, не коммитить).

---

## Операционный контур (защита от CLEAN-miss)

- `tools/tg_defender_watch.py` — слушает поток чеков (Kron → Proton), гоняет `route()`.
- При **bot=CLEAN**, а локально всё ещё «чисто» на известном фейке — форензик → новое HARD → деплой.
- `output/_proton_miss_watcher.py` + `tools/night_clean_streak.py` — цикл без остановки.

Сессии Telegram и inbox в `output/` / `.tg_*` — **не коммитить**.

---

## Принципы правил

- **HARD только при 0 FP** на корпусе настоящих чеков.
- Не банить за «новый» размер/SHA шрифта (novelty ≠ fake).
- Decisive FAKE нельзя понизить до ЧИСТО из‑за низкого score.
- Новые правила добавляются в stages/rules банка после сравнения fake vs genuines.

---

## Спеки

- `TBANK_VALIDATOR_SPEC_v6.md`
- `SBER_VALIDATOR_SPEC_v2.md`
- `ALFA_VALIDATOR_SPEC_v2.md`
- `PDFCHECKER_VALIDATOR_SPEC_v1.md`
- `docs/` — расширенные описания
