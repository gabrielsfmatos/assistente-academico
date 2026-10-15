"""Mostra no terminal a situação atual: frequência e CR.

Uso:
    python -m scripts.show_summary
    python -m scripts.show_summary --today 2026-11-20   (simula outra data)
"""

import argparse
from datetime import date

from app.db import get_engine, get_session, init_db
from app.services.attendance import summarize_all
from app.services.grades import current_cr

STATUS_LABEL = {
    "ok": "ok",
    "atencao": "ATENÇÃO",
    "reprovado_por_falta": "REPROVADO POR FALTA",
    "nao_cobra": "não cobra frequência",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    engine = get_engine()
    init_db(engine)
    with get_session(engine) as db:
        summaries = summarize_all(db, args.today)
        cr = current_cr(db)

    print(f"Situação em {args.today:%d/%m/%Y}\n")
    print(f"{'Disciplina':<42}{'Faltas':>8}{'Limite':>8}{'Restam':>8}{'Freq. até hoje':>16}  Status")
    for s in summaries:
        freq = f"{s.frequency_to_date:.1%}" if s.frequency_to_date is not None else "—"
        print(
            f"{s.course_name:<42}{s.absences:>8}{s.max_absences:>8}"
            f"{s.remaining_absences:>8}{freq:>16}  {STATUS_LABEL[s.status]}"
        )
    print(f"\nCR acumulado: {cr}")


if __name__ == "__main__":
    main()
