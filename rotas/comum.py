"""Recursos compartilhados pelas rotas: usuário logado, decoradores de
autenticação, serviços em memória e limpeza de uploads da sessão."""
from __future__ import annotations

from functools import wraps
from typing import Any

from flask import flash, redirect, request, session, url_for

import seguranca
from dispositivos_service import normalizar_payload_dispositivo
from veiculos_service import VeiculosService

try:
    from agente_refinamento import agente_ia
except Exception as e:  # pragma: no cover - IA é opcional
    print(f"[AVISO] Falha ao importar agente_ia: {e}")
    agente_ia = None

VEICULOS_SERVICE = VeiculosService()
LIMITADOR_LOGIN = seguranca.LimitadorTentativas(max_falhas=5, janela_seg=900)
from arquivos import remover_temporario
from banco import get_connection


def usuario_atual() -> dict[str, Any] | None:
    usuario_id = session.get("usuario_id")
    if not usuario_id:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, nome, pode_cadastrar_usuarios, deve_trocar_senha FROM usuarios WHERE id = ? AND ativo = 1",
            (usuario_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        usuario = usuario_atual()
        if usuario is None:
            return redirect(url_for("auth.login", proxima=request.path))
        if usuario.get("deve_trocar_senha") and request.endpoint != "auth.trocar_senha":
            flash("Defina uma nova senha para continuar.", "warning")
            return redirect(url_for("auth.trocar_senha"))
        return view(*args, **kwargs)

    return wrapped


def api_auth_required(view):
    """APIs aceitam um token (variável API_TOKEN, enviado em
    `Authorization: Bearer <token>` ou `X-API-Key`) ou um usuário logado."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if seguranca.token_api_valido(request.headers) or usuario_atual() is not None:
            return view(*args, **kwargs)
        return {"ok": False, "erro": "Não autorizado."}, 401

    return wrapped


def cleanup_cached_file(incluir_auditoria: bool = False) -> None:
    """Apaga o upload temporário da análise (e, se pedido, os da auditoria)."""
    chaves = [("uploaded_file_path", "uploaded_file_name")]
    if incluir_auditoria:
        chaves += [
            ("auditoria_carregamento_path", "auditoria_carregamento_nome"),
            ("auditoria_rastreio_path", "auditoria_rastreio_nome"),
        ]
    for chave_caminho, chave_nome in chaves:
        remover_temporario(session.pop(chave_caminho, None))
        session.pop(chave_nome, None)


def registrar_dispositivo_recebido(payload: dict[str, Any]) -> dict[str, Any]:
    normalizado = normalizar_payload_dispositivo(payload)
    veiculo = VEICULOS_SERVICE.registrar_ou_atualizar(payload)
    return {
        **normalizado,
        "veiculo_id": veiculo["veiculo_id"],
        "ultima_posicao": veiculo["ultima_posicao"],
    }
