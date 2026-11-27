"""Utilitários de teste para rotas web (login, CSRF)."""
import uuid

from werkzeug.security import generate_password_hash

import app
import banco
import seguranca


def token(client, pagina="/login"):
    client.get(pagina)
    with client.session_transaction() as s:
        return s[seguranca.CSRF_SESSION_KEY]


def cliente_logado(admin=True):
    nome = f"u{uuid.uuid4().hex[:8]}"
    conn = banco.get_connection()
    conn.execute("INSERT INTO usuarios (id, nome, senha_hash, pode_cadastrar_usuarios, deve_trocar_senha) VALUES (?, ?, ?, ?, 0)",
                 (uuid.uuid4().hex, nome, generate_password_hash("senhaforte1"), 1 if admin else 0))
    conn.commit()
    conn.close()
    c = app.app.test_client()
    c.post("/login", data={"nome": nome, "senha": "senhaforte1", "csrf_token": token(c)})
    return c


def post(client, url, pagina="/perfil", **dados):
    return client.post(url, data={"csrf_token": token(client, pagina), **dados})
