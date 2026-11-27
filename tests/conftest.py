"""Configuração comum dos testes.

Aponta o diretório de dados para uma pasta temporária ANTES de importar o
app, para que os testes nunca leiam nem alterem o poi_store.db real.
"""
import os
import sys
import tempfile

_DATA_DIR = tempfile.mkdtemp(prefix="rastreio_testes_")
os.environ["RASTREIO_DATA_DIR"] = _DATA_DIR
os.environ.pop("ADMIN_INICIAL_SENHA", None)
os.environ.pop("ADMIN_INICIAL_USUARIO", None)
os.environ.pop("API_TOKEN", None)
os.environ.pop("FLASK_SECRET_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
