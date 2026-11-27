import banco
from mensagem_saidas.locais import Local, resolver_local


def _l(**kw):
    base = dict(id="x", nome_exibicao="Matriz", genero="a", tipo="MATRIZ", aliases_ss=("CECOTI MATRIZ",),
                latitude=None, longitude=None, raio_m=250, cadastrado_na_ss=False)
    return Local(**{**base, **kw})


def test_artigos():
    assert (_l().art_de, _l().art_em) == ("da", "na")
    assert (_l(genero="o").art_de, _l(genero="o").art_em) == ("do", "no")


def test_resolve_por_coordenada_antes_do_alias():
    dom = _l(id="d", nome_exibicao="Posto Dom Pedro na SP-065 em Atibaia SP", genero="o", tipo="POSTO", aliases_ss=(),
             latitude=-23.10011, longitude=-46.60962, raio_m=300)
    assert resolver_local(-23.1010, -46.6096, None, None, [_l(), dom]) is dom


def test_resolve_por_alias_dentro_do_raio_ignorando_caixa_e_acento():
    assert resolver_local(None, None, "cecoti matríz", 120, [_l()]).nome_exibicao == "Matriz"


def test_alias_fora_do_raio_nao_casa():
    assert resolver_local(None, None, "CECOTI MATRIZ", 251, [_l()]) is None


def test_alias_sem_distancia_nao_casa():
    assert resolver_local(None, None, "CECOTI MATRIZ", None, [_l()]) is None


def test_carga_inicial_tem_os_11_locais_do_gabarito():
    nomes = {l.nome_exibicao for l in banco.listar_locais()}
    assert {"Matriz", "CD de Contagem", "CD Supermercados BH em Contagem MG", "Posto Dom Pedro na SP-065 em Atibaia SP"} <= nomes
    assert len(nomes) >= 11
    cd = next(l for l in banco.listar_locais() if l.nome_exibicao == "CD de Contagem")
    assert cd.raio_m == 150 and cd.aliases_ss == ("CECOTI CD CONTAGEM",)


def test_crud_local():
    lid = banco.salvar_local({"nome_exibicao": "Posto Teste em X MG", "genero": "o", "tipo": "POSTO", "aliases_ss": ["POSTO T"],
                              "latitude": -20.0, "longitude": -44.0, "raio_m": 200})
    banco.marcar_cadastrado_na_ss(lid, True)
    l = next(l for l in banco.listar_locais() if l.id == lid)
    assert l.cadastrado_na_ss and l.aliases_ss == ("POSTO T",)
    banco.salvar_local({"nome_exibicao": "Posto Teste 2 em X MG", "genero": "o", "tipo": "POSTO", "aliases_ss": [], "raio_m": 250}, lid)
    assert next(l for l in banco.listar_locais() if l.id == lid).nome_exibicao == "Posto Teste 2 em X MG"
    banco.excluir_local(lid)
    assert all(l.id != lid for l in banco.listar_locais())
