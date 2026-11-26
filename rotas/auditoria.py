"""Auditoria de roteiro (planejado x executado)."""
from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, flash, render_template, request, session

import auditoria_roteiro

bp = Blueprint("auditoria", __name__)
from arquivos import carregar_arquivo, remover_temporario, salvar_upload
from banco import get_saved_pois
from rotas.comum import agente_ia, login_required


@bp.route("/auditoria_roteiro", methods=["GET", "POST"])
@login_required
def auditoria_roteiro_view():
    """Módulo de Auditoria de Roteiro: cruza a planilha de carregamento
    (romaneio) com o log de rastreio de uma placa específica, usando uma
    tolerância de distância configurável, para identificar entregas
    executadas vs. não executadas. Gera um resumo executivo via IA quando
    disponível, com fallback gracioso para os dados brutos caso a IA falhe.
    """
    resultado_auditoria: dict[str, Any] | None = None
    resumo_ia: str | None = None
    ia_indisponivel = False
    placa_escolhida = request.form.get("placa_auditoria", "").strip()
    try:
        tolerancia_m = float(request.form.get("tolerancia_m", 50) or 50)
    except (TypeError, ValueError):
        tolerancia_m = 50.0

    placas_disponiveis: list[str] = []
    file_name_carregamento = session.get("auditoria_carregamento_nome", "")
    file_name_rastreio = session.get("auditoria_rastreio_nome", "")

    if request.method == "POST":
        arquivo_carregamento = request.files.get("arquivo_carregamento")
        arquivo_rastreio = request.files.get("arquivo_rastreio")

        caminho_carregamento = session.get("auditoria_carregamento_path")
        caminho_rastreio = session.get("auditoria_rastreio_path")

        try:
            if arquivo_carregamento and arquivo_carregamento.filename:
                remover_temporario(caminho_carregamento)
                caminho_carregamento = salvar_upload(arquivo_carregamento)
                session["auditoria_carregamento_path"] = caminho_carregamento
                session["auditoria_carregamento_nome"] = arquivo_carregamento.filename
                file_name_carregamento = arquivo_carregamento.filename

            if arquivo_rastreio and arquivo_rastreio.filename:
                remover_temporario(caminho_rastreio)
                caminho_rastreio = salvar_upload(arquivo_rastreio)
                session["auditoria_rastreio_path"] = caminho_rastreio
                session["auditoria_rastreio_nome"] = arquivo_rastreio.filename
                file_name_rastreio = arquivo_rastreio.filename
        except Exception as error:
            flash(f"Erro ao salvar arquivo enviado: {error}", "danger")
            caminho_carregamento = None
            caminho_rastreio = None

        if not caminho_carregamento or not os.path.exists(caminho_carregamento):
            flash("Envie a planilha de carregamento (romaneio) para continuar.", "warning")
        elif not caminho_rastreio or not os.path.exists(caminho_rastreio):
            flash("Envie o arquivo de logs de rastreio para continuar.", "warning")
        else:
            try:
                df_carregamento = carregar_arquivo(caminho_carregamento)
                df_rastreio = carregar_arquivo(caminho_rastreio)

                # Descobre as placas disponíveis na planilha de carregamento
                # para popular o seletor dinâmico da UI (dropdown).
                try:
                    carregamento_normalizado = auditoria_roteiro.normalize_columns(df_carregamento)
                    col_placa_disp = auditoria_roteiro._resolver_coluna_flex(
                        carregamento_normalizado, auditoria_roteiro._ALIASES_PLACA
                    )
                    if col_placa_disp:
                        placas_disponiveis = sorted(
                            carregamento_normalizado[col_placa_disp]
                            .dropna().astype(str).str.strip().str.upper().unique().tolist()
                        )
                except Exception:
                    placas_disponiveis = []

                pois_cadastrados = get_saved_pois()
                resultado_auditoria = auditoria_roteiro.executar_auditoria(
                    df_carregamento, df_rastreio, placa_escolhida, pois_cadastrados, tolerancia_m
                )

                # Plano B: tenta gerar o resumo executivo via IA com um payload
                # minúsculo (apenas estatísticas agregadas). Se a IA falhar,
                # atingir rate limit ou estiver indisponível, resumo_ia fica
                # None e a auditoria continua sendo exibida normalmente.
                if agente_ia:
                    resumo_ia = agente_ia.gerar_resumo_auditoria(resultado_auditoria["estatisticas"])
                    ia_indisponivel = resumo_ia is None
                else:
                    resumo_ia = None
                    ia_indisponivel = True
            except Exception as error:
                flash(f"Erro ao executar a auditoria: {error}", "danger")

    return render_template(
        "auditoria_roteiro.html",
        resultado_auditoria=resultado_auditoria,
        resumo_ia=resumo_ia,
        ia_indisponivel=ia_indisponivel,
        placa_escolhida=placa_escolhida,
        placas_disponiveis=placas_disponiveis,
        tolerancia_m=tolerancia_m,
        file_name_carregamento=file_name_carregamento,
        file_name_rastreio=file_name_rastreio,
    )
