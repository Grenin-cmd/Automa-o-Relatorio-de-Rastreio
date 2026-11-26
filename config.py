"""Configuração da aplicação: carrega o .env e define os diretórios.

Deve ser importado antes dos demais módulos do sistema, para que as
variáveis do .env (chaves de IA etc.) já estejam disponíveis.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"), override=True)


def template_folder() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "templates")  # type: ignore[attr-defined]
    return "templates"


def data_dir() -> str:
    """Diretório onde ficam o banco, a chave secreta e a senha inicial.
    Pode ser sobrescrito com RASTREIO_DATA_DIR (útil em testes e servidores)."""
    customizado = os.environ.get("RASTREIO_DATA_DIR")
    if customizado:
        os.makedirs(customizado, exist_ok=True)
        return customizado
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
