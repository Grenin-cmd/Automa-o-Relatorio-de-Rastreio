from pathlib import Path

import pandas as pd
import pytest

from mensagem_saidas.leitura import FormatoSSDesconhecido, extrair_cidade_uf, ler_exportacao_ss

FIX = Path(__file__).parent / "fixtures" / "ss"


def test_le_formato_historico():
    df = ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv"))
    assert list(df.columns) == ["placa", "data_hora", "velocidade_kmh", "ignicao", "evento", "poi_ss", "poi_ss_dist_m", "endereco", "cidade", "uf", "lat", "lon"]
    assert len(df) == 1765 and df["lat"].isna().all()
    r = df[df.placa == "PLA-0A01"].iloc[0]
    assert r.data_hora == pd.Timestamp("2026-11-26 01:54:13") and r.velocidade_kmh == 0 and r.ignicao is False
    assert (r.poi_ss, r.poi_ss_dist_m, r.cidade, r.uf) == ("CEMIL", 85.0, "Patos de Minas", "MG")


def test_le_formato_historico_completo():
    df = ler_exportacao_ss(str(FIX / "historico_completo_2026-11-27.csv"))
    assert len(df) == 1871 and df["lat"].notna().all()
    r = df[df.placa == "PLA-0A06"].iloc[0]
    assert r.poi_ss is None
    assert (round(r.lat, 5), round(r.lon, 5)) == (-23.10011, -46.60962)
    assert (r.cidade, r.uf) == ("Atibaia", "SP") and r.ignicao is None


def test_aceita_utf8_com_bom(tmp_path):
    origem = (FIX / "historico_2026-11-26.csv").read_bytes().decode("cp1252")
    f = tmp_path / "x.csv"
    f.write_bytes(origem.encode("utf-8-sig"))
    esperado = ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv")).iloc[0]
    obtido = ler_exportacao_ss(str(f)).iloc[0]
    assert (obtido.cidade, obtido.endereco) == (esperado.cidade, esperado.endereco)


def test_aceita_bytes():
    dados = (FIX / "historico_2026-11-26.csv").read_bytes()
    assert len(ler_exportacao_ss(dados)) == 1765


def test_formato_desconhecido(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a;b\n1;2\n", encoding="cp1252")
    with pytest.raises(FormatoSSDesconhecido, match="a"):
        ler_exportacao_ss(str(f))


def test_extrair_cidade_uf():
    assert extrair_cidade_uf("Rodovia Dom Pedro I, Jardim Colonial - Atibaia - São Paulo - Brasil") == ("Atibaia", "SP")
    assert extrair_cidade_uf("Riacho de areia - Minas Gerais - Brasil") == ("Riacho de areia", "MG")
    assert extrair_cidade_uf("") == ("", "")
