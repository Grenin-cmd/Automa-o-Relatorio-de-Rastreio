"""Testes das correções da revisão final."""
from pathlib import Path

import pandas as pd
import pytest

from mensagem_saidas import unidades
from mensagem_saidas.leitura import FormatoSSDesconhecido, ler_exportacao_ss
from mensagem_saidas.paradas import detectar_paradas

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


# Important 2 -------------------------------------------------------------
def test_semaforo_depois_da_saida_nao_atrasa_horario():
    df = _df([("05:30", 0, "CECOTI MATRIZ", 10, None, None), ("05:42", 0, "CECOTI MATRIZ", 12, None, None),
              ("05:43", 30, "CECOTI MATRIZ", 300, None, None), ("05:47", 0, "CECOTI MATRIZ", 800, None, None),
              ("05:48", 0, "CECOTI MATRIZ", 800, None, None), ("05:49", 40, "CECOTI MATRIZ", 1200, None, None)])
    p = detectar_paradas(df, unidades.LOCAIS)[0]
    assert p.local.nome_exibicao == "Matriz" and f"{p.saida:%H:%M}" == "05:43"


def test_parada_no_portao_continua_unificada():  # 187 m do CD de Contagem (raio 150): ainda é o mesmo local
    df = _df([("00:00", 0, "CECOTI CD CONTAGEM", 28, None, None), ("00:54", 4, "CECOTI CD CONTAGEM", 26, None, None),
              ("00:57", 0, "CECOTI CD CONTAGEM", 187, None, None), ("01:00", 0, "CECOTI CD CONTAGEM", 187, None, None),
              ("01:01", 40, "CECOTI CD CONTAGEM", 600, None, None)])
    p = detectar_paradas(df, unidades.LOCAIS)[0]
    assert f"{p.saida:%H:%M}" == "01:01"
