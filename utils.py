"""Funções utilitárias de texto e números (normalização de colunas,
conversão de coordenadas e valores no formato brasileiro)."""
from __future__ import annotations

import unicodedata
from typing import Any

import pandas as pd


def normalize_column_name(name: str) -> str:
    name = str(name).strip().lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.replace(" ", "_").replace("/", "_").replace("-", "_")
    while "__" in name:
        name = name.replace("__", "_")
    return name


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(col) for col in df.columns]
    return df


def parse_number(value: Any, cast: type, error_message: str):
    if pd.isna(value):
        raise ValueError(error_message)

    if isinstance(value, str):
        normalized = value.strip().replace("\xa0", " ").replace("\u202f", " ").replace(" ", "")
        if not normalized or normalized.lower() in {"nan", "n/a", "na", "none", "null", "-", "--"}:
            raise ValueError(error_message)

        if "," in normalized:
            if "." in normalized and normalized.rfind(".") < normalized.rfind(","):
                normalized = normalized.replace(".", "")
            normalized = normalized.replace(",", ".")
        elif normalized.count(".") > 1:
            first_dot = normalized.find(".")
            normalized = normalized[:first_dot+1] + normalized[first_dot+1:].replace(".", "")

        value = normalized

    try:
        return cast(value)
    except Exception:
        raise ValueError(error_message)


def resolver_coluna(df: pd.DataFrame, aliases: list[str]) -> str:
    columns = [normalize_column_name(col) for col in df.columns]
    for alias in aliases:
        alias_norm = normalize_column_name(alias)
        for i, col in enumerate(columns):
            if not col:
                continue
            if alias_norm == col or alias_norm in col or col in alias_norm:
                return df.columns[i]
    raise ValueError(f"Coluna não encontrada. Esperava uma das opções: {aliases}")


def ler_pois(texto: str) -> list[dict[str, object]]:
    pois = []
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        partes = linha.strip().split(":")
        if len(partes) != 7:
            continue
        nome, tipo, lat, lon, raio, tempo, velocidade = partes
        pois.append(
            {
                "nome": nome,
                "tipo": tipo,
                "latitude": parse_number(lat, float, "Latitude ou longitude inválida no arquivo de POIs."),
                "longitude": parse_number(lon, float, "Latitude ou longitude inválida no arquivo de POIs."),
                "raio_metros": parse_number(raio, float, "Raio inválido no arquivo de POIs."),
                "tempo_parado_seg": parse_number(tempo, int, "Tempo parado inválido no arquivo de POIs."),
                "velocidade_maxima_kmh": parse_number(velocidade, float, "Velocidade máxima inválida no arquivo de POIs."),
            }
        )
    return pois


def converter_coordenada(val: Any) -> float | None:
    """Converte coordenadas em formato brasileiro (ex: -19.839.907 ou -19,839907)
    para float, removendo pontos extras de milhar antes da conversão."""
    if val is None or pd.isna(val):
        return None
    texto = str(val).strip().replace("\xa0", "").replace("\u202f", "").replace(" ", "")
    if not texto:
        return None
    if texto.count(".") > 1:
        # Múltiplos pontos: mantém o primeiro como separador decimal e remove os demais.
        partes = texto.split(".")
        texto = partes[0] + "." + "".join(partes[1:])
    elif "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def converter_numero_opcional(val: Any, cast: type, default: float | int) -> Any:
    """Converte um valor numérico opcional (raio, tempo, velocidade) usando a mesma
    lógica de normalização de pontos/vírgulas. Retorna o default se vazio ou inválido."""
    if val is None or pd.isna(val):
        return default
    convertido = converter_coordenada(val)
    if convertido is None:
        return default
    try:
        return cast(convertido)
    except (ValueError, TypeError):
        return default


def parse_velocidade_series(series: pd.Series) -> pd.Series:
    extraida = series.astype(str).str.extract(r"(-?\d+(?:[.,]\d+)?)")[0]
    return pd.to_numeric(extraida.str.replace(",", ".", regex=False), errors="coerce")


def format_duration(seconds: int) -> str:
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def normalizar_busca(texto: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(ch for ch in texto if not unicodedata.combining(ch)).strip()
