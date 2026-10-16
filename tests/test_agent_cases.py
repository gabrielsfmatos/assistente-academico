"""Confere se o arquivo de casos do agente está bem formado.
(A avaliação do agente em si vem quando o agente existir.)"""

from pathlib import Path

import yaml

CASES_FILE = Path(__file__).parent / "agent_cases.yaml"
KNOWN_CODES = {"ACD", "AP", "CDD", "EI", "LPP"}
RESPONSE_TYPES = {"informacao", "pergunta", "recusa", "confirmacao_feita"}


def load():
    return yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))


def test_cases_file_is_valid():
    data = load()
    cases = data["casos"]
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "ids repetidos"
    for case in cases:
        assert case["conversa"], f"caso {case['id']} sem mensagens"
        expected = case["esperado"]
        if "tipo_resposta" in expected:
            assert expected["tipo_resposta"] in RESPONSE_TYPES, case["id"]
        for key in ("faltas", "presencas", "canceladas", "provas"):
            for item in expected.get(key, []):
                assert item["disciplina"] in KNOWN_CODES, case["id"]


def test_all_29_phrases_are_covered():
    assert sorted(c["id"] for c in load()["casos"]) == list(range(1, 30))
