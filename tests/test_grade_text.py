import pytest

from app.agent.grade_text import check_grade, parse_grade_text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("9,3", 9.3),
        ("9.3", 9.3),
        ("10", 10.0),
        ("8 pontos", 8.0),
        ("oito", 8.0),
        ("Nove e meio", 9.5),
        ("sete vírgula cinco", 7.5),
        ("sete virgula 25", 7.25),
        ("dez", 10.0),
    ],
)
def test_parse_valid(text, expected):
    assert parse_grade_text(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["oitcx", "", "11", "nota boa", "8,5,3", "dez e meio"])
def test_parse_invalid(text):
    assert parse_grade_text(text) is None


def test_check_grade_rejects_guess():
    with pytest.raises(ValueError, match="Não entendi"):
        check_grade(8, "oitcx")  # o modelo "adivinhou" 8


def test_check_grade_rejects_mismatch():
    with pytest.raises(ValueError, match="diferente"):
        check_grade(9.5, "9,3")
