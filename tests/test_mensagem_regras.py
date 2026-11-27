import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from mensagem_saidas import unidades
from mensagem_saidas.leitura import ler_exportacao_ss
from mensagem_saidas.regras import montar_mensagem, montar_texto

FIX = Path(__file__).parent / "fixtures" / "ss"


def _gab(nome):
    blocos = (FIX / nome).read_text(encoding="utf-8").strip().split("\n\n")
    return blocos[0], {b.split(":", 1)[0]: b.split(":", 1)[1].strip() for b in blocos[1:]}


def _confere(gerada, esperada):
    def norm(s):
        return re.sub(r"\d{2}:\d{2}", "HH:MM", " ".join(s.split()))
    def mins(s):
        return [int(h) * 60 + int(m) for h, m in re.findall(r"(\d{2}):(\d{2})", s)]
    assert norm(gerada) == norm(esperada), (gerada, esperada)
    assert all(abs(a - b) <= 2 for a, b in zip(mins(gerada), mins(esperada))), (gerada, esperada)


def _res(arquivo):
    return montar_mensagem(ler_exportacao_ss(str(FIX / arquivo)), unidades.LOCAIS)


@pytest.mark.parametrize("arquivo,gabarito", [
    ("historico_completo_2026-11-27.csv", "gabarito_2026-11-27.txt"),
    ("historico_2026-11-26.csv", "gabarito_2026-11-26.txt"),
])
def test_bate_com_gabarito(arquivo, gabarito):
    res = _res(arquivo)
    cab, esperadas = _gab(gabarito)
    assert res.texto.split("\n\n")[0] == cab
    assert list(res.linhas) == sorted(res.linhas)
    for placa, esperada in esperadas.items():
        _confere(res.linhas[placa], esperada)


def test_situacoes_e_totais_27_11():
    res = _res("historico_completo_2026-11-27.csv")
    assert res.situacoes["PLA-0A01"] == "Saiu 05:41"
    assert res.situacoes["PLA-0A04"] == "Parado"
    assert res.situacoes["PLA-0A02"] == "No CD 06:41"
    assert res.situacoes["PLA-0A08"] == "Na Matriz 03:29"
    assert res.totais == {"veiculos": 8, "sairam": 6, "parados": 2, "sem_poi": 0}
    assert res.aviso_periodo is None


def test_pontos_sem_poi_26_11():
    res = _res("historico_2026-11-26.csv")
    assert {p.placa for p in res.pontos_sem_poi} == {"PLA-0A02", "PLA-0A06"}
    assert "21:00" in res.aviso_periodo


def _df(horarios, velocidades, pois):
    n = len(horarios)
    return pd.DataFrame({"placa": ["PLA-9Z99"] * n, "data_hora": pd.to_datetime(horarios), "velocidade_kmh": [float(v) for v in velocidades],
                         "ignicao": [None] * n, "evento": [""] * n, "poi_ss": pois, "poi_ss_dist_m": [10 if p else None for p in pois],
                         "endereco": [""] * n, "cidade": ["Cláudio"] * n, "uf": ["MG"] * n, "lat": [None] * n, "lon": [None] * n})


def test_recorte_as_21h_do_dia_anterior():
    df = _df(["2026-11-26 20:30", "2026-11-26 20:59", "2026-11-26 21:00", "2026-11-26 21:30", "2026-11-27 05:00"],
             [0, 50, 0, 40, 60], ["CEMIL", None, "CECOTI MATRIZ", None, None])
    res = montar_mensagem(df, unidades.LOCAIS)
    assert res.linhas["PLA-9Z99"] == "Saída da Matriz as 21:30 de ontem."


def test_montar_texto_com_edicao():
    texto = montar_texto(date(2026, 11, 27), {"AAA-1A11": "Saída da Matriz as 05:00.", "BBB-2B22": "Está na Matriz."},
                         {"BBB-2B22": "Está na Matriz (manutenção)."})
    assert texto == ("*Horário de saída das Carretas 27/11/2026*\n\nAAA-1A11: Saída da Matriz as 05:00.\n\n"
                     "BBB-2B22: Está na Matriz (manutenção).")


def test_veiculo_sem_paradas_fica_em_transito():
    res = montar_mensagem(_df(["2026-11-27 01:00", "2026-11-27 01:05"], [60, 70], [None, None]), unidades.LOCAIS)
    assert res.linhas["PLA-9Z99"] == "Em trânsito." and res.situacoes["PLA-9Z99"] == "Em trânsito"
