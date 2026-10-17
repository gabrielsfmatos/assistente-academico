"""Resumo do uso real do bot (data/uso_telegram.jsonl): o "depois" do Show Case.

Uso:
    python -m scripts.usage_report
"""

import json
from collections import Counter
from pathlib import Path
from statistics import mean, median

LOG = Path("data") / "uso_telegram.jsonl"


def main() -> None:
    if not LOG.exists():
        raise SystemExit("Ainda não há registro de uso. Converse com o bot primeiro.")
    entries = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line]
    messages = [e for e in entries if "mensagem" in e]
    answered = [e for e in messages if "resposta" in e]
    reported = [e for e in entries if "erro_reportado" in e]
    system_errors = [e for e in messages if "erro_sistema" in e]
    days = sorted({e["ts"][:10] for e in messages})
    tools = Counter(t["nome"] for e in answered for t in e["ferramentas"])
    times = [e["segundos"] for e in answered]

    print(f"Período: {days[0]} a {days[-1]} ({len(days)} dia(s) com uso)" if days else "Sem mensagens.")
    print(f"Mensagens: {len(messages)} (alteraram dados: {sum(e['alterou_dados'] for e in answered)})")
    if times:
        print(f"Tempo de resposta: mediana {median(times):.1f}s, média {mean(times):.1f}s, máx {max(times):.1f}s")
    print(f"Erros reportados por você (/erro): {len(reported)}")
    for e in reported:
        print(f"   - {e['ts'][:16]}: {e['erro_reportado']}")
    print(f"Falhas do sistema (API etc.): {len(system_errors)}")
    print("Ferramentas mais usadas:")
    for name, count in tools.most_common():
        print(f"   {name}: {count}")


if __name__ == "__main__":
    main()
