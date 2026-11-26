"""Aplicação web Flask: cria o app, registra as rotas (blueprints) e inicia
o servidor local.

Organização dos módulos:
  config.py        carrega o .env e define diretórios
  banco.py         SQLite: tabelas, usuários iniciais, POIs e regras
  seguranca.py     CSRF, limite de login, senhas, token de API
  utils.py / geo.py  funções de texto, números e distâncias
  arquivos.py      leitura de planilhas e uploads temporários
  analise.py       paradas, linha do tempo, resumo geral e Word
  rotas/           blueprints de cada tela e das APIs
"""
from __future__ import annotations

import config  # noqa: F401  (precisa vir primeiro: carrega o .env)

import os
import socket
import threading
import time
import webbrowser
from urllib.parse import urlsplit

from flask import Flask, flash, redirect, request, session, url_for

import banco
import seguranca
from banco import get_regras_ativas, get_saved_pois
from rotas import analise as rotas_analise
from rotas import api as rotas_api
from rotas import auditoria as rotas_auditoria
from rotas import auth as rotas_auth
from rotas import configuracoes as rotas_configuracoes
from rotas.comum import VEICULOS_SERVICE, usuario_atual

app = Flask(__name__, template_folder=config.template_folder())
app.secret_key = seguranca.carregar_secret_key(config.data_dir())
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    CSRF_ENABLED=True,
)

for _modulo in (rotas_auth, rotas_analise, rotas_configuracoes, rotas_auditoria, rotas_api):
    app.register_blueprint(_modulo.bp)

banco.init_db()


@app.before_request
def _verificar_csrf():
    if not app.config.get("CSRF_ENABLED", True):
        return None
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if request.path.startswith("/api/"):
        return None  # APIs usam token próprio, não cookies de formulário
    token = request.form.get(seguranca.CSRF_FORM_FIELD) or request.headers.get(seguranca.CSRF_HEADER)
    if seguranca.csrf_valido(session, token):
        return None
    flash("Sua sessão expirou ou o formulário é inválido. Tente novamente.", "warning")
    destino = seguranca.destino_seguro(_caminho_local(request.referrer), url_for("analise.index"))
    return redirect(destino, 303)


def _caminho_local(url: str | None) -> str | None:
    """Converte uma URL absoluta do próprio host em caminho relativo."""
    if not url:
        return None
    partes = urlsplit(url)
    if partes.netloc and partes.netloc != request.host:
        return None
    caminho = partes.path or "/"
    return f"{caminho}?{partes.query}" if partes.query else caminho


@app.context_processor
def _inject_csrf():
    return {
        "csrf_token": lambda: seguranca.obter_csrf_token(session),
        "csrf_input": lambda: seguranca.csrf_input_html(session),
    }


@app.context_processor
def inject_globais():
    # Reaproveita o cache em memória de POIs (já povoado por get_saved_pois) em vez
    # de disparar uma segunda consulta ao SQLite em toda renderização de template.
    try:
        pois = get_saved_pois()
    except Exception:
        pois = []

    try:
        veiculos = VEICULOS_SERVICE.listar_veiculos()
    except Exception:
        veiculos = []

    return dict(
        regras_salvas=get_regras_ativas(),
        pois_salvos=pois,
        veiculos_ativos=veiculos,
        usuario_atual=usuario_atual(),
    )


def _server_host() -> str:
    """Por padrão o servidor só aceita conexões desta máquina. Para liberar o
    acesso pela rede local, defina HOST=0.0.0.0 no .env."""
    return os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"

def _find_available_port(initial_port: int = 5000) -> int:
    port = initial_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        while True:
            try:
                sock.bind((_server_host(), port))
                return port
            except OSError:
                port += 1

def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((_server_host(), port))
            return True
        except OSError:
            return False

def _get_server_port(default_port: int = 5000) -> int:
    port_str = os.environ.get("PORT")
    if port_str:
        try:
            port = int(port_str)
        except ValueError:
            raise RuntimeError("Valor inválido para a variável de ambiente PORT. Use um número inteiro.")

        if _is_port_available(port):
            return port
        raise RuntimeError(f"Porta {port} já está em uso. Pare o serviço existente ou defina PORT com outra porta.")

    if _is_port_available(default_port):
        return default_port

    return _find_available_port(default_port + 1)

def _open_browser(port: int) -> None:
    url = f"http://127.0.0.1:{port}/"

    def _try_open() -> None:
        time.sleep(1.0)
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass

    thread = threading.Thread(target=_try_open, daemon=True)
    thread.start()


if __name__ == "__main__":
    port = _get_server_port(5000)
    host = _server_host()
    print(f"Iniciando a aplicação em http://{host}:{port}/ ...")
    _open_browser(port)

    app.run(
        host=host,
        port=port,
        debug=False,
        use_reloader=False,
    )