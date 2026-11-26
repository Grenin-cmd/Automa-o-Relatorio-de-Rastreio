"""Análise de rastreamento (página inicial), exportação Word e upload pelo leitor universal."""
from __future__ import annotations

import os
import tempfile
from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

from adaptador_compatibilidade import AdaptadorParaRastreamento
from analisador_rastreio import RastreamentoAnalyzer
from leitor_universal import ler_rastreamento

bp = Blueprint("analise", __name__)
from analise import DOCX_DISPONIVEL, find_suspicious_stops, gerar_resumo_geral_placas, gerar_timeline_viagem, gerar_word_bytes, obter_posicoes_placas, parse_poi_dataframe
from arquivos import carregar_arquivo, salvar_upload
from banco import get_regras_ativas, get_saved_pois, save_saved_pois
from rotas.comum import agente_ia, cleanup_cached_file, login_required
from utils import ler_pois, normalize_column_name, resolver_coluna


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    report = None
    pois_text = (
        "ClienteA:cliente:-23.5505:-46.6333:300:120:10\n"
        "PostoX:posto:-23.5600:-46.6400:250:120:10"
    )
    placa_escolhida = request.form.get("placa", "")
    try:
        raio_suspeita = float(request.form.get("raio_suspeita", 200) or 200)
    except (TypeError, ValueError):
        raio_suspeita = 200.0

    action = request.form.get("action", "analyze")
    placas: list[str] = []
    resumo_geral = None
    posicoes_placas: dict[str, tuple[float, float]] = {}
    paradas_suspeitas: list[dict[str, object]] = []
    timeline_eventos: list[dict[str, object]] = []
    docx_available = DOCX_DISPONIVEL
    uploaded_file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name", "")
    saved_pois = get_saved_pois()
    nomes_pois_registrados = {normalize_column_name(str(p["nome"])) for p in saved_pois if p.get("nome")}

    if uploaded_file_path and not os.path.exists(uploaded_file_path):
        cleanup_cached_file()
        uploaded_file_path = None
        file_name = ""

    # GET RÁPIDO
    if request.method == "GET" and uploaded_file_path and os.path.exists(uploaded_file_path):
        try:
            df_full = carregar_arquivo(uploaded_file_path)
            placa_col = resolver_coluna(df_full, ["Placa", "placa", "plate"])
            placas = sorted(df_full[placa_col].dropna().astype(str).unique().tolist())
            if not placa_escolhida and placas:
                placa_escolhida = placas[0]
        except Exception:
            cleanup_cached_file()
            uploaded_file_path = None
            file_name = ""

    # POST OTIMIZADO (CARREGAMENTO ÚNICO DO ARQUIVO)
    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        arquivo_pois = request.files.get("arquivo_pois")
        pois_text = request.form.get("pois", "")

        action = request.form.get("action") or request.form.get("submit") or ""

        if action == "import_pois" or "import_pois" in request.form or (arquivo_pois and arquivo_pois.filename):
            if not arquivo_pois or not arquivo_pois.filename:
                flash("Selecione um arquivo CSV ou Excel de POIs para importar.", "warning")
            else:
                try:
                    df_pois = carregar_arquivo(arquivo_pois)
                    imported_pois = parse_poi_dataframe(df_pois)
                    save_saved_pois(imported_pois)
                    flash(f"{len(imported_pois)} POI(s) importado(s) com sucesso.", "success")
                except Exception as error:
                    flash(f"Erro ao processar POIs: {error}", "danger")
            return redirect(url_for("configuracoes.configuracoes"))

        if arquivo and arquivo.filename:
            try:
                new_path = salvar_upload(arquivo)
                if uploaded_file_path and uploaded_file_path != new_path and os.path.exists(uploaded_file_path):
                    try:
                        os.unlink(uploaded_file_path)
                    except OSError:
                        pass
                uploaded_file_path = new_path
                session["uploaded_file_path"] = new_path
                session["uploaded_file_name"] = arquivo.filename
                file_name = arquivo.filename
            except Exception as error:
                flash(str(error), "danger")

        if not uploaded_file_path or not os.path.exists(uploaded_file_path):
            flash("Selecione um arquivo CSV ou Excel para continuar.", "warning")
            return render_template(
                "index.html",
                report=report,
                placa_escolhida=placa_escolhida,
                raio_suspeita=raio_suspeita,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                placas=placas,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
            )

        # 1. Carrega o arquivo UMA ÚNICA VEZ em memória
        try:
            df_full = carregar_arquivo(uploaded_file_path)
            placa_col = resolver_coluna(df_full, ["Placa", "placa", "plate"])
            placas = sorted(df_full[placa_col].dropna().astype(str).unique().tolist())
            if not placa_escolhida and placas:
                placa_escolhida = placas[0]
        except Exception as error:
            flash(str(error), "danger")
            return render_template(
                "index.html",
                report=report,
                placa_escolhida=placa_escolhida,
                raio_suspeita=raio_suspeita,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                placas=placas,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
            )

        df_placa = df_full[df_full[placa_col].astype(str) == placa_escolhida] if placa_escolhida else df_full

        # 2. Processa os POIs
        pois = ler_pois(pois_text) + [{k: v for k, v in p.items() if k != "id"} for p in saved_pois]
        pois_ajustados = []
        for p in pois:
            p_copia = dict(p)
            val_raio = p_copia.get("raio_metros")
            try:
                raio_orig = float(str(val_raio).replace(",", ".")) if val_raio is not None else 200.0
            except (ValueError, TypeError):
                raio_orig = 200.0
            p_copia["raio_metros"] = max(raio_orig, float(raio_suspeita))
            pois_ajustados.append(p_copia)

        analyzer = RastreamentoAnalyzer(pois=pois_ajustados, raio_tolerancia_m=raio_suspeita)
        limite_velocidade_kmh = 110.0
        regras_ativas = get_regras_ativas()

        # 3. Executa a Ação Solicitada
        try:
            if action == "summary":
                refinar = (lambda texto: agente_ia.refinar_relatorio(texto, regras_ativas)) if agente_ia else None
                resumo_geral = gerar_resumo_geral_placas(
                    df_full, pois_ajustados, raio_tolerancia_m=raio_suspeita, refinar=refinar
                )
                posicoes_placas = obter_posicoes_placas(df_full)
                session["word_summary"] = resumo_geral
            elif action == "timeline":
                timeline_eventos = gerar_timeline_viagem(df_full, placa_escolhida, pois_ajustados, limite_velocidade_kmh, raio_suspeita)
            else:
                relatorio_bruto = analyzer.gerar_relatorio(df_placa)
                report = agente_ia.refinar_relatorio(relatorio_bruto, regras_ativas) if agente_ia else relatorio_bruto

            paradas_suspeitas = find_suspicious_stops(df_placa, raio_suspeita, nomes_pois_registrados, pois_ajustados)
        except Exception as error:
            flash(str(error), "danger")

        return render_template(
            "index.html",
            report=report,
            placa_escolhida=placa_escolhida,
            raio_suspeita=raio_suspeita,
            paradas_suspeitas=paradas_suspeitas,
            timeline_eventos=timeline_eventos,
            placas=placas,
            file_name=file_name,
            resumo_geral=resumo_geral,
            posicoes_placas=posicoes_placas,
            docx_available=docx_available,
        )

    return render_template(
        "index.html",
        report=report,
        placa_escolhida=placa_escolhida,
        raio_suspeita=raio_suspeita,
        paradas_suspeitas=paradas_suspeitas,
        timeline_eventos=timeline_eventos,
        placas=placas,
        file_name=file_name,
        resumo_geral=resumo_geral,
        posicoes_placas=posicoes_placas,
        docx_available=docx_available,
    )


