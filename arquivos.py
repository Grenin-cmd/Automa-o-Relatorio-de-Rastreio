"""Leitura de planilhas (CSV/Excel) e gerenciamento de uploads temporários."""
from __future__ import annotations

import io
import os
import tempfile

import pandas as pd
from utils import normalize_columns


def carregar_arquivo(uploaded_file) -> pd.DataFrame:
    if isinstance(uploaded_file, str):
        caminho = uploaded_file
        if not os.path.exists(caminho):
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}.")

        extensao = os.path.splitext(caminho)[1].lower()
        if extensao == ".csv":
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
                for sep in [",", ";", "\t", "|"]:
                    try:
                        df = pd.read_csv(caminho, encoding=encoding, sep=sep)
                        df = normalize_columns(df)
                        if len(df.columns) > 1:
                            return df
                    except Exception:
                        continue
            raise ValueError("Não foi possível decodificar o CSV. Verifique o encoding e o delimitador.")

        if extensao in {".xls", ".xlsx"}:
            try:
                df = pd.read_excel(caminho, engine="calamine")
            except Exception:
                df = pd.read_excel(caminho)
            return normalize_columns(df)

        raise ValueError("Formato não suportado. Use CSV ou Excel.")

    nome = uploaded_file.filename
    if not nome:
        raise ValueError("Nenhum arquivo selecionado.")

    _, extensao = os.path.splitext(nome)
    extensao = extensao.lower()

    if extensao == ".csv":
        dados = uploaded_file.read()
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
            for sep in [",", ";", "\t", "|"]:
                try:
                    df = pd.read_csv(io.BytesIO(dados), encoding=encoding, sep=sep)
                    df = normalize_columns(df)
                    if len(df.columns) > 1:
                        return df
                except Exception:
                    continue
        raise ValueError("Não foi possível decodificar o CSV.")

    if extensao in {".xls", ".xlsx"}:
        dados = uploaded_file.read()
        buffer = io.BytesIO(dados)
        try:
            df = pd.read_excel(buffer, engine="calamine")
        except Exception:
            df = pd.read_excel(buffer)
        return normalize_columns(df)

    raise ValueError("Formato não suportado. Use CSV ou Excel.")


def salvar_upload(uploaded_file) -> str:
    dados = uploaded_file.read()
    _, extensao = os.path.splitext(uploaded_file.filename)
    extensao = extensao.lower() if extensao else ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=extensao)
    tmp.write(dados)
    tmp.flush()
    tmp.close()
    return tmp.name


def remover_temporario(caminho: str | None) -> None:
    """Remove um arquivo temporário de upload, ignorando se já não existir.
    Só apaga arquivos dentro do diretório temporário do sistema."""
    if not caminho:
        return
    tmp_dir = os.path.realpath(tempfile.gettempdir())
    real = os.path.realpath(caminho)
    if os.path.commonpath([tmp_dir, real]) != tmp_dir:
        return
    try:
        os.unlink(real)
    except OSError:
        pass
