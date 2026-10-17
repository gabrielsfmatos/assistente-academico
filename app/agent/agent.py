"""Laço do agente: mensagem -> modelo -> ferramentas -> modelo -> resposta."""

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from sqlmodel import Session

from app.agent.llm import GeminiChat, ToolCall
from app.agent.prompt import build_system_prompt
from app.agent.tools import DECLARATIONS, WRITE_TOOLS, AgentState, AgentTools
from app.services.changes import ChangeBatch

MAX_STEPS = 6  # limite de idas e voltas modelo <-> ferramentas por mensagem


@dataclass
class ToolTrace:
    name: str
    args: dict
    result: dict


@dataclass
class AgentReply:
    text: str
    trace: list[ToolTrace] = field(default_factory=list)

    @property
    def wrote(self) -> bool:
        return any(t.name in WRITE_TOOLS for t in self.trace)


ChatFactory = Callable[[str, list[dict]], object]


class Agent:
    """Uma conversa com o usuário.

    - Cada mensagem do usuário gera um lote de alterações (para o "desfazer").
    - A conversa (histórico do modelo) e a ação pendente duram entre mensagens.
    """

    def __init__(
        self,
        engine,
        today_fn: Callable[[], date] = date.today,
        chat_factory: Optional[ChatFactory] = None,
    ):
        self.engine = engine
        self.today_fn = today_fn
        self.chat_factory = chat_factory or (lambda prompt, decls: GeminiChat(prompt, decls))
        self.state = AgentState()
        self.chat = None
        self.chat_day: Optional[date] = None

    def _ensure_chat(self, db: Session, today: date) -> None:
        # Nova conversa a cada dia: o prompt traz a data de hoje.
        if self.chat is None or self.chat_day != today:
            self.chat = self.chat_factory(build_system_prompt(db, today), DECLARATIONS)
            self.chat_day = today

    def reply(self, message: str) -> AgentReply:
        today = self.today_fn()
        batch = ChangeBatch(source="agente")
        trace: list[ToolTrace] = []
        with Session(self.engine) as db:
            self._ensure_chat(db, today)
            tools = AgentTools(db, today, batch, self.state)
            response = self.chat.send_user(message)
            for _ in range(MAX_STEPS):
                if not response.tool_calls:
                    break
                results: list[tuple[ToolCall, dict]] = []
                for call in response.tool_calls:
                    result = tools.call(call.name, call.args)
                    trace.append(ToolTrace(call.name, call.args, result))
                    results.append((call, result))
                response = self.chat.send_tool_results(results)
            else:
                return AgentReply(
                    "Não consegui concluir esse pedido. Pode reformular?", trace
                )
        return AgentReply(response.text or "Feito.", trace)
