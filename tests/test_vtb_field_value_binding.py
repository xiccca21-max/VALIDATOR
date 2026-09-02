"""VTB SBP label/value row binding — foreign-shell coordinate shift."""

from detector.vtb_v2.field_binding import check_field_value_binding


def _codes(text: str) -> set[str]:
    return {flag.code for flag in check_field_value_binding(text)}


def test_shifted_sbp_rows_are_decisive():
    text = """\
Исходящий перевод СБП
Статус
Выполнено
Дата операции
100 000 ₽
Имя плательщика
Максим Васильевич К.
Получатель
B6183111709072080G1010001
ID операции в СБП
Артур Алексеевич С.
Сумма операции
02.07.2026, 14:17
Банк ВТБ (ПАО)
"""
    assert "VTB_FIELD_VALUE_BINDING_CONFLICT" in _codes(text)


def test_normal_sbp_rows_stay_clean():
    text = """\
Исходящий перевод СБП
Артур Алексеевич С.
Статус
Выполнено
Дата операции
02.07.2026, 14:17
Счет списания
*1958
Имя плательщика
Максим Васильевич К.
Получатель
Артур Алексеевич С.
Телефон получателя
+7 (910) 877-66-06
Банк получателя
Т-Банк
ID операции в СБП
B6183111709072080G1010001
1791103
Сумма операции
100 000 ₽
Банк ВТБ (ПАО)
Операция выполнена
"""
    assert "VTB_FIELD_VALUE_BINDING_CONFLICT" not in _codes(text)


def test_one_bad_binding_does_not_decide():
    text = """\
Исходящий перевод СБП
Дата операции
02.07.2026, 14:17
Сумма операции
не извлечено
"""
    assert "VTB_FIELD_VALUE_BINDING_CONFLICT" not in _codes(text)
