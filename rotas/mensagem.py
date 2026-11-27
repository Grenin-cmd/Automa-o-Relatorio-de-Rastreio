"""Mensagem do dia (aba da Análise de rastreio): edição por placa e Excel do aprendiz."""
from __future__ import annotations

from io import BytesIO

from flask import Blueprint, flash, redirect, request, send_file, session

from mensagem_saidas.relatorio import chave_sugestao, gerar_excel_pontos
from mensagem_saidas.sugestao import sugerir_nome
from rotas.analise import arquivo_atual, resultado_mensagem
from rotas.comum import login_required

bp = Blueprint("mensagem", __name__)

_MAX_SUGESTOES = 10


@bp.route("/mensagem_saidas")
def mensagem_saidas():
    return redirect("/?aba=mensagem")


@bp.route("/mensagem/editar", methods=["POST"])
@login_required
def editar():
    placa = request.form.get("placa", "").strip()
    edicoes = dict(session.get("mensagem_edicoes", {}))
    if placa:
        if request.form.get("acao") == "restaurar":
            edicoes.pop(placa, None)
            flash(f"{placa}: texto original restaurado.", "success")
        else:
            texto = " ".join(request.form.get("texto", "").split())
            if texto:
                edicoes[placa] = texto
                flash(f"{placa}: linha atualizada.", "success")
    session["mensagem_edicoes"] = edicoes
    return redirect(f"/?aba=mensagem#placa-{placa}")


@bp.route("/mensagem/excel")
@login_required
def excel():
    resultado = resultado_mensagem(arquivo_atual())
    if resultado is None or not resultado.data_mensagem:
        flash("Envie a planilha da SS primeiro.", "warning")
        return redirect("/")
    cache = dict(session.get("mensagem_sugestoes", {}))
    pendentes = [p for p in resultado.pontos_sem_poi if p.lat is not None and chave_sugestao(p.lat, p.lon) not in cache]
    for p in pendentes[:_MAX_SUGESTOES]:
        cache[chave_sugestao(p.lat, p.lon)] = sugerir_nome(p.lat, p.lon, timeout_s=3.0) or ""
    session["mensagem_sugestoes"] = cache
    dados = gerar_excel_pontos(resultado.pontos_sem_poi, cache)
    return send_file(BytesIO(dados), as_attachment=True,
                     download_name=f"pontos_para_cadastrar_na_ss_{resultado.data_mensagem:%d-%m-%Y}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
