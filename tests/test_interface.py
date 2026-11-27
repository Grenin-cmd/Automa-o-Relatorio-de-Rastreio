import io

import pytest

import app
import banco
from tests.helpers_web import cliente_logado, post


@pytest.mark.parametrize("url", ["/pois", "/regras", "/usuarios", "/perfil"])
def test_telas_novas_respondem_logado_e_exigem_login(url):
    assert cliente_logado().get(url).status_code == 200
    assert app.app.test_client().get(url).status_code == 302


def test_configuracoes_redireciona_para_pois():
    r = cliente_logado().get("/configuracoes")
    assert r.status_code == 302 and r.headers["Location"].endswith("/pois")


def test_menu_tem_os_modulos_e_sem_usuarios_para_quem_nao_pode():
    html = cliente_logado().get("/pois").get_data(as_text=True)
    for item in ["Análise de rastreio", "Auditoria de roteiro", "Base de POIs", "Regras de IA", "Usuários", "Meu perfil"]:
        assert item in html
    comum = cliente_logado(admin=False)
    assert "Usuários" not in comum.get("/pois").get_data(as_text=True)
    assert comum.get("/usuarios").status_code == 302


def test_pois_nao_renderiza_a_base_inteira():
    banco.save_saved_pois([{"id": "p1", "nome": "POSTO RENDER TESTE", "tipo": "posto", "latitude": -20.0, "longitude": -44.0,
                            "cidade": "", "estado": "", "rodovia": "", "raio_metros": 200.0, "tempo_parado_seg": 120,
                            "velocidade_maxima_kmh": 10.0}])
    html = cliente_logado().get("/pois").get_data(as_text=True)
    assert "POSTO RENDER TESTE" not in html and "/api/pois" in html


def test_acoes_redirecionam_para_as_telas_novas():
    c = cliente_logado()
    r = post(c, "/adicionar_regra_feedback", descricao_regra="Regra de teste", categoria="GERAL")
    assert r.headers["Location"].endswith("/regras")
    assert "Regra de teste" in c.get("/regras").get_data(as_text=True)
    assert post(c, "/excluir_pois", poi_ids="nao-existe").headers["Location"].endswith("/pois")
    arquivo = (io.BytesIO(b"nome;latitude;longitude\nPOSTO X;-20,1;-44,2\n"), "pois.csv")
    r = c.post("/", data={"csrf_token": __import__("tests.helpers_web", fromlist=["token"]).token(c, "/pois"),
                          "action": "import_pois", "arquivo_pois": arquivo}, content_type="multipart/form-data")
    assert r.headers["Location"].endswith("/pois")


def test_criar_usuario_pela_tela_de_usuarios():
    c = cliente_logado()
    r = post(c, "/usuarios", acao="criar_usuario", nome="novo_pela_tela", senha="senhaforte1")
    assert r.headers["Location"].endswith("/usuarios")
    assert "novo_pela_tela" in c.get("/usuarios").get_data(as_text=True)


def test_perfil_troca_senha():
    c = cliente_logado()
    r = post(c, "/trocar_senha", senha_atual="senhaforte1", nova_senha="outrasenha9", confirmacao="outrasenha9")
    assert r.status_code == 302
    assert c.get("/perfil").status_code == 200


def test_login_tem_visual_novo():
    html = app.app.test_client().get("/login").get_data(as_text=True)
    assert "Plus Jakarta Sans" in html and "Entrar" in html


def test_troca_de_senha_de_outro_usuario_nao_apaga_senha_inicial_do_admin(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(banco, "data_dir", lambda: str(tmp_path))
    arquivo = tmp_path / banco.ARQUIVO_SENHA_INICIAL
    arquivo.write_text("Usuario: admin\nSenha temporaria: x\n", encoding="utf-8")
    banco.remover_arquivo_senha_inicial("outra_pessoa")
    assert arquivo.exists()
    banco.remover_arquivo_senha_inicial("admin")
    assert not os.path.exists(arquivo)
