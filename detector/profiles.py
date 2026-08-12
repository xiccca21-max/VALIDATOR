"""Bank registry: identification, routing, supported-bank list."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .tbank import analyze as analyze_tbank


@dataclass(frozen=True)
class BankProfile:
    key: str
    name: str
    markers: tuple[str, ...]
    producers: tuple[str, ...] = ()
    min_score: float = 0.45
    use_tbank_engine: bool = False
    use_alfa_engine: bool = False
    use_spec_engine: bool = False


def _load_bank_meta() -> dict:
    try:
        import json
        from pathlib import Path
        p = Path(__file__).with_name("bank_corpus.json")
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("banks", {})
    except Exception:
        pass
    return {}


def _build_profiles() -> list[BankProfile]:
    corpus = _load_bank_meta()
    profiles: list[BankProfile] = []

    profiles.append(BankProfile(
        key="tbank",
        name="Т-Банк",
        markers=("т-банк", "тинькофф", "tinkoff", "tbank", "tbank.ru", "fb@tbank"),
        producers=("jasperreports", "openpdf"),
        min_score=0.4,
        use_tbank_engine=True,
    ))

    profiles.append(BankProfile(
        key="alfa",
        name="Альфа-Банк",
        markers=(
            "квитанция о переводе", "сформирована", "альфа-банк", "alfa-bank",
        ),
        producers=("oracle bi publisher",),
        min_score=0.45,
        use_alfa_engine=True,
    ))

    # Альфа-Банк, iOS-вариант (Quartz PDFContext) — тот же alfa_v2,
    # что и Oracle BI веб-формат (emitter routing внутри движка).
    profiles.append(BankProfile(
        key="alfa_ios",
        name="Альфа-Банк",
        markers=("сформирована", "квитанция о переводе"),
        producers=("quartz pdfcontext",),
        min_score=0.45,
        use_alfa_engine=True,
    ))

    profiles.append(BankProfile(
        key="sber",
        name="Сбербанк",
        markers=(
            "чек по операции", "перевод клиенту сбербанка",
            "сбербанк", "сбер",
        ),
        producers=("itext 2.1.7",),
        min_score=0.45,
    ))

    profiles.append(BankProfile(
        key="ozon",
        name="Ozon Банк",
        markers=(
            "озон банк", "ozon банк", "ozon bank",
            "служба поддержки ozon",
        ),
        producers=("skia/pdf", "chromium"),
        min_score=0.45,
    ))

    profiles.append(BankProfile(
        key="vtb",
        name="Банк ВТБ",
        markers=(
            "банк втб", "втб (пао)", "исходящий перевод сбп",
            "перевод на карту", "по номеру телефона клиенту втб",
        ),
        producers=("openhtmltopdf",),
        min_score=0.45,
    ))

    profiles.append(BankProfile(
        key="gazprombank",
        name="Газпромбанк",
        markers=(
            "газпромбанк", "gazprombank", "mailbox@gazprombank.ru",
            "www.gazprombank.ru", "чек по операции",
        ),
        producers=("itext® 7", "itext 2.1.7", "jasperreports"),
        min_score=0.45,
    ))

    profiles.append(BankProfile(
        key="wbbank",
        name="ВБ Банк",
        markers=("вб банк", "wildberries bank", "перевод по сбп"),
        producers=("openpdf", "jasperreports"),
        min_score=0.45,
    ))
    profiles.append(BankProfile(
        key="otp",
        name="ОТП Банк",
        markers=("отп банк", "7708001614", "квитанция"),
        producers=("quartz pdfcontext", "mpdf"),
        min_score=0.45,
    ))
    profiles.append(BankProfile(
        key="psb",
        name="Промсвязьбанк",
        markers=("чек по операции", "id операции сбп"),
        producers=("fastreport",),
        min_score=0.45,
    ))
    profiles.append(BankProfile(
        key="bchpb",
        name="Банк Санкт-Петербург",
        markers=("банк санкт-петербург", "бспб", "перевод через систему быстрых платежей"),
        producers=("pdfcreator", "pdfproducer"),
        min_score=0.45,
    ))
    profiles.append(BankProfile(
        key="raif",
        name="Райффайзенбанк",
        markers=("райффайзенбанк", "raiffeisen", "справка по операции"),
        producers=("itext® pdfhtml", "itext pdfhtml"),
        min_score=0.45,
    ))
    profiles.append(BankProfile(
        key="rocket",
        name="Рокетбанк",
        markers=("рокет", "перевод через сбп", "банк отправителя"),
        producers=("itext® core 9", "itext core 9"),
        min_score=0.45,
    ))
    profiles.append(BankProfile(
        key="sovkom",
        name="Совкомбанк",
        markers=("платежная квитанция", "совкомбанк"),
        producers=("flying saucer",),
        min_score=0.45,
    ))
    profiles.append(BankProfile(
        key="uralsib",
        name="Уралсиб",
        markers=("уралсиб", "8-800-250-57-57", "квитанция"),
        producers=("rpdf.0.9",),
        min_score=0.45,
    ))
    profiles.append(BankProfile(
        key="yandex",
        name="Яндекс Банк",
        markers=("яндекс банк", "исходящий перевод сбп", "дата и время операции мск"),
        producers=("openpdf", "jasperreports"),
        min_score=0.45,
    ))

    for key, bank in corpus.items():
        if key in (
            "tbank", "alfa", "sber", "ozon", "vtb", "gazprombank",
            "wbbank", "otp", "psb", "bchpb", "raif", "rocket", "sovkom", "uralsib", "yandex",
        ):
            continue
        profiles.append(BankProfile(
            key=key,
            name=bank.get("name", key),
            markers=tuple(m.lower() for m in bank.get("markers", ())),
            producers=tuple(p.lower() for p in bank.get("known_producers", ())),
            min_score=0.3 if key == "raif" else 0.45,
            use_spec_engine=True,
        ))
    return profiles


PROFILES: list[BankProfile] | None = None


def get_profiles() -> list[BankProfile]:
    global PROFILES
    if PROFILES is None:
        PROFILES = _build_profiles()
    return PROFILES


def reload_profiles() -> None:
    """Перечитать bank_corpus.json (после tools/build_bank_corpus.py)."""
    global PROFILES
    PROFILES = _build_profiles()


def _norm_text(text: str) -> str:
    return (text or "").replace("\xa0", " ").lower()


def _score(text: str, producer: str, profile: BankProfile) -> float:
    t = _norm_text(text)
    pr = (producer or "").lower()
    if profile.key == "gazprombank" and (
        # Домен эмитента есть только в чеках, ВЫПУЩЕННЫХ Газпромбанком.
        # Голое слово «газпромбанк» триггерило чужие чеки, где ГПБ — банк
        # получателя (например, Альфа/Сбер по СБП), поэтому убрано.
        "gazprombank.ru" in t
        or "mailbox@gazprombank.ru" in t
    ):
        return 1.0
    # Альфа-Банк iOS (Quartz) идёт в профиль alfa_ios → тот же alfa_v2,
    # НЕ в чужой банк. Комбинация «Сформирована» + «Квитанция о переводе»
    # уникальна Альфе (у Сбера/ОТП/ГПБ из iOS другой заголовок).
    if profile.key == "alfa_ios" and "quartz pdfcontext" in pr:
        # Чек Альфы из приложения iOS: первая строка «Сформирована» +
        # «Квитанция о переводе …». Домены/юр-имена других банков сюда не
        # попадают, т.к. это формат именно Альфы (Oracle-веб идёт по producer).
        if "сформирована" in t and "квитанция о переводе" in t:
            return 1.0
    if profile.key == "sber" and "quartz pdfcontext" in pr:
        # iOS Sber export variant can omit explicit "Сбер/Сбербанк" in body text.
        # Keep this strict by requiring the exact transfer wording + field labels.
        if (
            "перевод в другой банк по номеру карты" in t
            and "откуда" in t
            and "куда" in t
        ):
            return 0.95
    if profile.key == "otp" and (
        "акционерное общество \u00abотп банк\u00bb" in t
        or "ао \u00abотп банк\u00bb" in t
        or "ао \u00abотп банк\u00bb" in t.replace("\u00ab", "").replace("\u00bb", "")
        or "7708001614" in t  # ОТП Банк ИНН — уникальная подпись эмитента
    ):
        # Юридическая подпись эмитента ОТП встречается только в чеках,
        # выпущенных ОТП (не когда ОТП — банк получателя). Producer может быть
        # любым: Quartz (iOS), mPDF, либо пустым.
        return 1.0
    if profile.key == "otp" and "quartz pdfcontext" in pr:
        # Quartz is also used by other banks (e.g. Sber exports from iOS),
        # so treat it as OTP-only when OTP markers are present in text.
        return 1.0 if any(m in t for m in profile.markers) else 0.0
    if profile.key == "bchpb" and (
        'банк "санкт-петербург"' in t
        or "банк санкт-петербург" in t
    ):
        return 1.0
    if profile.key == "rocket" and "банк отправителя" in t and "рокет" in t:
        return 1.0
    if profile.key == "wbbank" and "вб банк" in t:
        return 1.0
    if profile.key == "psb" and "fastreport" in pr and "чек по операции" in t:
        return 1.0
    if profile.key == "sovkom" and "flying saucer" in pr:
        return 1.0
    if profile.key == "uralsib" and "rpdf.0.9" in pr:
        return 1.0
    if profile.key == "yandex" and "банк отправителя" in t:
        sender = t.split("банк отправителя", 1)[-1][:80]
        if "яндекс" in sender:
            return 1.0
    # Уникальные producer → банк (надёжный сигнал)
    exclusive = (
        ("oracle bi publisher", "alfa"),
        ("openhtmltopdf", "vtb"),
        ("fastreport", "psb"),
        ("rpdf.0.9", "uralsib"),
        ("itext 2.1.7", "sber"),
        ("itext® 7", "gazprombank"),
    )
    for prod_sub, key in exclusive:
        if profile.key == key and prod_sub in pr:
            # iText 2.1.7 is shared by non-Sber Jasper banks (ГПБ, ДОМ.РФ, …).
            # Never exclusive-map to Sber when another issuer is branded, or when
            # the body has no Sber branding at all.
            if key == "sber" and prod_sub == "itext 2.1.7":
                foreign_issuer = (
                    "gazprombank.ru" in t
                    or "mailbox@gazprombank.ru" in t
                    or "банк дом.рф" in t
                    or "дом.рф" in t
                )
                sber_brand = (
                    "сбербанк" in t
                    or "sberbank" in t
                    or "перевод клиенту сбербанка" in t
                )
                # Shared Jasper/iText tooling — block only when another bank is branded.
                if foreign_issuer and not sber_brand:
                    continue
            return 1.0
    if profile.key == "ozon" and "skia/pdf" in pr:
        return 1.0
    # OTP issuer must never lose to recipient-bank «Озон Банк» marker noise.
    if profile.key == "ozon" and (
        "7708001614" in t
        or "акционерное общество «отп банк»" in t
        or "ао «отп банк»" in t
    ):
        return 0.0
    if profile.key == "tbank" and "fb@tbank" in t:
        return 1.0
    if profile.key == "tbank" and "pdfium" in pr and "tbank" in t:
        return 1.0
    # SEQ strips/corrupts «Служба поддержки fb@tbank.ru» (ToUnicode junk) so
    # text markers disappear while OpenPDF+Jasper shell + SBP field layout stay.
    # Fingerprint is T-Bank SBP-only in genuines (0 FP on other OpenPDF banks).
    if profile.key == "tbank" and "openpdf" in pr:
        if (
            "по номеру телефона" in t
            and "счет списания" in t
            and "идентификатор операции" in t
            and "квитанция" in t
        ):
            return 1.0
    hits = 0
    total = len(profile.markers) + max(len(profile.producers), 1)
    for m in profile.markers:
        if m.replace("\xa0", " ") in t:
            hits += 1
    for p in profile.producers:
        if p and p in pr:
            hits += 1
    if hits and not any(m in t for m in profile.markers):
        return min(0.55, hits / total)
    return hits / total if total else 0.0


def identify(text: str, producer: str) -> tuple[dict | None, float]:
    best: BankProfile | None = None
    best_score = 0.0
    scores: dict[str, float] = {}
    by_key: dict[str, BankProfile] = {}
    for p in get_profiles():
        s = _score(text, producer, p)
        scores[p.key] = s
        by_key[p.key] = p
        if s > best_score:
            best_score, best = s, p
    # Issuer domain beats shared iText 2.1.7 → Sber exclusive mapping.
    t = _norm_text(text)
    gpb = by_key.get("gazprombank")
    if (
        gpb
        and scores.get("gazprombank", 0) >= gpb.min_score
        and ("gazprombank.ru" in t or "mailbox@gazprombank.ru" in t)
    ):
        best, best_score = gpb, max(scores.get("gazprombank", 0), 1.0)
    if best and best_score >= best.min_score:
        return {"key": best.key, "name": best.name}, best_score
    return None, best_score


def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:
    """Route to the correct analyzer by re-identifying bank."""
    import fitz
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        producer = (doc.metadata.get("producer", "") or "")
        text = "".join(p.get_text() for p in doc)
        doc.close()
    except Exception:
        producer, text = "", ""
    prof, _ = identify(text, producer)
    if prof:
        return analyze_for(prof["key"], pdf_bytes, file_hash)
    from .generic_bank import analyze as generic_analyze
    return generic_analyze(pdf_bytes, "unknown", file_hash)


def analyze_for(key: str, pdf_bytes: bytes, file_hash: str = "") -> dict:
    from .alfa import analyze as analyze_alfa
    from .bank_spec_engine import analyze as spec_analyze
    from .full_bank import analyze as full_analyze
    from .generic_bank import analyze as generic_analyze
    from .gazprombank import analyze as analyze_gazprombank
    from .ozon import analyze as analyze_ozon
    from .sber import analyze as analyze_sber
    from .sparse9 import analyze as analyze_sparse9
    from .sparse9_v1.rollout import is_sparse9_bank
    from .vtb import analyze as analyze_vtb
    for p in get_profiles():
        if p.key == key:
            if p.use_tbank_engine:
                return analyze_tbank(pdf_bytes, file_hash)
            if p.use_alfa_engine:
                return analyze_alfa(pdf_bytes, file_hash)
            if key == "sber":
                return analyze_sber(pdf_bytes, file_hash)
            if key == "ozon":
                return analyze_ozon(pdf_bytes, file_hash)
            if key == "vtb":
                return analyze_vtb(pdf_bytes, file_hash)
            if key == "gazprombank":
                return analyze_gazprombank(pdf_bytes, file_hash)
            if is_sparse9_bank(key):
                return analyze_sparse9(pdf_bytes, key, file_hash)
            return full_analyze(pdf_bytes, key, file_hash)
    return generic_analyze(pdf_bytes, key, file_hash)


def format_banks_list_html() -> str:
    """Список банков без пояснений."""
    corpus = _load_bank_meta()
    lines: list[str] = ["• <b>Т-Банк</b>"]
    tier2_order = (
        "alfa", "sber", "vtb", "gazprombank", "psb", "raif",
        "ozon", "otp", "uralsib", "yandex", "sovkom", "rocket", "bchpb",
    )
    for key in tier2_order:
        bank = corpus.get(key)
        if bank:
            lines.append(f"• <b>{bank['name']}</b>")
    return "\n".join(lines)
