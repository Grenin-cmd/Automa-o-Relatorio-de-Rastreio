import re
from pathlib import Path

import pandas as pd
import pytest

import banco
from mensagem_saidas.leitura import ler_exportacao_ss
from mensagem_saidas.regras import montar_mensagem

FIX = Path(__file__).parent / "fixtures" / "ss"


def _gab(nome):
    blocos = (FIX / nome).read_text(encoding="utf-8").strip().split("\n\n")
    return blocos[0], {b.split(":", 1)[0]: b for b in blocos[1:]}


def _minutos(frase):
    return [int(h) * 60 + int(m) for h, m in re.findall(r"(\d{2}):(\d{2})", frase)]


def _confere(gerada, esperada):
    def norm(s):
        return re.sub(r"\d{2}:\d{2}", "HH:MM", " ".join(s.split()))
    assert norm(gerada) == norm(esperada), (gerada, esperada)
    assert all(abs(a - b) <= 2 for a, b in zip(_minutos(gerada), _minutos(esperada))), (gerada, esperada)


def _res(arquivo, ignorar=frozenset()):
    return montar_mensagem(ler_exportacao_ss(str(FIX / arquivo)), banco.listar_locais(), ignorar)


@pytest.mark.parametrize("arquivo,gabarito", [
    ("historico_completo_2026-11-27.csv", "gabarito_2026-11-27.txt"),
    ("historico_2026-11-26.csv", "gabarito_2026-11-26.txt"),
])
def test_bate_com_gabarito(arquivo, gabarito):
    res = _res(arquivo)
    cab, esperadas = _gab(gabarito)
    blocos = res.texto.split("\n\n")
    assert blocos[0] == cab
    geradas = {b.split(":", 1)[0]: b for b in blocos[1:]}
    assert list(geradas) == sorted(geradas)
    for placa, esperada in esperadas.items():
        _confere(geradas[placa], esperada)


def test_conferir_27_11_vazio():
    res = _res("historico_completo_2026-11-27.csv")
    assert res.conferir == [] and res.aviso_periodo is None


def test_aviso_quando_planilha_comeca_a_meia_noite():
    assert "18:00" in _res("historico_2026-11-26.csv").aviso_periodo


def test_conferir_26_11():
    res = _res("historico_2026-11-26.csv")
    motivos = {(i.placa, i.motivo) for i in res.conferir}
    assert ("PLA-0A02", "local_desconhecido") in motivos
    assert ("PLA-0A06", "local_desconhecido") in motivos
    assert ("PLA-0A03", "em_movimento_no_inicio") in motivos
    assert "Carmópolis" not in res.texto


def test_ignorar_remove_item():
    chave = _res("historico_2026-11-26.csv").conferir[0].chave
    assert chave not in {i.chave for i in _res("historico_2026-11-26.csv", {chave}).conferir}


def test_de_ontem_na_virada_do_ano():
    df = pd.DataFrame({"placa": ["PLA-9Z99"] * 3, "data_hora": pd.to_datetime(["2026-12-31 23:00", "2026-12-31 23:50", "2027-01-01 01:00"]),
                       "velocidade_kmh": [0.0, 40.0, 50.0], "ignicao": [None] * 3, "evento": [""] * 3,
                       "poi_ss": ["CECOTI MATRIZ", None, None], "poi_ss_dist_m": [10, None, None], "endereco": [""] * 3,
                       "cidade": ["Cláudio"] * 3, "uf": ["MG"] * 3, "lat": [None] * 3, "lon": [None] * 3})
    res = montar_mensagem(df, banco.listar_locais())
    assert res.texto.startswith("*Horário de saída das Carretas 01/01/2027*")
    assert "PLA-9Z99: Saída da Matriz as 23:50 de ontem." in res.texto


def test_veiculo_sem_paradas_fica_em_transito():
    df = pd.DataFrame({"placa": ["PLA-9Z98"] * 2, "data_hora": pd.to_datetime(["2026-11-27 01:00", "2026-11-27 01:05"]),
                       "velocidade_kmh": [60.0, 70.0], "ignicao": [None] * 2, "evento": [""] * 2, "poi_ss": [None] * 2,
                       "poi_ss_dist_m": [None] * 2, "endereco": [""] * 2, "cidade": ["X"] * 2, "uf": ["MG"] * 2,
                       "lat": [None] * 2, "lon": [None] * 2})
    res = montar_mensagem(df, banco.listar_locais())
    assert "PLA-9Z98: Em trânsito." in res.texto and res.conferir[0].motivo == "sem_paradas"
