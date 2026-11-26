"""Utilitários de segurança da aplicação web.

Concentra proteção CSRF, limite de tentativas de login, validação de
redirecionamentos, chave secreta persistente e autenticação das APIs.
"""
from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from markupsafe import Markup, escape

CSRF_SESSION_KEY = "_csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

SENHA_TAMANHO_MINIMO = 8


# ---------------------------------------------------------------------------
# Chave secreta
# ---------------------------------------------------------------------------
def carregar_secret_key(data_dir: str) -> str:
    """Usa FLASK_SECRET_KEY se definida; senão lê/gera uma chave persistida em
    disco. Sem isso, cada reinício gerava uma chave nova e derrubava todas as
    sessões abertas."""
    chave_env = os.environ.get("FLASK_SECRET_KEY")
    if chave_env:
        return chave_env

    caminho = os.path.join(data_dir, ".secret_key")
    try:
        with open(caminho, "r", encoding="utf-8") as fh:
            chave = fh.read().strip()
        if chave:
            return chave
    except FileNotFoundError:
        pass

    chave = secrets.token_hex(32)
    fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(chave)
    return chave


# ---------------------------------------------------------------------------
# Redirecionamento seguro
# ---------------------------------------------------------------------------
def destino_seguro(destino: str | None, padrao: str) -> str:
    """Aceita apenas caminhos relativos do próprio site (evita open redirect)."""
    if not destino:
        return padrao
    destino = destino.strip()
    if not destino.startswith("/") or destino.startswith("//") or "\\" in destino:
        return padrao
    partes = urlsplit(destino)
    if partes.scheme or partes.netloc:
        return padrao
    return destino


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def obter_csrf_token(sessao) -> str:
    token = sessao.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        sessao[CSRF_SESSION_KEY] = token
    return token


def csrf_input_html(sessao) -> Markup:
    token = obter_csrf_token(sessao)
    return Markup(f'<input type="hidden" name="{CSRF_FORM_FIELD}" value="{escape(token)}">')


def csrf_valido(sessao, token_enviado: str | None) -> bool:
    esperado = sessao.get(CSRF_SESSION_KEY)
    if not esperado or not token_enviado:
        return False
    return hmac.compare_digest(str(esperado), str(token_enviado))


# ---------------------------------------------------------------------------
# Limite de tentativas de login
# ---------------------------------------------------------------------------
class LimitadorTentativas:
    """Bloqueia temporariamente uma chave (ex: IP + usuário) após muitas falhas."""

    def __init__(self, max_falhas: int = 5, janela_seg: int = 900) -> None:
        self.max_falhas = max_falhas
        self.janela_seg = janela_seg
        self._falhas: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _limpar(self, chave: str, agora: float) -> deque[float]:
        fila = self._falhas[chave]
        while fila and agora - fila[0] > self.janela_seg:
            fila.popleft()
        return fila

    def bloqueado(self, chave: str) -> bool:
        with self._lock:
            return len(self._limpar(chave, time.monotonic())) >= self.max_falhas

    def registrar_falha(self, chave: str) -> None:
        with self._lock:
            agora = time.monotonic()
            self._limpar(chave, agora).append(agora)

    def limpar(self, chave: str) -> None:
        with self._lock:
            self._falhas.pop(chave, None)


# ---------------------------------------------------------------------------
# Senhas e API
# ---------------------------------------------------------------------------
def validar_nova_senha(senha: str, confirmacao: str | None = None) -> str | None:
    """Retorna a mensagem de erro, ou None se a senha for aceitável."""
    if len(senha) < SENHA_TAMANHO_MINIMO:
        return f"A senha deve ter pelo menos {SENHA_TAMANHO_MINIMO} caracteres."
    if confirmacao is not None and senha != confirmacao:
        return "A confirmação não confere com a nova senha."
    return None


def gerar_senha_temporaria() -> str:
    return secrets.token_urlsafe(12)


def token_api_valido(headers) -> bool:
    """Valida o token de API enviado em `Authorization: Bearer` ou `X-API-Key`
    contra a variável de ambiente API_TOKEN."""
    esperado = os.environ.get("API_TOKEN", "")
    if not esperado:
        return False
    enviado = headers.get("X-API-Key", "")
    auth = headers.get("Authorization", "")
    if not enviado and auth.lower().startswith("bearer "):
        enviado = auth[7:].strip()
    return bool(enviado) and hmac.compare_digest(enviado, esperado)
