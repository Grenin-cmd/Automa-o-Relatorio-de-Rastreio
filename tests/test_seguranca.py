import os
import re
import unittest
import uuid

import numpy as np
import pandas as pd
from werkzeug.security import generate_password_hash

import app as app_module
import seguranca


def _csrf(client, pagina: str = "/login") -> str:
    client.get(pagina)
    with client.session_transaction() as sess:
        return sess[seguranca.CSRF_SESSION_KEY]


def _criar_usuario(nome: str, senha: str, deve_trocar: int = 0, admin: int = 0) -> str:
    usuario_id = uuid.uuid4().hex
    conn = app_module._get_db_connection()
    try:
        conn.execute(
            "INSERT INTO usuarios (id, nome, senha_hash, pode_cadastrar_usuarios, deve_trocar_senha) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, nome, generate_password_hash(senha), admin, deve_trocar),
        )
        conn.commit()
    finally:
        conn.close()
    return usuario_id


def _login(client, nome: str, senha: str, proxima: str | None = None):
    url = "/login" + (f"?proxima={proxima}" if proxima else "")
    token = _csrf(client)
    return client.post(url, data={"nome": nome, "senha": senha, "csrf_token": token})


class FuncoesSegurancaTests(unittest.TestCase):
    def test_destino_seguro_bloqueia_urls_externas(self):
        self.assertEqual(seguranca.destino_seguro("/configuracoes", "/"), "/configuracoes")
        for ruim in ["https://evil.com", "//evil.com", "/\\evil.com", "javascript:alert(1)", "", None]:
            self.assertEqual(seguranca.destino_seguro(ruim, "/"), "/", ruim)

    def test_limitador_bloqueia_apos_max_falhas(self):
        lim = seguranca.LimitadorTentativas(max_falhas=3, janela_seg=60)
        for _ in range(3):
            self.assertFalse(lim.bloqueado("x"))
            lim.registrar_falha("x")
        self.assertTrue(lim.bloqueado("x"))
        lim.limpar("x")
        self.assertFalse(lim.bloqueado("x"))

    def test_validar_nova_senha(self):
        self.assertIsNotNone(seguranca.validar_nova_senha("curta"))
        self.assertIsNotNone(seguranca.validar_nova_senha("senhalonga1", "outra"))
        self.assertIsNone(seguranca.validar_nova_senha("senhalonga1", "senhalonga1"))

    def test_token_api(self):
        os.environ["API_TOKEN"] = "segredo123"
        try:
            self.assertTrue(seguranca.token_api_valido({"Authorization": "Bearer segredo123"}))
            self.assertTrue(seguranca.token_api_valido({"X-API-Key": "segredo123"}))
            self.assertFalse(seguranca.token_api_valido({"X-API-Key": "errado"}))
        finally:
            os.environ.pop("API_TOKEN")
        self.assertFalse(seguranca.token_api_valido({"X-API-Key": ""}))

    def test_secret_key_persistida(self):
        data_dir = os.environ["RASTREIO_DATA_DIR"]
        self.assertEqual(seguranca.carregar_secret_key(data_dir), seguranca.carregar_secret_key(data_dir))


class AppSegurancaTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        app_module._LIMITADOR_LOGIN._falhas.clear()
        self.client = app_module.app.test_client()

    def test_admin_inicial_criado_com_senha_aleatoria_e_troca_obrigatoria(self):
        caminho = os.path.join(os.environ["RASTREIO_DATA_DIR"], app_module._ARQUIVO_SENHA_INICIAL)
        with open(caminho, encoding="utf-8") as fh:
            conteudo = fh.read()
        senha = re.search(r"Senha temporaria: (\S+)", conteudo).group(1)
        self.assertNotEqual(senha, app_module._SENHA_PADRAO_LEGADA)

        resp = _login(self.client, "admin", senha)
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/trocar_senha", resp.headers["Location"])

    def test_post_sem_csrf_e_rejeitado(self):
        _criar_usuario("csrfuser", "senhaforte1")
        resp = self.client.post("/login", data={"nome": "csrfuser", "senha": "senhaforte1"})
        self.assertEqual(resp.status_code, 303)
        with self.client.session_transaction() as sess:
            self.assertNotIn("usuario_id", sess)

    def test_login_nao_redireciona_para_site_externo(self):
        _criar_usuario("redir", "senhaforte1")
        resp = _login(self.client, "redir", "senhaforte1", proxima="https://evil.com")
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("evil.com", resp.headers["Location"])

    def test_login_bloqueia_apos_muitas_falhas(self):
        _criar_usuario("bruto", "senhaforte1")
        for _ in range(5):
            _login(self.client, "bruto", "errada")
        resp = _login(self.client, "bruto", "senhaforte1")
        self.assertEqual(resp.status_code, 429)

    def test_troca_de_senha(self):
        _criar_usuario("trocador", "senhaforte1", deve_trocar=1)
        _login(self.client, "trocador", "senhaforte1")
        token = _csrf(self.client, "/trocar_senha")
        resp = self.client.post("/trocar_senha", data={
            "senha_atual": "senhaforte1", "nova_senha": "novasenha22",
            "confirmacao": "novasenha22", "csrf_token": token,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.get("/configuracoes").status_code, 200)

    def test_senha_padrao_legada_obriga_troca(self):
        usuario_id = _criar_usuario("legado", app_module._SENHA_PADRAO_LEGADA)
        conn = app_module._get_db_connection()
        try:
            app_module._forcar_troca_de_senha_padrao_legada(conn)
            conn.commit()
            row = conn.execute("SELECT deve_trocar_senha FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["deve_trocar_senha"], 1)

    def test_api_exige_autenticacao(self):
        self.assertEqual(self.client.get("/api/veiculos").status_code, 401)
        self.assertEqual(self.client.post("/api/dispositivos/receber", json={"placa": "ABC"}).status_code, 401)
        os.environ["API_TOKEN"] = "tok"
        try:
            resp = self.client.post(
                "/api/dispositivos/receber",
                json={"placa": "ABC1D23", "lat": -23.5, "lon": -46.6},
                headers={"Authorization": "Bearer tok"},
            )
            self.assertEqual(resp.status_code, 200)
            recentes = self.client.get("/api/dispositivos/recentes", headers={"X-API-Key": "tok"}).get_json()
            self.assertEqual(recentes["dados"][0]["veiculo_id"], "ABC1D23")
        finally:
            os.environ.pop("API_TOKEN")


class ApiPoisTests(unittest.TestCase):
    def test_busca_paginada_de_pois(self):
        app_module._save_saved_pois([
            {"id": f"id{i}", "nome": f"Posto São João {i}", "tipo": "posto", "latitude": -23.0, "longitude": -46.0,
             "cidade": "Campinas", "estado": "SP", "rodovia": "", "raio_metros": 200.0,
             "tempo_parado_seg": 120, "velocidade_maxima_kmh": 10.0}
            for i in range(30)
        ] + [
            {"id": "cli", "nome": "Cliente Alfa", "tipo": "cliente", "latitude": -22.0, "longitude": -45.0,
             "cidade": "Santos", "estado": "SP", "rodovia": "", "raio_metros": 300.0,
             "tempo_parado_seg": 120, "velocidade_maxima_kmh": 10.0}
        ])
        client = app_module.app.test_client()
        _criar_usuario("buscador", "senhaforte1")
        _login(client, "buscador", "senhaforte1")

        resp = client.get("/api/pois?q=sao joao&limite=10").get_json()
        self.assertEqual(resp["total"], 30)
        self.assertEqual(len(resp["dados"]), 10)

        resp = client.get("/api/pois?q=santos").get_json()
        self.assertEqual([p["id"] for p in resp["dados"]], ["cli"])

        html = client.get("/").get_data(as_text=True)
        self.assertNotIn("Posto São João 1<", html)  # POIs não são mais renderizados no HTML


class ParadasSuspeitasTests(unittest.TestCase):
    def _df_parado(self, lat: float, lon: float) -> pd.DataFrame:
        horarios = pd.date_range("2026-01-01 08:00", periods=4, freq="5min")
        return pd.DataFrame({
            "placa": ["ABC1234"] * 4,
            "timestamp": horarios.strftime("%d/%m/%Y %H:%M:%S"),
            "velocidade_kmh": [0, 0, 0, 0],
            "latitude": [lat] * 4,
            "longitude": [lon] * 4,
        })

    def test_parada_dentro_de_poi_cadastrado_nao_e_suspeita(self):
        pois = [{"nome": "Cliente", "latitude": -23.5505, "longitude": -46.6333, "raio_metros": 300}]
        df = self._df_parado(-23.5506, -46.6334)
        self.assertEqual(app_module._find_suspicious_stops(df, 200.0, None, pois), [])

    def test_parada_longe_dos_pois_e_suspeita(self):
        pois = [{"nome": "Cliente", "latitude": -23.5505, "longitude": -46.6333, "raio_metros": 300}]
        df = self._df_parado(-22.0, -45.0)
        self.assertEqual(len(app_module._find_suspicious_stops(df, 200.0, None, pois)), 1)

    def test_calculo_em_blocos_igual_ao_calculo_direto(self):
        rng = np.random.default_rng(42)
        lats = rng.uniform(-24, -23, 700)
        lons = rng.uniform(-47, -46, 700)
        pois = [
            {"latitude": float(a), "longitude": float(b), "raio_metros": 2000}
            for a, b in zip(rng.uniform(-24, -23, 300), rng.uniform(-47, -46, 300))
        ]
        resultado = app_module._pontos_dentro_de_algum_poi(lats, lons, pois, 200.0)
        esperado = np.array([
            any(app_module._haversine_metros(la, lo, p["latitude"], p["longitude"]) <= 2000 for p in pois)
            for la, lo in zip(lats, lons)
        ])
        np.testing.assert_array_equal(resultado, esperado)


if __name__ == "__main__":
    unittest.main()
