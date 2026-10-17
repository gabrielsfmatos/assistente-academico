"""Senha de acesso ao site.

Uma senha só (SITE_PASSWORD no .env), já que o sistema tem um único usuário.
Depois do login, o navegador guarda um cookie com uma "assinatura" da senha
(HMAC). A senha em si nunca vai para o cookie, e trocar a senha no .env
desconecta todos os aparelhos.

Sem SITE_PASSWORD o site fica aberto: serve só para testar no próprio
computador. No servidor a senha é obrigatória.
"""

import hashlib
import hmac
from typing import Optional

COOKIE_NAME = "sessao"
COOKIE_MAX_AGE = 60 * 60 * 24 * 90  # 90 dias logado no mesmo aparelho
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
