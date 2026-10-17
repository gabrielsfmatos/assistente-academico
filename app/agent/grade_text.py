"""Trava de segurança para notas: converte a nota COMO O USUÁRIO ESCREVEU.

O modelo de linguagem pode "adivinhar" (ex.: "oitcx" -> 8). Para impedir que
uma nota adivinhada seja gravada, as ferramentas de nota recebem também o texto
original, e este código precisa conseguir convertê-lo sozinho. Se não conseguir,
ou se o resultado for diferente do número que o modelo enviou, a gravação é
recusada e o agente precisa perguntar.

Aceita: "9,3", "9.3", "10", "8 pontos", "oito", "nove e meio", "sete vírgula cinco".
"""

import re
import unicodedata
from typing import Optional

UNITS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
}


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def parse_grade_text(text: str) -> Optional[float]:
    """Devolve a nota (0 a 10) ou None se o texto não for uma nota clara."""
    if not text:
        return None
    t = _plain(text)
    t = re.sub(r"\s*(pontos?|pts?)$", "", t)  # "8 pontos" -> "8"

    if re.fullmatch(r"\d{1,2}([.,]\d{1,2})?", t):
        value = float(t.replace(",", "."))
        return value if 0 <= value <= 10 else None

    m = re.fullmatch(r"(\w+)( e meio| virgula (\w+))?", t)
    if not m or m.group(1) not in UNITS:
        return None
    value = float(UNITS[m.group(1)])
    if m.group(2) == " e meio":
        value += 0.5
    elif m.group(3) is not None:
        decimal = m.group(3)
        if decimal.isdigit():
            value = float(f"{int(value)}.{decimal}")
        elif decimal in UNITS and UNITS[decimal] < 10:
            value = float(f"{int(value)}.{UNITS[decimal]}")
        else:
            return None
    return value if 0 <= value <= 10 else None


def check_grade(nota: float, nota_texto: str) -> float:
    """Confere se o número enviado pelo modelo é o que o usuário escreveu."""
    parsed = parse_grade_text(nota_texto)
    if parsed is None:
        raise ValueError(
            f"Não entendi a nota {nota_texto!r}. Nada foi gravado: pergunte ao usuário qual foi a nota."
        )
    if abs(parsed - float(nota)) > 1e-9:
        raise ValueError(
            f"A nota escrita pelo usuário ({nota_texto!r} = {parsed:g}) é diferente de {nota:g}. "
            "Nada foi gravado: confirme a nota com o usuário."
        )
    return parsed
