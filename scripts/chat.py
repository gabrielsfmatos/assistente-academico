"""Conversa com o agente pelo terminal (antes do Telegram).

Uso:
    python -m scripts.chat                    (usa o banco real e a data de hoje)
    python -m scripts.chat --today 2026-10-15 (simula outra data)
    python -m scripts.chat --quiet            (esconde as chamadas de ferramenta)

Digite "sair" para encerrar.
"""

import argparse
import json
import time
from datetime import date

from dotenv import load_dotenv

from app.agent.agent import Agent
from app.db import get_engine, init_db


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    engine = get_engine()
    init_db(engine)
    agent = Agent(engine, today_fn=(lambda: args.today) if args.today else date.today)
    print("Assistente acadêmico. Digite 'sair' para encerrar.\n")

    while True:
        try:
            message = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message.lower() in {"sair", "exit", "quit"}:
            break
        if not message:
            continue
        start = time.perf_counter()
        calls_before = len(getattr(agent.chat, "calls", []))
        reply = agent.reply(message)
        elapsed = time.perf_counter() - start
        api_calls = getattr(agent.chat, "calls", [])[calls_before:]
        if not args.quiet:
            for t in reply.trace:
                print(f"  [ferramenta] {t.name}({json.dumps(t.args, ensure_ascii=False)})")
                print(f"     -> {json.dumps(t.result, ensure_ascii=False)[:300]}")
        print(f"agente> {reply.text}")
        detail = ", ".join(f"{c:.1f}s" for c in api_calls)
        print(f"  ({elapsed:.1f}s no total; {len(api_calls)} chamada(s) ao modelo: {detail})\n")


if __name__ == "__main__":
    main()
