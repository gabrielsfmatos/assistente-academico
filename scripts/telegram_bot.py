"""Bot do Telegram: o mesmo agente do terminal, agora no celular.

Uso (na raiz do projeto, com o ambiente virtual ativo):
    python -m scripts.telegram_bot

Funciona por "long polling": o programa no seu computador busca as mensagens
no Telegram. Não precisa de endereço público. O bot só responde enquanto o
programa estiver rodando.

Segurança: o bot responde APENAS ao usuário configurado em TELEGRAM_USER_ID.
Se ele estiver vazio, o bot só informa o seu ID (para você colocar no .env).
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.agent.agent import Agent
from app.db import get_engine, init_db

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # esconde o log de cada requisição
log = logging.getLogger("bot")

# Registro de uso real (fica em data/, fora do GitHub): base para medir o "depois".
USAGE_LOG = Path("data") / "uso_telegram.jsonl"


def log_usage(entry: dict) -> None:
    USAGE_LOG.parent.mkdir(exist_ok=True)
    with USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


WELCOME = (
    "Oi! Sou seu assistente acadêmico. Exemplos do que posso fazer:\n"
    "• faltei hoje\n"
    "• quantas faltas ainda posso ter em ACD?\n"
    "• tirei 9,3 na P1 de EI\n"
    "• tenho prova de LPP dia 19/11\n"
    "• como fica meu CR se eu fechar com 10 em LPP, 9 em AP...\n"
    "• desfaça a última alteração\n\n"
    "Se eu errar, mande /erro e o que deu errado (ex.: /erro registrou a disciplina errada)."
)


def allowed_user_id() -> int | None:
    value = os.getenv("TELEGRAM_USER_ID", "").strip()
    return int(value) if value.isdigit() else None


async def check_user(update: Update) -> bool:
    """Só o dono do bot pode usá-lo. Sem ID configurado, informa o ID e para."""
    user = update.effective_user
    allowed = allowed_user_id()
    if allowed is None:
        await update.message.reply_text(
            f"Seu ID do Telegram é {user.id}.\n"
            "Coloque no .env a linha TELEGRAM_USER_ID=" f"{user.id} e reinicie o bot."
        )
        return False
    if user.id != allowed:
        log.warning("Mensagem ignorada de usuário não autorizado: %s", user.id)
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await check_user(update):
        await update.message.reply_text(WELCOME)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_user(update):
        return
    agent: Agent = context.application.bot_data["agent"]
    lock: asyncio.Lock = context.application.bot_data["lock"]
    text = update.message.text
    await update.message.chat.send_action(ChatAction.TYPING)
    start = time.perf_counter()
    try:
        # O agente é síncrono (chama a API e o banco); roda em outra thread para não
        # travar o bot. O lock garante uma mensagem por vez, na ordem em que chegaram.
        async with lock:
            reply = await asyncio.to_thread(agent.reply, text)
    except Exception as exc:
        log.exception("Erro ao responder: %r", text)
        log_usage({"ts": datetime.now(), "mensagem": text, "erro_sistema": repr(exc),
                   "segundos": round(time.perf_counter() - start, 1)})
        await update.message.reply_text(
            "Tive um problema para responder agora. Tente de novo em instantes. "
            "Se algo chegou a ser registrado, você pode pedir \"desfaça a última alteração\"."
        )
        return
    elapsed = round(time.perf_counter() - start, 1)
    for t in reply.trace:
        log.info("ferramenta %s %s", t.name, t.args)
    log_usage(
        {
            "ts": datetime.now(),
            "mensagem": text,
            "resposta": reply.text,
            "ferramentas": [{"nome": t.name, "args": t.args, "ok": t.result.get("ok")} for t in reply.trace],
            "alterou_dados": reply.wrote,
            "segundos": elapsed,
        }
    )
    await update.message.reply_text(reply.text)


async def report_error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/erro <descrição>: marca que a última resposta do agente estava errada."""
    if not await check_user(update):
        return
    description = " ".join(context.args) or "(sem descrição)"
    log_usage({"ts": datetime.now(), "erro_reportado": description})
    await update.message.reply_text(
        "Anotado, obrigado! Se algo foi gravado errado, você pode pedir \"desfaça a última alteração\"."
    )


def main() -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN não encontrado no .env (crie o bot com o @BotFather).")
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY não encontrada no .env.")

    engine = get_engine()
    init_db(engine)

    app = Application.builder().token(token).build()
    app.bot_data["agent"] = Agent(engine, today_fn=date.today)
    app.bot_data["lock"] = asyncio.Lock()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("erro", report_error))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if allowed_user_id() is None:
        log.info("TELEGRAM_USER_ID vazio: mande qualquer mensagem ao bot para descobrir seu ID.")
    log.info("Bot rodando. Pressione Ctrl+C para parar.")
    app.run_polling()


if __name__ == "__main__":
    main()
