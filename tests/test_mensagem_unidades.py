from mensagem_saidas.locais import resolver_local
from mensagem_saidas.unidades import LOCAIS, formatar_nome_ss, local_da_ss, tipo_por_nome


def test_formatar_nome_ss():
    assert formatar_nome_ss("POSTO JALÉ BR-262 EM ARAÚJOS") == "Posto Jalé BR-262 em Araújos"
    assert formatar_nome_ss("P.S. AERODROMO MG 260 CLAUDIO") == "P.S. Aerodromo MG 260 Claudio"
    assert formatar_nome_ss("CD Mart Minas Contagem") == "CD Mart Minas Contagem"
    assert formatar_nome_ss("PADARIA DA PRAÇA") == "Padaria da Praça"


def test_tipo_por_nome():
    assert tipo_por_nome("AUTO POSTO X") == "POSTO"
    assert tipo_por_nome("P.S. AERODROMO MG 260") == "POSTO"
    assert tipo_por_nome("CHURRASCARIA BOI") == "RESTAURANTE"
    assert tipo_por_nome("CD CARREFOR") == "CD"
    assert tipo_por_nome("CECOTI MATRIZ") == "MATRIZ"
    assert tipo_por_nome("PAES E CIA MIL") == "OUTRO"


def test_lista_fixa_tem_os_locais_do_gabarito():
    nomes = {l.nome_exibicao for l in LOCAIS}
    assert {"Matriz", "CD de Contagem", "Fontini em São Francisco de Paula MG", "Posto Dom Pedro na SP-065 em Atibaia SP"} <= nomes


def test_poi_da_ss_fora_da_lista_vira_local_com_nome_formatado():
    l = resolver_local(None, None, "POSTO JALÉ BR-262 EM ARAÚJOS", 59, LOCAIS)
    assert (l.nome_exibicao, l.tipo, l.art_de) == ("Posto Jalé BR-262 em Araújos", "POSTO", "do")
    assert l.id == local_da_ss("posto jalé br-262 em araújos").id


def test_poi_da_ss_longe_nao_vira_local():
    assert resolver_local(None, None, "POSTO JALÉ BR-262 EM ARAÚJOS", 251, LOCAIS) is None


def test_lista_fixa_tem_prioridade_sobre_nome_da_ss():
    assert resolver_local(None, None, "CECOTI MATRIZ", 20, LOCAIS).nome_exibicao == "Matriz"


def test_siglas_entre_parenteses_e_barra():
    assert formatar_nome_ss("POSTO TREVÃO (MG)") == "Posto Trevão (MG)"
    assert formatar_nome_ss("POSTO SANTA LUZIA/MG") == "Posto Santa Luzia/MG"
    assert formatar_nome_ss("P.S. GRAAL PE") == "P.S. Graal PE"
    assert formatar_nome_ss("POSTO ALE TO") == "Posto Ale TO"
