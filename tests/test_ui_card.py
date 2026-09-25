import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import ui  # noqa: E402

TEXT = (
    "Квитанция № 1-2-3\n5 июля 2026 11:52:07\nПеревод по номеру карты\n"
    "Сумма 5 753 ₽\nГенеральная лицензия Банка России № 2673 от 24.03.2015\n"
)
PARSED = {
    "issuer_bank": "Т-Банк",
    "sender": "Светлана Чернышева",
    "receiver": None,
    "receiver_account": None,
    "contact_label": "Карта получ",
    "contact_value": "220012****9747",
    "recipient_bank_normalized": "Сбербанк",
    "status": "Успешно",
    "amount": "5 753,00 руб.",
}
AT = datetime.datetime(2026, 9, 24, 20, 25, tzinfo=datetime.timezone.utc)


def test_pretty_amount():
    assert ui.pretty_amount("5 753,00 руб.") == "5 753 ₽"
    assert ui.pretty_amount("371427 ₽") == "371 427 ₽"
    assert ui.pretty_amount("1 234,50 руб.") == "1 234,50 ₽"
    assert ui.pretty_amount("") is None


def test_receipt_datetime_prefers_operation_date_not_license():
    assert ui.receipt_datetime(TEXT) == "5 июля 2026, 11:52"
    assert ui.receipt_datetime("Дата 05.08.2026 20:33:10") == "5 августа 2026, 20:33"
    assert ui.receipt_datetime("нет даты") is None


def test_ok_card_layout():
    card = ui.result_card(
        kind="ok", bank="Т-Банк", filename="tbank_nocomm_01.pdf", checked_at=AT,
        parsed=PARSED, text=TEXT,
    )
    lines = card.split("\n")
    assert lines[0] == "<b>✅ Чек прошёл проверку</b>"
    assert lines[1] == "<i>tbank_nocomm_01.pdf · 24.09.2026 23:25</i>"  # MSK
    assert "<b>Платёж</b>\n<blockquote>Дата: 5 июля 2026, 11:52\nСумма: <b>5 753 ₽</b>" in card
    assert "Отправитель: Светлана Чернышева" in card
    assert "Получатель: <code>220012****9747</code>" in card
    assert "Банк получателя: Сбербанк" in card
    assert "Статус: Успешно" in card
    assert "<b>Проверка</b>\n<blockquote>Банк: Т-Банк\nСтруктура документа: соответствует банку\nПризнаков изменения: нет</blockquote>" in card
    assert card.endswith("Признаков изменения: нет</blockquote>")
    assert "Зачисление" not in card
    assert "История" not in card


def test_fake_card_hides_status_and_shows_history():
    parsed = dict(PARSED, receiver="Юрий Щ.", contact_value="427645****1393",
                  amount="371427 руб.", sender="Татьяна Зайцева")
    card = ui.result_card(
        kind="fake", bank="Т-Банк", filename="x.pdf", checked_at=AT,
        parsed=parsed, text="Дата 05.08.2026 20:33",
        history=["24.09.2026 22:41 - @username", "24.09.2026 23:10 - @another"],
    )
    assert card.startswith("<b>❌ Чек не прошёл проверку</b>")
    assert "Статус:" not in card
    assert "Получатель: Юрий Щ. · <code>427645****1393</code>" in card
    assert "Структура документа: <b>не соответствует банку</b>" in card
    assert "Признаков изменения: <b>есть</b>" in card
    assert card.endswith(
        "<b>История</b>\n<blockquote>24.09.2026 22:41 - @username\n24.09.2026 23:10 - @another</blockquote>"
    )


def test_failed_transfer_card():
    parsed = dict(PARSED, status="Отклонено")
    card = ui.result_card(kind="failed", bank="Сбер", filename="", checked_at=AT,
                          parsed=parsed, text="", status="Отклонено")
    assert card.startswith("<b>⚠️ Перевод не выполнен</b>\n<i>24.09.2026 23:25</i>")
    assert "Статус: <b>Отклонено</b>" in card
    assert "Операция: <b>не выполнена</b>" in card
    assert "<i>Это не подтверждение оплаты</i>" in card


def test_unknown_bank_and_unknown_doc():
    card = ui.result_card(kind="unknown_bank", bank="", filename="a.pdf", checked_at=AT,
                          parsed=None, text="")
    assert "Банк: <b>не поддерживается</b>" in card
    assert "Платёж" not in card
    card = ui.result_card(kind="unknown_doc", bank="", filename="a.pdf", checked_at=AT,
                          parsed=None, text="", note="Это счёт на оплату, а не чек <x>")
    assert card.startswith("<b>❔ Не похоже на банковский чек</b>")
    assert "Это счёт на оплату, а не чек &lt;x&gt;" in card
    assert "Платёж" not in card and "Проверка" not in card


def test_values_are_html_escaped():
    parsed = dict(PARSED, sender="<b>Иван</b> & Ко")
    card = ui.result_card(kind="ok", bank="Т-Банк", filename="<f>.pdf", checked_at=AT,
                          parsed=parsed, text="")
    assert "&lt;b&gt;Иван&lt;/b&gt; &amp; Ко" in card
    assert "<i>&lt;f&gt;.pdf" in card
