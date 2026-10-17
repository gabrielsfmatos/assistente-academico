"""Avalia o agente com o conjunto de teste (tests/agent_cases.yaml).

Para cada caso:
1. copia o banco real (academico.db) para um arquivo temporário;
2. conversa com o agente usando a data de referência dos casos;
3. compara o estado final do banco e a resposta com o esperado.

Uso:
    python -m scripts.eval_agent --tag v1
    python -m scripts.eval_agent --tag v1 --ids 1 2 17     (só alguns casos)
    python -m scripts.eval_agent --tag v1 --judge          (avalia também o "criterio" com o LLM)

O relatório vai para data/avaliacoes/ (fora do GitHub: contém seus dados).
"""

import argparse
import json
import os
import shutil
import tempfile
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from sqlmodel import Session, select

from app.agent.agent import Agent
from app.agent.llm import DailyQuotaExceeded
from google.genai import errors as genai_errors
from app.agent.prompt import PROMPT_VERSION
from app.db import DB_PATH, get_engine
from app.models import Assessment, ClassSession, Course

CASES_FILE = Path("tests/agent_cases.yaml")
CONFIG_ERROR_CODES = {400, 401, 403, 404}
GRAVE = "[GRAVE]"  # erro que alterou dados indevidamente (pior que perguntar demais)


class ConfigError(RuntimeError):
    """Problema de configuração: não adianta rodar os outros casos."""
OUT_DIR = Path("data/avaliacoes")


# ---------------------------------------------------------------- estado do banco


def snapshot(engine) -> dict:
    """Foto do que importa no banco (sem o log de alterações)."""
    with Session(engine) as db:
        courses = {c.id: c for c in db.exec(select(Course)).all()}
        return {
            "aulas": {
                (courses[s.course_id].code, s.day.isoformat()): (s.attended, s.cancelled, s.has_quiz)
                for s in db.exec(select(ClassSession)).all()
            },
            "provas": {
                (courses[a.course_id].code, a.name): (a.day.isoformat() if a.day else None, a.grade)
                for a in db.exec(select(Assessment)).all()
            },
            "disciplinas": {
                c.code or c.name: {
                    "situacao": c.status.value,
                    "cobra_frequencia": c.requires_attendance,
                    "curso": c.program,
                    "media_final": c.final_grade,
                }
                for c in courses.values()
            },
        }


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


# ---------------------------------------------------------------- verificação


def check_case(case: dict, before: dict, after: dict, final_text: str, traces: list) -> list[str]:
    exp = case["esperado"]
    problems: list[str] = []

    def session(code, day):
        return after["aulas"].get((code, str(day)))

    for key, index, want, label in (
        ("faltas", 0, False, "falta"),
        ("presencas", 0, True, "presença"),
        ("canceladas", 1, True, "cancelada"),
    ):
        for item in exp.get(key, []):
            s = session(item["disciplina"], item["dia"])
            if s is None or s[index] is not want:
                problems.append(f"esperava {label} em {item['disciplina']} {item['dia']}")

    for item in exp.get("provas", []):
        found = [
            (name, values)
            for (code, name), values in after["provas"].items()
            if code == item["disciplina"] and ("nome" not in item or name == item["nome"])
        ]
        ok = any(
            ("dia" not in item or values[0] == str(item["dia"]))
            and ("nota" not in item or values[1] == item["nota"])
            for _, values in found
        )
        if not ok:
            problems.append(f"esperava avaliação {item}")

    if "media_final" in exp:
        item = exp["media_final"]
        got = after["disciplinas"].get(item["disciplina"], {}).get("media_final")
        if got != item["nota"]:
            problems.append(f"esperava média {item['nota']} em {item['disciplina']}, veio {got}")

    if "disciplina" in exp:
        item = dict(exp["disciplina"])
        code = item.pop("codigo")
        got = after["disciplinas"].get(code, {})
        for field, value in item.items():
            if got.get(field) != value:
                problems.append(f"esperava {code}.{field} = {value}, veio {got.get(field)}")

    if exp.get("sem_alteracoes") and before != after:
        problems.append(f"{GRAVE} o banco mudou, mas não deveria")

    for text in exp.get("resposta_contem", []):
        if plain(str(text)) not in plain(final_text):
            problems.append(f"resposta não contém {text!r}")

    kind = exp.get("tipo_resposta")
    if kind == "pergunta" and "?" not in final_text:
        problems.append("esperava uma pergunta na resposta")
    if kind == "recusa" and traces:
        problems.append("esperava recusa sem usar ferramentas")
    return problems


def judge(case: dict, conversation: list[tuple[str, str]]) -> tuple[bool, str]:
    """Usa o LLM como juiz para o campo 'criterio' (opcional)."""
    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    dialog = "\n".join(f"Usuário: {u}\nAgente: {a}" for u, a in conversation)
    prompt = (
        "Você avalia respostas de um assistente acadêmico.\n"
        f"Critério: {case['esperado']['criterio']}\n\nConversa:\n{dialog}\n\n"
        'Responda só com JSON: {"ok": true ou false, "motivo": "..."}'
    )
    response = client.models.generate_content(
        model=model, contents=prompt, config={"response_mime_type": "application/json"}
    )
    data = json.loads(response.text)
    return bool(data.get("ok")), data.get("motivo", "")


