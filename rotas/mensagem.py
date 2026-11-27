"""Mensagem do dia: a tela própria foi removida (agora é uma aba da Análise de rastreio)."""
from __future__ import annotations

from flask import Blueprint, redirect

bp = Blueprint("mensagem", __name__)


@bp.route("/mensagem_saidas")
def mensagem_saidas():
    return redirect("/?aba=mensagem")
