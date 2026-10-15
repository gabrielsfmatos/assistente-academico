import pytest

from scripts.import_xlsx import normalize, parse_attendance_cell, parse_time_range


@pytest.mark.parametrize(
    "value, expected",
    [
        (True, {"attended": True}),
        (False, {"attended": False}),
        ("S/ AULA", {"attended": True, "cancelled": True}),
        ("PROVA", {"attended": True, "has_exam": True}),
        ("TESTE", {"attended": True, "has_quiz": True}),
        (None, None),
        (" ", None),
    ],
)
def test_parse_attendance_cell(value, expected):
    assert parse_attendance_cell(value) == expected


def test_parse_attendance_cell_rejects_unknown_value():
    with pytest.raises(ValueError):
        parse_attendance_cell("FERIADO")


def test_parse_time_range():
    assert parse_time_range("16h - 18h") == ("16:00", "18:00")


def test_normalize_removes_asterisk_and_spaces():
    assert normalize("Empreendedorismo e Inovação* ") == normalize("Empreendedorismo e Inovação")
