from __future__ import annotations

import unicodedata
from typing import List
import pandas as pd


def normalize_column_name(name: str) -> str:
    name = str(name).strip().lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.replace(" ", "_")
    name = name.replace("/", "_")
    name = name.replace("-", "_")
    while "__" in name:
        name = name.replace("__", "_")
    return name


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(col) for col in df.columns]
    return df


def ler_pois(texto: str) -> List[dict[str, object]]:
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
                "latitude": float(lat),
                "longitude": float(lon),
                "raio_metros": float(raio),
                "tempo_parado_seg": int(tempo),
                "velocidade_maxima_kmh": float(velocidade),
            }
        )
    return pois
