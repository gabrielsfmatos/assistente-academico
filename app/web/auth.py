"""Senha de acesso ao site.

Uma senha só (SITE_PASSWORD no .env), já que o sistema tem um único usuário.
Depois do login, o navegador guarda um cookie com uma "assinatura" da senha
(HMAC). A senha em si nunca vai para o cookie, e trocar a senha no .env
desconecta todos os aparelhos.

Sem SITE_PASSWORD o site fica aberto: serve só para testar no próprio
computador. No servidor a senha é obrigatória.

Como o site fica público (Tailscale Funnel), há também um limite de tentativas:
depois de MAX_FAILURES senhas erradas em WINDOW segundos, aquele endereço
fica bloqueado até a janela passar.
"""

import hashlib
import hmac
import time
from collections import defaultdict, deque
from typing import Optional

COOKIE_NAME = "sessao"
COOKIE_MAX_AGE = 60 * 60 * 24 * 90  # "manter conectado": 90 dias no mesmo aparelho
MIN_PASSWORD_LENGTH = 12
MAX_FAILURES = 5
WINDOW = 15 * 60  # segundos
PUBLIC_PATHS = ("/login", "/static/")


def session_token(password: str) -> str:
    return hmac.new(password.encode(), b"assistente-academico/sessao", hashlib.sha256).hexdigest()


def is_logged_in(cookie: Optional[str], password: str) -> bool:
    return bool(cookie) and hmac.compare_digest(cookie, session_token(password))


def check_password(attempt: str, password: str) -> bool:
    return hmac.compare_digest(attempt.encode(), password.encode())


def is_public(path: str) -> bool:
    return path == "/login" or any(path.startswith(p) for p in PUBLIC_PATHS if p.endswith("/"))


def safe_next(target: Optional[str]) -> str:
    """Só aceita voltar para uma página do próprio site (evita redirecionar para fora)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


class LoginLimiter:
    """Conta senhas erradas por endereço de origem e bloqueia depois de MAX_FAILURES."""

    def __init__(self, max_failures: int = MAX_FAILURES, window: int = WINDOW, clock=time.monotonic):
        self.max_failures = max_failures
        self.window = window
        self.clock = clock
        self._failures: dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str) -> deque:
        now = self.clock()
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """Segundos até poder tentar de novo (0 = liberado)."""
        q = self._prune(key)
        if len(q) < self.max_failures:
            return 0
        return max(1, int(self.window - (self.clock() - q[0])))

    def fail(self, key: str) -> None:
        self._prune(key).append(self.clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def client_key(headers, client_host: Optional[str]) -> str:
    """Endereço de quem está tentando entrar (atrás do Tailscale vem no X-Forwarded-For)."""
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return client_host or "desconhecido"


def is_https(scheme: str, headers) -> bool:
    """Atrás do Tailscale o site recebe HTTP, mas o navegador está em HTTPS."""
    host = headers.get("host", "")
    return (
        scheme == "https"
        or headers.get("x-forwarded-proto") == "https"
        or host.split(":")[0].endswith(".ts.net")
    )
