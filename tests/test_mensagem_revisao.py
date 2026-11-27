"""Testes das correções da revisão final."""
import io
import uuid
from pathlib import Path

import pandas as pd
import pytest

import app
import banco
from mensagem_saidas.leitura import FormatoSSDesconhecido, ler_exportacao_ss
from mensagem_saidas.paradas import detectar_paradas
from mensagem_saidas.regras import montar_mensagem
from mensagem_saidas.relatorio import gerar_excel_pontos
from tests.test_mensagem_rotas import _post, client_logado  # noqa: F401

FIX = Path(__file__).parent / "fixtures" / "ss"


def _df(linhas):
    """linhas: (hora 'HH:MM', velocidade, poi_ss, dist, lat, lon)"""
    return pd.DataFrame({
        "placa": "PLA-9Z97", "data_hora": pd.to_datetime([f"2026-11-27 {h}" for h, *_ in linhas]),
        "velocidade_kmh": [float(v) for _, v, *_ in linhas], "ignicao": None, "evento": "",
        "poi_ss": [p for _, _, p, *_ in linhas], "poi_ss_dist_m": [d for *_, d, _, _ in linhas], "endereco": "",
        "cidade": "Cláudio", "uf": "MG", "lat": [la for *_, la, _ in linhas], "lon": [lo for *_, lo in linhas],
    })


# Important 1 -------------------------------------------------------------
@pytest.mark.parametrize("conteudo", ["", "Placa;Data;Hora;Distância;POI\nX;27/11/26 01:00:00;01:00:00;10;Y\n"])
def test_planilha_vazia_ou_sem_velocidade_e_formato_desconhecido(tmp_path, conteudo):
    f = tmp_path / "x.csv"
    f.write_text(conteudo, encoding="cp1252")
    with pytest.raises(FormatoSSDesconhecido):
        ler_exportacao_ss(str(f))


def test_planilha_ruim_nao_trava_a_pagina(client_logado, tmp_path):  # noqa: F811
    f = tmp_path / "vazio.csv"
    f.write_text("", encoding="cp1252")
    _post(client_logado, "/mensagem_saidas", arquivo=f)
    assert client_logado.get("/mensagem_saidas").status_code == 200


# Important 2 -------------------------------------------------------------
def test_semaforo_depois_da_saida_nao_atrasa_horario():
    df = _df([("05:30", 0, "CECOTI MATRIZ", 10, None, None), ("05:42", 0, "CECOTI MATRIZ", 12, None, None),
              ("05:43", 30, "CECOTI MATRIZ", 300, None, None), ("05:47", 0, "CECOTI MATRIZ", 800, None, None),
              ("05:48", 0, "CECOTI MATRIZ", 800, None, None), ("05:49", 40, "CECOTI MATRIZ", 1200, None, None)])
    p = detectar_paradas(df, banco.listar_locais())[0]
    assert p.local.nome_exibicao == "Matriz" and f"{p.saida:%H:%M}" == "05:43"


def test_parada_no_portao_continua_unificada():  # 187 m do CD de Contagem (raio 150): ainda é o mesmo local
    df = _df([("00:00", 0, "CECOTI CD CONTAGEM", 28, None, None), ("00:54", 4, "CECOTI CD CONTAGEM", 26, None, None),
              ("00:57", 0, "CECOTI CD CONTAGEM", 187, None, None), ("01:00", 0, "CECOTI CD CONTAGEM", 187, None, None),
              ("01:01", 40, "CECOTI CD CONTAGEM", 600, None, None)])
    p = detectar_paradas(df, banco.listar_locais())[0]
    assert f"{p.saida:%H:%M}" == "01:01"


# Important 3 -------------------------------------------------------------
def test_cadastrar_nao_preenche_alias_com_poi_da_ss():
    from datetime import datetime
    from flask import render_template
    from mensagem_saidas.paradas import Parada
    from mensagem_saidas.regras import ItemConferir, ResultadoMensagem
    parada = Parada("PLA-1", datetime(2026, 11, 27, 1), datetime(2026, 11, 27, 3), datetime(2026, 11, 27, 1), None, None,
                    "Contagem", "MG", "Rua X - Contagem - Minas Gerais - Brasil", -19.9, -44.0, "CD CARREFOR", 200, False)
    res = ResultadoMensagem("*x*", [ItemConferir("PLA-1", "local_desconhecido", parada, "k")], None, None)
    with app.app.test_request_context("/mensagem_saidas"):
        html = render_template("mensagem_saidas.html", resultado=res, sugestoes={}, arquivo_nome="", tipos=("POSTO",),
                               usuario_atual={"nome": "t"})
    assert 'name="aliases_ss" value=""' in html and "CD CARREFOR" in html


# Important 4 -------------------------------------------------------------
def test_nome_com_aspas_nao_quebra_confirmacao(client_logado):  # noqa: F811
    nome = f"x{uuid.uuid4().hex[:4]}');alert(1);('"
    banco.salvar_local({"nome_exibicao": nome, "genero": "o", "tipo": "POSTO", "aliases_ss": [], "raio_m": 250})
    html = client_logado.get("/locais_importantes").get_data(as_text=True)
    assert "confirm('Excluir ' + this.dataset.nome" in html
    assert "alert(1);(" not in html.split("onsubmit=")[1].split(">")[0]


# Important 5 -------------------------------------------------------------
def test_excel_inclui_locais_ainda_nao_cadastrados_na_ss():
    lid = banco.salvar_local({"nome_exibicao": "Posto Aceito em Z MG", "genero": "o", "tipo": "POSTO", "aliases_ss": [],
                              "latitude": -20.5, "longitude": -44.5, "raio_m": 250})
    pendentes = [l for l in banco.listar_locais() if not l.cadastrado_na_ss]
    df = pd.read_excel(io.BytesIO(gerar_excel_pontos([], {}, pendentes)))
    linha = df[df["Nome sugerido"] == "Posto Aceito em Z MG"].iloc[0]
    assert linha["Tipo"] == "POSTO" and str(linha["Link Google Maps"]).endswith("-20.5,-44.5")
    banco.excluir_local(lid)


# Re-graded minor 3 -------------------------------------------------------
def test_saida_de_dois_dias_atras_mostra_a_data():
    df = _df([("05:00", 0, "CECOTI MATRIZ", 10, None, None)])
    df.loc[len(df)] = df.iloc[0]
    df["data_hora"] = pd.to_datetime(["2026-11-25 05:00", "2026-11-25 05:10"])
    df.loc[1, "velocidade_kmh"] = 40.0
    extra = df.iloc[[1]].copy()
    extra["data_hora"] = pd.Timestamp("2026-11-27 06:00")
    res = montar_mensagem(pd.concat([df, extra], ignore_index=True), banco.listar_locais())
    assert "Saída da Matriz as 05:10 de 25/11." in res.texto
