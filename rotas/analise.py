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
from mensagem_saidas import unidades
from mensagem_saidas.leitura import ler_exportacao_ss
from mensagem_saidas.regras import montar_mensagem, montar_texto
from arquivos import carregar_arquivo, salvar_upload
from banco import get_regras_ativas, get_saved_pois, save_saved_pois
from rotas.comum import agente_ia, cleanup_cached_file, login_required
from utils import resolver_coluna


ABAS = ("mensagem", "resumo", "relatorio", "linha", "paradas")
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def arquivo_atual() -> str | None:
    caminho = session.get("uploaded_file_path")
    return caminho if caminho and os.path.exists(caminho) else None


def resultado_mensagem(caminho: str | None):
    """Mensagem do dia da planilha atual, ou None se não for uma exportação da SS."""
    if not caminho:
        return None
    try:
        return montar_mensagem(ler_exportacao_ss(caminho), unidades.LOCAIS)
    except Exception:
        return None


def texto_mensagem(resultado) -> str:
    return montar_texto(resultado.data_mensagem, resultado.linhas, session.get("mensagem_edicoes", {}))


def _pois_ajustados(raio: float) -> list[dict]:
    ajustados = []
    for p in get_saved_pois():
        copia = {k: v for k, v in p.items() if k != "id"}
        try:
            raio_orig = float(str(copia.get("raio_metros")).replace(",", ".")) if copia.get("raio_metros") is not None else 200.0
        except (ValueError, TypeError):
            raio_orig = 200.0
        copia["raio_metros"] = max(raio_orig, raio)
        ajustados.append(copia)
    return ajustados


def _data_extenso(d) -> str:
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        arquivo_pois = request.files.get("arquivo_pois")
        if request.form.get("action") == "import_pois" or (arquivo_pois and arquivo_pois.filename):
            if not arquivo_pois or not arquivo_pois.filename:
                flash("Selecione um arquivo CSV ou Excel de POIs para importar.", "warning")
            else:
                try:
                    importados = parse_poi_dataframe(carregar_arquivo(arquivo_pois))
                    save_saved_pois(importados)
                    flash(f"{len(importados)} POI(s) importado(s) com sucesso.", "success")
                except Exception as erro:
                    flash(f"Erro ao processar POIs: {erro}", "danger")
            return redirect(url_for("configuracoes.pois"))

        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Selecione a planilha de rastreamento (CSV ou Excel).", "warning")
            return redirect(url_for("analise.index"))
        try:
            novo = salvar_upload(arquivo)
        except Exception as erro:
            flash(str(erro), "danger")
            return redirect(url_for("analise.index"))
        cleanup_cached_file()
        session["uploaded_file_path"] = novo
        session["uploaded_file_name"] = arquivo.filename
        session["mensagem_edicoes"] = {}
        session["mensagem_sugestoes"] = {}
        aba = "mensagem" if resultado_mensagem(novo) else "relatorio"
        return redirect(f"/?aba={aba}")

    caminho = arquivo_atual()
    contexto = {"arquivo_nome": session.get("uploaded_file_name", ""), "tem_arquivo": bool(caminho), "docx_available": DOCX_DISPONIVEL}
    if not caminho:
        return render_template("analise.html", **contexto, aba=None, resultado=None, placas=[])

    resultado = resultado_mensagem(caminho)
    aba = request.args.get("aba") or ("mensagem" if resultado else "relatorio")
    if aba not in ABAS or (aba == "mensagem" and not resultado) or (aba == "resumo" and resultado):
        aba = "relatorio"
    try:
        raio = float(request.args.get("raio", 200) or 200)
    except ValueError:
        raio = 200.0

    try:
        df_full = carregar_arquivo(caminho)
        placa_col = resolver_coluna(df_full, ["Placa", "placa", "plate"])
        placas = sorted(df_full[placa_col].dropna().astype(str).unique().tolist())
    except Exception as erro:
        flash(f"Não foi possível ler a planilha: {erro}", "danger")
        cleanup_cached_file()
        return redirect(url_for("analise.index"))

    placa = request.args.get("placa") or (placas[0] if placas else "")
    contexto.update(aba=aba, resultado=resultado, placas=placas, placa_escolhida=placa, raio=raio)
    if resultado and resultado.data_mensagem:
        contexto["data_extenso"] = _data_extenso(resultado.data_mensagem)

    try:
        if aba == "mensagem":
            edicoes = session.get("mensagem_edicoes", {})
            contexto.update(edicoes=edicoes, texto_completo=texto_mensagem(resultado),
                            posicoes=obter_posicoes_placas(df_full))
        elif aba == "resumo":
            # Planilhas que não são da SS: o resumo geral antigo (com IA, mapa e Word) continua disponível.
            regras = get_regras_ativas()
            refinar = (lambda texto: agente_ia.refinar_relatorio(texto, regras)) if agente_ia else None
            resumo = gerar_resumo_geral_placas(df_full, _pois_ajustados(raio), raio_tolerancia_m=raio, refinar=refinar)
            session["word_summary"] = resumo
            contexto.update(resumo_linhas=[l for l in resumo.split("\n\n") if l.strip()], posicoes=obter_posicoes_placas(df_full))
        elif aba == "relatorio" and placa:
            df_placa = df_full[df_full[placa_col].astype(str) == placa]
            bruto = RastreamentoAnalyzer(pois=_pois_ajustados(raio), raio_tolerancia_m=raio).gerar_relatorio(df_placa)
            contexto["relatorio"] = agente_ia.refinar_relatorio(bruto, get_regras_ativas()) if agente_ia else bruto
        elif aba == "linha" and placa:
            contexto["eventos"] = gerar_timeline_viagem(df_full, placa, _pois_ajustados(raio), 110.0, raio)
        elif aba == "paradas":
            contexto["paradas"] = find_suspicious_stops(df_full, raio, None, _pois_ajustados(raio))
    except Exception as erro:
        flash(f"Erro ao gerar a análise: {erro}", "danger")

    return render_template("analise.html", **contexto)


@bp.route("/download_word")
@login_required
def download_word():
    resultado = resultado_mensagem(arquivo_atual())
    if resultado is not None and resultado.data_mensagem:
        texto, nome = texto_mensagem(resultado), f"mensagem_saidas_{resultado.data_mensagem:%d-%m-%Y}.docx"
    elif session.get("word_summary") and arquivo_atual():
        texto, nome = session["word_summary"], "resumo_geral_frotas.docx"
    else:
        flash("Envie a planilha e abra a Mensagem do dia (ou o Resumo geral) para gerar o Word.", "warning")
        return redirect("/")
    try:
        doc_bytes = gerar_word_bytes(texto)
    except RuntimeError as error:
        flash(str(error), "danger")
        return redirect("/")
    return send_file(
        BytesIO(doc_bytes),
        as_attachment=True,
        download_name=nome,
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
