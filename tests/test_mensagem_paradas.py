from pathlib import Path

import banco
from mensagem_saidas.leitura import ler_exportacao_ss
from mensagem_saidas.paradas import detectar_paradas, veio_em_movimento

FIX = Path(__file__).parent / "fixtures" / "ss"
_CACHE = {}


def _df(arquivo):
    if arquivo not in _CACHE:
        _CACHE[arquivo] = ler_exportacao_ss(str(FIX / arquivo))
    return _CACHE[arquivo]


def _paradas(arquivo, placa):
    df = _df(arquivo)
    return detectar_paradas(df[df.placa == placa], banco.listar_locais())


def hm(dt):
    return dt.strftime("%H:%M")


def test_manobras_na_matriz_viram_uma_parada():
    p = _paradas("historico_completo_2026-11-27.csv", "PLA-0A02")[0]
    assert p.local.nome_exibicao == "Matriz" and hm(p.saida) == "22:56"


def test_noite_fora_do_cd_unifica_com_cd_e_usa_o_cd():
    p = _paradas("historico_completo_2026-11-27.csv", "PLA-0A05")[0]
    assert p.local.nome_exibicao == "CD Supermercado BH em Contagem MG" and hm(p.saida) == "05:51" and p.em_andamento_no_inicio


def test_sem_coordenadas_nao_unifica_pois_diferentes():
    ps = _paradas("historico_2026-11-26.csv", "PLA-0A03")
    assert ps[0].local.nome_exibicao.startswith("Posto Caxuxa") and hm(ps[0].saida) == "03:03"


def test_cd_mart_minas_a_208_m_e_reconhecido_e_em_andamento():
    p = _paradas("historico_completo_2026-11-27.csv", "PLA-0A04")[-1]
    assert p.local.nome_exibicao == "CD Supermercados BH em Contagem MG" and p.em_andamento


def test_chegada_recente_em_cd_conta():
    p = _paradas("historico_completo_2026-11-27.csv", "PLA-0A02")[-1]
    assert p.local.nome_exibicao == "CD de Uberlândia" and hm(p.chegada) == "06:41" and p.em_andamento


def test_parada_fora_do_raio_do_cd_contagem_nao_e_chegada():
    ps = [p for p in _paradas("historico_2026-11-26.csv", "PLA-0A05") if p.local and p.local.nome_exibicao == "CD de Contagem"]
    assert hm(ps[0].chegada) == "01:07"


def test_registros_esparsos_com_ignicao_desligada():
    ps = _paradas("historico_2026-11-26.csv", "PLA-0A01")
    assert len(ps) == 1 and ps[0].em_andamento and ps[0].local.nome_exibicao.startswith("Cemil")


def test_duracao_vai_da_chegada_a_saida():
    p = [p for p in _paradas("historico_completo_2026-11-27.csv", "PLA-0A03") if p.local and "Ponto do Peixe" in p.local.nome_exibicao][0]
    assert (hm(p.chegada), hm(p.saida)) == ("05:28", "06:01") and 30 <= p.duracao_min < 33


def test_veio_em_movimento():
    df = _df("historico_2026-11-26.csv")
    assert veio_em_movimento(df[df.placa == "PLA-0A03"]) and not veio_em_movimento(df[df.placa == "PLA-0A01"])
