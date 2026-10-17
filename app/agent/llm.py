"""Adaptador do provedor de LLM (Google Gemini).

O resto do agente só conhece as classes ToolCall e LLMReply. Para trocar de
provedor (ex.: Claude, OpenAI), basta escrever outra classe com os mesmos
métodos `send_user` e `send_tool_results`.
"""

import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import errors, types

DEFAULT_MODEL = "gemini-2.5-flash"
RETRYABLE_CODES = {429, 500, 503}  # limite de uso e instabilidade do servidor

# Intervalo mínimo entre chamadas, compartilhado por todas as conversas do processo.
# Ex.: limite de 10 chamadas/minuto -> GEMINI_MIN_INTERVAL=6
_last_call = 0.0


class DailyQuotaExceeded(RuntimeError):
    """A cota diária do plano gratuito acabou: não adianta tentar de novo hoje."""


def _wait_rate_limit() -> None:
    global _last_call
    interval = float(os.getenv("GEMINI_MIN_INTERVAL", "0"))
    wait = _last_call + interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _retry_delay(exc: errors.APIError, default: float) -> float:
    """Usa o tempo de espera sugerido pela API (ex.: 'retryDelay': '33s'), se houver."""
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    return float(match.group(1)) + 1 if match else default


def thinking_config(model: str) -> types.ThinkingConfig:
    """Quanto o modelo "pensa" antes de responder (GEMINI_THINKING no .env).

    Nossos pedidos são simples, então pouco raciocínio = respostas mais rápidas.
    Modelos 2.5 usam um orçamento de tokens; modelos 3.x usam um nível.
    """
    level = os.getenv("GEMINI_THINKING", "low").lower()  # minimal | low | medium | high
    if model.startswith("gemini-2.5"):
        budgets = {"minimal": 0, "low": 512, "medium": 2048, "high": 8192}
        if "pro" in model:  # o 2.5 Pro não aceita desligar o raciocínio
            budgets["minimal"] = 128
        return types.ThinkingConfig(thinking_budget=budgets.get(level, 512))
    return types.ThinkingConfig(thinking_level=level.upper())


@dataclass
class ToolCall:
    name: str
    args: dict
    id: Optional[str] = None


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class GeminiChat:
    """Uma conversa com o Gemini, com ferramentas declaradas e execução manual.

    O histórico guarda o conteúdo exatamente como o Gemini devolveu: modelos
    recentes exigem que partes como a "assinatura de raciocínio" voltem intactas.
    """

    def __init__(self, system_prompt: str, declarations: list[dict], client=None, model=None):
        self.client = client or genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.history: list[types.Content] = []
        self.calls: list[float] = []  # duração (s) de cada chamada à API
        self.config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=d["name"],
                            description=d["description"],
                            parameters_json_schema=d["parameters"],
                        )
                        for d in declarations
                    ]
                )
            ],
            # Nós executamos as ferramentas (para validar e registrar tudo).
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=thinking_config(self.model),
        )

    def _generate(self, attempts: int = 6) -> LLMReply:
        for attempt in range(attempts):
            _wait_rate_limit()
            start = time.perf_counter()
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=self.history, config=self.config
                )
                self.calls.append(time.perf_counter() - start)
                break
            except errors.APIError as exc:
                if exc.code == 429 and "PerDay" in str(exc):
                    raise DailyQuotaExceeded(
                        f"Cota diária do modelo {self.model} esgotada. Tente amanhã ou troque "
                        "GEMINI_MODEL no .env."
                    ) from exc
                if exc.code not in RETRYABLE_CODES or attempt == attempts - 1:
                    raise
                wait = _retry_delay(exc, default=15 * (attempt + 1))
                reason = "limite de uso da API" if exc.code == 429 else "servidor instável"
                print(f"  [aviso] {reason} ({exc.code}); tentando de novo em {wait:.0f}s...", file=sys.stderr)
                time.sleep(wait)

        candidate = (response.candidates or [None])[0]
        content = candidate.content if candidate else None
        if content is None or not content.parts:
            return LLMReply(text="Desculpe, não consegui responder agora. Pode repetir?")
        self.history.append(content)

        calls = [
            ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {}), id=p.function_call.id)
            for p in content.parts
            if p.function_call
        ]
        text = "".join(p.text for p in content.parts if p.text and not p.thought).strip()
        return LLMReply(text=text, tool_calls=calls)

    def send_user(self, text: str) -> LLMReply:
        self.history.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        return self._generate()

    def send_tool_results(self, results: list[tuple[ToolCall, dict]]) -> LLMReply:
        parts = [
            types.Part(
                function_response=types.FunctionResponse(id=call.id, name=call.name, response=result)
            )
            for call, result in results
        ]
        self.history.append(types.Content(role="user", parts=parts))
        return self._generate()
