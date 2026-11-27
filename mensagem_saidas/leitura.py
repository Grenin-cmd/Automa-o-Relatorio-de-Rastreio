"""Leitura das exportações CSV da SS Telemática para um formato interno único."""
from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

from analisador_rastreio import _UFS_POR_NOME

COLUNAS = ["placa", "data_hora", "velocidade_kmh", "ignicao", "evento", "poi_ss", "poi_ss_dist_m",
           "endereco", "cidade", "uf", "lat", "lon"]

_SEM_POI = {"", "nao informado", "nan", "none"}


class FormatoSSDesconhecido(ValueError):
    """A planilha não corresponde a nenhum formato de exportação conhecido da SS."""


def _sem_acento(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


def extrair_cidade_uf(endereco: str) -> tuple[str, str]:
    """'Rua X - Cidade - Estado - Brasil' -> ('Cidade', 'UF')."""
    if not endereco or not isinstance(endereco, str):
        return "", ""
    partes = [p.strip() for p in endereco.split(" - ") if p.strip()]
    if partes and _sem_acento(partes[-1]).lower() == "brasil":
        partes = partes[:-1]
    for i in range(len(partes) - 1, -1, -1):
        chave = _sem_acento(partes[i]).lower()
        uf = _UFS_POR_NOME.get(chave) or (partes[i] if re.fullmatch(r"[A-Z]{2}", partes[i]) else None)
        if uf:
            cidade = partes[i - 1].split(",")[-1].strip() if i > 0 else ""
            return cidade, uf
    return "", ""


def _ler_csv(origem: str | bytes) -> pd.DataFrame:
    dados = origem if isinstance(origem, bytes) else open(origem, "rb").read()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            texto = dados.decode(encoding)
        except UnicodeDecodeError:
            continue
        try:
            return pd.read_csv(io.StringIO(texto), sep=";", dtype=str, keep_default_na=False)
        except (pd.errors.EmptyDataError, pd.errors.ParserError) as erro:
            raise FormatoSSDesconhecido(f"Formato de planilha da SS não reconhecido: {erro}") from erro
    raise FormatoSSDesconhecido("Não foi possível decodificar o arquivo (esperado cp1252 ou UTF-8).")


def _numero(serie: pd.Series) -> pd.Series:
    extraido = serie.astype(str).str.extract(r"(-?\d+(?:[.,]\d+)?)")[0]
    return pd.to_numeric(extraido.str.replace(",", ".", regex=False), errors="coerce")


def ler_exportacao_ss(origem: str | bytes) -> pd.DataFrame:
    """Lê a exportação 'Histórico' ou 'Histórico completo' da SS (caminho ou bytes)."""
    bruto = _ler_csv(origem)
    cols = set(bruto.columns)

    if {"Placa", "Data", "Hora", "Velocidade", "Distância", "POI"} <= cols:
        endereco = bruto.get("Endereço", pd.Series([""] * len(bruto)))
        dist = bruto["Distância"]
        ign = bruto["Ignição"].map({"Ligado": True, "Desligado": False}) if "Ignição" in cols else None
        lat = lon = pd.Series([None] * len(bruto), dtype="object")
    elif {"Placa", "Data", "Velocidade", "POI", "POI - Distância", "Latitude / Longitude"} <= cols:
        endereco = bruto.get("Local", pd.Series([""] * len(bruto)))
        dist = bruto["POI - Distância"]
        ign = None
        coords = bruto["Latitude / Longitude"].str.split("/", n=1, expand=True)
        lat = pd.to_numeric(coords[0].str.strip(), errors="coerce")
        lon = pd.to_numeric(coords[1].str.strip(), errors="coerce")
    else:
        raise FormatoSSDesconhecido(f"Formato de planilha da SS não reconhecido. Colunas lidas: {list(bruto.columns)}")

    poi = bruto["POI"].astype(str).str.strip()
    poi = poi.where(~poi.map(lambda v: _sem_acento(v).lower() in _SEM_POI), None)
    cidades_ufs = endereco.astype(str).map(extrair_cidade_uf)

    df = pd.DataFrame({
        "placa": bruto["Placa"].astype(str).str.strip(),
        "data_hora": pd.to_datetime(bruto["Data"], format="%d/%m/%y %H:%M:%S", errors="coerce"),
        "velocidade_kmh": _numero(bruto["Velocidade"]).astype(float),
        "ignicao": ign.astype(object).where(ign.notna(), None) if ign is not None else pd.Series([None] * len(bruto), dtype="object"),
        "evento": bruto.get("Evento", pd.Series([""] * len(bruto))).astype(str),
        "poi_ss": poi,
        "poi_ss_dist_m": _numero(dist),
        "endereco": endereco.astype(str),
        "cidade": cidades_ufs.map(lambda t: t[0]),
        "uf": cidades_ufs.map(lambda t: t[1]),
        "lat": lat.astype(float) if lat.dtype != object else lat,
        "lon": lon.astype(float) if lon.dtype != object else lon,
    })
    tem_poi = df["poi_ss"].notna()
    df["poi_ss"] = df["poi_ss"].astype(object).where(tem_poi, None)
    df["poi_ss_dist_m"] = df["poi_ss_dist_m"].astype(object).where(df["poi_ss_dist_m"].notna() & tem_poi, None)
    df = df.dropna(subset=["data_hora"]).sort_values(["placa", "data_hora"], kind="stable").reset_index(drop=True)
    return df[COLUNAS]