# ---------------------------------------------------------------- execução


def run_case(case: dict, today: date, use_judge: bool) -> dict:
    tmp_dir = Path(tempfile.mkdtemp())
    db_copy = tmp_dir / "caso.db"
    shutil.copy(DB_PATH, db_copy)
    engine = get_engine(f"sqlite:///{db_copy}")
    before = snapshot(engine)

    agent = Agent(engine, today_fn=lambda: today)
    conversation, traces = [], []
    error = None
    try:
        for message in case["conversa"]:
            reply = agent.reply(message)
            conversation.append((message, reply.text))
            traces.extend({"ferramenta": t.name, "args": t.args, "resultado": t.result} for t in reply.trace)
    except DailyQuotaExceeded:
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except genai_errors.ClientError as exc:
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if exc.code in CONFIG_ERROR_CODES:  # modelo inexistente, chave inválida...
            raise ConfigError(f"Erro de configuração ({exc.code}): {exc}") from exc
        error = f"ClientError: {exc}"
        return {"id": case["id"], "categoria": case.get("categoria", ""), "ok": False,
                "problemas": [error], "conversa": conversation, "ferramentas": traces}
    except Exception as exc:  # erro de API, etc.: o caso conta como falha
        error = f"{type(exc).__name__}: {exc}"

    after = snapshot(engine)
    engine.dispose()
    shutil.rmtree(tmp_dir, ignore_errors=True)

    final_text = conversation[-1][1] if conversation else ""
    problems = [error] if error else check_case(case, before, after, final_text, traces)
    if not error and use_judge and "criterio" in case["esperado"]:
        ok, reason = judge(case, conversation)
        if not ok:
            problems.append(f"juiz: {reason}")

    return {
        "id": case["id"],
        "categoria": case.get("categoria", ""),
        "ok": not problems,
        "grave": any(p.startswith(GRAVE) for p in problems),
        "problemas": problems,
        "conversa": conversation,
        "ferramentas": traces,
    }


def write_report(tag: str, results: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    passed = sum(r["ok"] for r in results)
    total = len(results)

    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r["categoria"], []).append(r["ok"])

    lines = [
        f"# Avaliação do agente — {tag}",
        "",
        f"- Data: {datetime.now():%d/%m/%Y %H:%M}",
        f"- Prompt: {PROMPT_VERSION} · Modelo: {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}",
        f"- **Acertos: {passed}/{total} ({passed / total:.0%})**",
        f"- **Erros graves (alteraram dados indevidamente): {sum(r.get('grave', False) for r in results)}**",
        "",
        "## Por categoria",
        "",
        "| Categoria | Acertos |",
        "|---|---|",
        *[f"| {c} | {sum(v)}/{len(v)} |" for c, v in sorted(by_cat.items())],
        "",
        "## Casos",
        "",
    ]
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        lines.append(f"### {mark} Caso {r['id']} ({r['categoria']})")
        for user, agent in r["conversa"]:
            lines += [f"- **Você:** {user}", f"- **Agente:** {agent}"]
        for t in r["ferramentas"]:
            lines.append(f"  - `{t['ferramenta']}` {json.dumps(t['args'], ensure_ascii=False)}")
        for p in r["problemas"]:
            lines.append(f"- ⚠️ {p}")
        lines.append("")

    md = OUT_DIR / f"{tag}_{stamp}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / f"{tag}_{stamp}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return md


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="nome da rodada, ex.: v1")
    parser.add_argument("--ids", type=int, nargs="*", help="rodar só estes casos")
    parser.add_argument("--judge", action="store_true", help="usar LLM para avaliar 'criterio'")
    parser.add_argument("--pause", type=float, default=0, help="segundos extras entre casos")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit("Banco não encontrado. Rode a importação da planilha antes.")

    data = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    today = data["data_referencia"]
    cases = [c for c in data["casos"] if not args.ids or c["id"] in args.ids]

    results = []
    for i, case in enumerate(cases, start=1):
        try:
            result = run_case(case, today, args.judge)
        except DailyQuotaExceeded as exc:
            print(f"\n{exc}\nSalvando o relatório parcial ({len(results)} casos).")
            break
        except ConfigError as exc:
            raise SystemExit(f"\n{exc}\nCorrija o .env e rode de novo.") from None
        results.append(result)
        mark = "ok " if result["ok"] else "ERRO"
        print(f"[{i:2}/{len(cases)}] {mark} caso {case['id']:2}: {case['conversa'][0][:55]}")
        for p in result["problemas"]:
            print(f"           - {p}")
        time.sleep(args.pause)

    if not results:
        raise SystemExit("Nenhum caso concluído.")
    passed = sum(r["ok"] for r in results)
    path = write_report(args.tag, results)
    print(f"\nAcertos: {passed}/{len(results)} ({passed / len(results):.0%})")
    print(f"Erros graves: {sum(r.get('grave', False) for r in results)}")
    print(f"Relatório: {path}")


if __name__ == "__main__":
    main()
