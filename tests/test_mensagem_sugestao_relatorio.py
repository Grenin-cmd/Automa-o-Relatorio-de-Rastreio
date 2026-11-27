import io
import json
from pathlib import Path

import pandas as pd

import banco
from mensagem_saidas import sugestao
from mensagem_saidas.leitura import ler_exportacao_ss
from mensagem_saidas.regras import montar_mensagem
from mensagem_saidas.relatorio import gerar_excel_pontos
from mensagem_saidas.sugestao import sugerir_nome

FIX = Path(__file__).parent / "fixtures" / "ss"

OVERPASS = json.dumps({"elements": [
    {"type": "node", "lat": -23.1003, "lon": -46.6096, "tags": {"name": "Restaurante X"}},
    {"type": "node", "lat": -23.1005, "lon": -46.6097, "tags": {"amenity": "fuel", "name": "Posto Dom Pedro"}},
    {"type": "way", "center": {"lat": -23.1001, "lon": -46.6096}, "tags": {"amenity": "fuel"}},
]}).encode()


def setup_function():
    sugestao._CACHE.clear()


def test_sugere_posto_com_nome_mais_proximo():
    assert sugerir_nome(-23.10011, -46.60962, buscar=lambda q: OVERPASS) == "Posto Dom Pedro"


def test_sem_posto_usa_o_lugar_com_nome_mais_proximo():
    so_restaurante = json.dumps({"elements": [{"type": "node", "lat": -23.1003, "lon": -46.6096, "tags": {"amenity": "restaurant", "name": "Restaurante X"}}]}).encode()
    assert sugerir_nome(-23.10011, -46.60962, buscar=lambda q: so_restaurante) == "Restaurante X"


def test_falha_de_rede_retorna_none():
    def quebra(q):
        raise TimeoutError
    assert sugerir_nome(-1.0, -1.0, buscar=quebra) is None


def test_resultado_fica_em_cache():
    chamadas = []
    def buscar(q):
        chamadas.append(q)
        return OVERPASS
    sugerir_nome(-23.10011, -46.60962, buscar=buscar)
    sugerir_nome(-23.10012, -46.60961, buscar=buscar)
    assert len(chamadas) == 1


def test_excel_tem_colunas_e_link():
    res = montar_mensagem(ler_exportacao_ss(str(FIX / "historico_completo_2026-11-27.csv")), [])
    itens = [i for i in res.conferir if i.motivo == "local_desconhecido"]
    dados = gerar_excel_pontos(res.conferir, {itens[0].chave: "Posto Sugerido"})
    df = pd.read_excel(io.BytesIO(dados))
    assert list(df.columns)[-1] == "Cadastrado na SS" and "Link Google Maps" in df.columns
    assert len(df) == len(itens)
    assert df.iloc[0]["Nome sugerido"] == "Posto Sugerido"
    assert str(df.iloc[0]["Link Google Maps"]).startswith("https://www.google.com/maps/search/?api=1&query=")


def test_excel_so_itens_de_local_desconhecido():
    res = montar_mensagem(ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv")), banco.listar_locais())
    df = pd.read_excel(io.BytesIO(gerar_excel_pontos(res.conferir, {})))
    assert set(df["Placa"]) == {"PLA-0A02", "PLA-0A06"}
