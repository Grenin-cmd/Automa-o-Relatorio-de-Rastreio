"""Mensagem de saídas das carretas (WhatsApp) e cadastro de locais importantes."""
from __future__ import annotations

import os
from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

import banco
from arquivos import remover_temporario, salvar_upload
from mensagem_saidas.leitura import FormatoSSDesconhecido, ler_exportacao_ss
from mensagem_saidas.locais import TIPOS
from mensagem_saidas.regras import ResultadoMensagem, montar_mensagem
from mensagem_saidas.relatorio import gerar_excel_pontos
from mensagem_saidas.sugestao import sugerir_nome
from rotas.comum import login_required

bp = Blueprint("mensagem", __name__)

_MAX_SUGESTOES = 10  # limita consultas ao OpenStreetMap por planilha


def _numero(texto: str | None) -> float | None:
    texto = (texto or "").strip().replace(",", ".")
    try:
        return float(texto) if texto else None
    except ValueError:
        return None


def _dados_local(form) -> dict:
    aliases = [a.strip() for a in form.get("aliases_ss", "").replace("|", "\n").splitlines() if a.strip()]
    return {
        "nome_exibicao": form.get("nome_exibicao", ""),
        "genero": form.get("genero", "o"),
        "tipo": form.get("tipo", "OUTRO"),
        "aliases_ss": aliases,
        "latitude": _numero(form.get("latitude")),
        "longitude": _numero(form.get("longitude")),
        "raio_m": _numero(form.get("raio_m")) or 250,
    }


def _resultado_da_sessao() -> ResultadoMensagem | None:
    caminho = session.get("mensagem_arquivo_path")
    if not caminho or not os.path.exists(caminho):
        return None
    try:
        df = ler_exportacao_ss(caminho)
    except FormatoSSDesconhecido as erro:
        flash(str(erro), "danger")
        remover_temporario(session.pop("mensagem_arquivo_path", None))
        session.pop("mensagem_arquivo_nome", None)
        return None
    return montar_mensagem(df, banco.listar_locais(), set(session.get("mensagem_ignorados", [])))


def _sugestoes(resultado: ResultadoMensagem) -> dict[str, str]:
    """Sugestões por item, guardadas na sessão para não consultar a cada recarga."""
    cache = dict(session.get("mensagem_sugestoes", {}))
    pendentes = [i for i in resultado.conferir
                 if i.motivo == "local_desconhecido" and i.parada and i.parada.lat is not None and i.chave not in cache]
    for item in pendentes[:_MAX_SUGESTOES]:
        cache[item.chave] = sugerir_nome(item.parada.lat, item.parada.lon, timeout_s=3.0) or ""
    session["mensagem_sugestoes"] = cache
    return cache


@bp.route("/mensagem_saidas", methods=["GET", "POST"])
@login_required
def mensagem_saidas():
    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Selecione a planilha exportada da SS.", "warning")
        else:
            remover_temporario(session.get("mensagem_arquivo_path"))
            session["mensagem_arquivo_path"] = salvar_upload(arquivo)
            session["mensagem_arquivo_nome"] = arquivo.filename
            session["mensagem_ignorados"] = []
            session["mensagem_sugestoes"] = {}
        return redirect(url_for("mensagem.mensagem_saidas"))

    resultado = _resultado_da_sessao()
    sugestoes = _sugestoes(resultado) if resultado else {}
    return render_template(
        "mensagem_saidas.html",
        resultado=resultado,
        sugestoes=sugestoes,
        arquivo_nome=session.get("mensagem_arquivo_nome", ""),
        tipos=TIPOS,
    )


@bp.route("/mensagem_saidas/aceitar", methods=["POST"])
@login_required
def aceitar_local():
    try:
        banco.salvar_local(_dados_local(request.form))
        flash("Local cadastrado. A mensagem foi gerada novamente.", "success")
    except ValueError as erro:
        flash(str(erro), "danger")
    return redirect(url_for("mensagem.mensagem_saidas"))


@bp.route("/mensagem_saidas/ignorar", methods=["POST"])
@login_required
def ignorar_item():
    chave = request.form.get("chave", "")
    if chave:
        session["mensagem_ignorados"] = [*session.get("mensagem_ignorados", []), chave]
    return redirect(url_for("mensagem.mensagem_saidas"))


@bp.route("/mensagem_saidas/relatorio.xlsx")
@login_required
def relatorio_pontos():
    resultado = _resultado_da_sessao()
    if resultado is None:
        flash("Gere a mensagem primeiro.", "warning")
        return redirect(url_for("mensagem.mensagem_saidas"))
    dados = gerar_excel_pontos(resultado.conferir, session.get("mensagem_sugestoes", {}))
    nome = f"pontos_sem_cadastro_{resultado.data_mensagem:%d-%m-%Y}.xlsx"
    return send_file(BytesIO(dados), as_attachment=True, download_name=nome,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/locais_importantes", methods=["GET", "POST"])
@login_required
def locais_importantes():
    if request.method == "POST":
        acao = request.form.get("acao")
        local_id = request.form.get("local_id") or None
        try:
            if acao == "salvar":
                banco.salvar_local(_dados_local(request.form), local_id)
                flash("Local salvo.", "success")
            elif acao == "excluir" and local_id:
                banco.excluir_local(local_id)
                flash("Local excluído.", "success")
            elif acao == "marcar_ss" and local_id:
                banco.marcar_cadastrado_na_ss(local_id, request.form.get("valor") == "1")
        except ValueError as erro:
            flash(str(erro), "danger")
        return redirect(url_for("mensagem.locais_importantes"))

    locais = banco.listar_locais()
    editar = next((l for l in locais if l.id == request.args.get("editar")), None)
    return render_template("locais_importantes.html", locais=locais, editar=editar, tipos=TIPOS)
