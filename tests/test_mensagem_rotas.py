import io
import uuid
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

import app
import banco
import seguranca
from rotas import mensagem as rotas_mensagem

FIX = Path(__file__).parent / "fixtures" / "ss"


@pytest.fixture
def client_logado(monkeypatch):
    monkeypatch.setattr(rotas_mensagem, "sugerir_nome", lambda *a, **k: "Posto Sugerido")
    nome = f"msg{uuid.uuid4().hex[:6]}"
    conn = banco.get_connection()
    conn.execute("INSERT INTO usuarios (id, nome, senha_hash, pode_cadastrar_usuarios, deve_trocar_senha) VALUES (?, ?, ?, 0, 0)",
                 (uuid.uuid4().hex, nome, generate_password_hash("senhaforte1")))
    conn.commit()
    conn.close()
    c = app.app.test_client()
    c.post("/login", data={"nome": nome, "senha": "senhaforte1", "csrf_token": _token(c, "/login")})
    return c


def _token(c, pagina):
    c.get(pagina)
    with c.session_transaction() as s:
        return s[seguranca.CSRF_SESSION_KEY]


def _post(c, url, arquivo=None, **campos):
    dados = {"csrf_token": _token(c, "/mensagem_saidas"), **campos}
    if arquivo is not None:
        dados["arquivo"] = (io.BytesIO(Path(arquivo).read_bytes()), Path(arquivo).name)
    return c.post(url, data=dados, content_type="multipart/form-data", follow_redirects=True)


def test_gera_mensagem_pelo_upload(client_logado):
    r = _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_completo_2026-11-27.csv")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "*Horário de saída das Carretas 27/11/2026*" in html
    assert "PLA-0A05: Saída do CD Supermercado BH em Contagem MG as 05:5" in html


def test_mensagem_continua_ao_recarregar(client_logado):
    _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_completo_2026-11-27.csv")
    assert "PLA-0A06: Saída do Posto Dom Pedro" in client_logado.get("/mensagem_saidas").get_data(as_text=True)


def test_conferir_mostra_sugestao_e_aviso(client_logado):
    html = _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_2026-11-26.csv").get_data(as_text=True)
    assert "Carmópolis de Minas" in html and "18:00" in html


def test_aceitar_cria_local_e_regera(client_logado):
    _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_2026-11-26.csv")
    r = _post(client_logado, "/mensagem_saidas/aceitar", nome_exibicao="Posto Padre Libério em Papagaios MG", genero="o",
              tipo="POSTO", raio_m="250", aliases_ss="", latitude="", longitude="")
    assert any(l.nome_exibicao == "Posto Padre Libério em Papagaios MG" for l in banco.listar_locais())
    assert "*Horário de saída das Carretas 26/11/2026*" in r.get_data(as_text=True)


def test_ignorar_remove_da_lista(client_logado):
    _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_2026-11-26.csv")
    from mensagem_saidas.leitura import ler_exportacao_ss
    from mensagem_saidas.regras import montar_mensagem
    item = montar_mensagem(ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv")), banco.listar_locais()).conferir[0]
    html = _post(client_logado, "/mensagem_saidas/ignorar", chave=item.chave).get_data(as_text=True)
    assert item.chave not in html


def test_relatorio_xlsx(client_logado):
    _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_2026-11-26.csv")
    r = client_logado.get("/mensagem_saidas/relatorio.xlsx")
    assert r.status_code == 200 and r.mimetype.endswith("spreadsheetml.sheet")


def test_locais_importantes_lista_e_cria(client_logado):
    assert "CD de Contagem" in client_logado.get("/locais_importantes").get_data(as_text=True)
    _post(client_logado, "/locais_importantes", acao="salvar", nome_exibicao="Posto Novo em Y MG", genero="o", tipo="POSTO",
          raio_m="200", aliases_ss="POSTO NOVO\nPOSTO NOVO 2", latitude="-20,1", longitude="-44,2")
    novo = next(l for l in banco.listar_locais() if l.nome_exibicao == "Posto Novo em Y MG")
    assert novo.aliases_ss == ("POSTO NOVO", "POSTO NOVO 2") and novo.latitude == -20.1


def test_exige_login():
    assert app.app.test_client().get("/mensagem_saidas").status_code == 302


def test_planilha_invalida_mostra_erro(client_logado, tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a;b\n1;2\n", encoding="cp1252")
    assert "não reconhecido" in _post(client_logado, "/mensagem_saidas", arquivo=f).get_data(as_text=True).lower()