@bp.route("/download_word")
@login_required
def download_word():
    resumo = session.get("word_summary")
    if not resumo:
        flash("Gere o resumo geral primeiro para poder baixar o Word.", "warning")
        return redirect("/")

    try:
        doc_bytes = gerar_word_bytes(resumo)
    except RuntimeError as error:
        flash(str(error), "danger")
        return redirect("/")

    return send_file(
        BytesIO(doc_bytes),
        as_attachment=True,
        download_name="resumo_geral_frotas.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@bp.route("/upload_rastreamento", methods=["POST"])
@login_required
def upload_rastreamento():
    """
    Rota para upload de arquivos de rastreamento de qualquer fonte.
    Compatível com SS Telemática, Vivo, TIM, etc.
    """
    arquivo = request.files.get("arquivo")
    nome_fonte = request.form.get("nome_fonte", "GENERICA")

    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo", "warning")
        return redirect("/")

    caminho_temp: str | None = None
    try:
        caminho_temp = salvar_upload(arquivo)
        eventos, stats = ler_rastreamento(caminho_temp, nome_fonte)
        df = AdaptadorParaRastreamento.eventos_para_dataframe(eventos)

        # O DataFrame vai para um CSV temporário no servidor; a sessão (que é
        # um cookie limitado a ~4 KB) guarda apenas o caminho. Assim o arquivo
        # convertido segue o mesmo fluxo de análise de um upload comum.
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        tmp.close()
        df.to_csv(tmp.name, index=False)
        cleanup_cached_file()
        session["uploaded_file_path"] = tmp.name
        session["uploaded_file_name"] = f"{arquivo.filename} ({nome_fonte})"
        session["stats_rastreamento"] = {
            k: v for k, v in stats.items() if isinstance(v, (int, float, str, bool))
        }

        flash(f"✅ {stats.get('eventos_validos', len(df))} eventos válidos de {nome_fonte}", "success")
    except Exception as e:
        flash(f"❌ Erro: {str(e)}", "danger")
    finally:
        if caminho_temp and os.path.exists(caminho_temp):
            os.unlink(caminho_temp)

    return redirect("/")
