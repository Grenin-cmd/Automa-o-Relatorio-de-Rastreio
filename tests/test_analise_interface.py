import io
from pathlib import Path

import pandas as pd

from tests.helpers_web import cliente_logado, token

RAIZ = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures" / "ss"


def _enviar(c, arquivo):
    dados = {"csrf_token": token(c, "/"), "arquivo": (io.BytesIO(Path(arquivo).read_bytes()), Path(arquivo).name)}
    return c.post("/", data=dados, content_type="multipart/form-data")


def test_upload_da_ss_abre_mensagem_do_dia():
    c = cliente_logado()
    r = _enviar(c, FIX / "historico_completo_2026-11-27.csv")
    assert r.status_code == 302 and r.headers["Location"].endswith("/?aba=mensagem")
    html = c.get("/?aba=mensagem").get_data(as_text=True)
    for placa in ["PLA-0A01", "PLA-0A04", "PLA-0A08"]:
        assert placa in html
    assert "Saiu 05:41" in html and "Horário de saída das Carretas 27/11/2026" in html
    assert "Copiar mensagem" not in html and "Ao vivo" not in html


def test_editar_e_restaurar_placa():
    c = cliente_logado()
    _enviar(c, FIX / "historico_completo_2026-11-27.csv")
    c.post("/mensagem/editar", data={"csrf_token": token(c, "/"), "placa": "PLA-0A01", "texto": "Saída da Matriz as 05:43 (ajustado).", "acao": "salvar"})
    html = c.get("/?aba=mensagem").get_data(as_text=True)
    assert "PLA-0A01: Saída da Matriz as 05:43 (ajustado)." in html
    c.post("/mensagem/editar", data={"csrf_token": token(c, "/"), "placa": "PLA-0A01", "texto": "", "acao": "restaurar"})
    assert "(ajustado)" not in c.get("/?aba=mensagem").get_data(as_text=True)


def test_word_usa_texto_editado():
    from docx import Document
    c = cliente_logado()
    _enviar(c, FIX / "historico_completo_2026-11-27.csv")
    c.post("/mensagem/editar", data={"csrf_token": token(c, "/"), "placa": "PLA-0A02", "texto": "Texto editado no Word.", "acao": "salvar"})
    r = c.get("/download_word")
    assert r.status_code == 200
    texto = "\n".join(p.text for p in Document(io.BytesIO(r.data)).paragraphs)
    assert "PLA-0A02: Texto editado no Word." in texto


def test_nova_planilha_zera_edicoes():
    c = cliente_logado()
    _enviar(c, FIX / "historico_completo_2026-11-27.csv")
    c.post("/mensagem/editar", data={"csrf_token": token(c, "/"), "placa": "PLA-0A01", "texto": "EDITADO", "acao": "salvar"})
    _enviar(c, FIX / "historico_completo_2026-11-27.csv")
    assert "EDITADO" not in c.get("/?aba=mensagem").get_data(as_text=True)


def test_excel_do_aprendiz(monkeypatch):
    from rotas import mensagem
    monkeypatch.setattr(mensagem, "sugerir_nome", lambda *a, **k: "Posto Sugerido")
    c = cliente_logado()
    _enviar(c, FIX / "historico_completo_2026-11-27.csv")
    r = c.get("/mensagem/excel")
    assert r.status_code == 200
    assert list(pd.read_excel(io.BytesIO(r.data)).columns) == ["Nome sugerido", "Latitude", "Longitude", "Link Google Maps"]


def test_outras_abas_respondem():
    c = cliente_logado()
    _enviar(c, FIX / "historico_completo_2026-11-27.csv")
    for url in ["/?aba=relatorio&placa=PLA-0A01", "/?aba=linha&placa=PLA-0A01", "/?aba=paradas&raio=200"]:
        r = c.get(url)
        assert r.status_code == 200, url
        assert "Ocorreu um erro" not in r.get_data(as_text=True)


def test_planilha_generica_abre_no_relatorio():
    c = cliente_logado()
    r = _enviar(c, RAIZ / "test_rastreio.csv")
    assert r.headers["Location"].endswith("/?aba=relatorio")
    assert c.get("/?aba=relatorio").status_code == 200


def test_sem_planilha_mostra_envio():
    html = cliente_logado().get("/").get_data(as_text=True)
    assert 'name="arquivo"' in html and "Análise de rastreio" in html


def test_auditoria_no_novo_layout():
    html = cliente_logado().get("/auditoria_roteiro").get_data(as_text=True)
    assert "Meu perfil" in html and "Auditoria de roteiro" in html


def test_planilha_generica_tem_resumo_geral_e_word():
    c = cliente_logado()
    _enviar(c, RAIZ / "test_rastreio.csv")
    html = c.get("/?aba=resumo").get_data(as_text=True)
    assert "Resumo geral" in html and "ABC1234" in html
    assert c.get("/download_word").status_code == 200


def test_planilha_da_ss_nao_mostra_resumo_geral():
    c = cliente_logado()
    _enviar(c, FIX / "historico_completo_2026-11-27.csv")
    assert "aba=resumo" not in c.get("/?aba=mensagem").get_data(as_text=True)
