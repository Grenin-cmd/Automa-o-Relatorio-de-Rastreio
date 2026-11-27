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
