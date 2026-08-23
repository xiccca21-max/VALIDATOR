"""Regression tests for Alfa SBP label/value row binding."""

from detector.alfa_v2.profile_semantics import validate_field_value_binding


def _codes(text: str) -> set[str]:
    return {
        flag.code
        for flag in validate_field_value_binding(text, method="sbp").flags
    }


def test_shifted_sbp_rows_are_decisive():
    text = """\
Квитанция о переводе по СБП
Сумма перевода
87 560 RUR
Комиссия
0 RUR
Списано с учётом комиссии
19.08.2026 18:33:51 мск
Дата и время перевода
C161908261730059
Номер операции
Электрон Китае И
Получатель
Кирилл Станиславович К
"""
    assert "ALFA_FIELD_VALUE_BINDING_CONFLICT" in _codes(text)


def test_normal_sbp_rows_stay_clean():
    text = """\
Квитанция о переводе по СБП
Сумма перевода
87 560 RUR
Комиссия
0 RUR
Дата и время перевода
19.08.2026 18:33:51 мск
Номер операции
C161908261730059
Получатель
Кирилл Станиславович К
"""
    assert "ALFA_FIELD_VALUE_BINDING_CONFLICT" not in _codes(text)


def test_valid_debit_row_stays_clean():
    text = """\
Квитанция о переводе по СБП
Сумма перевода
87 560 RUR
Комиссия
40 RUR
Списано с учётом комиссии
87 600 RUR
Дата и время перевода
19.08.2026 18:33:51 мск
Номер операции
C161908261730059
"""
    assert "ALFA_FIELD_VALUE_BINDING_CONFLICT" not in _codes(text)


def test_one_bad_binding_does_not_decide():
    text = """\
Квитанция о переводе по СБП
Дата и время перевода
19.08.2026 18:33:51 мск
Номер операции
не извлечено
"""
    assert "ALFA_FIELD_VALUE_BINDING_CONFLICT" not in _codes(text)
