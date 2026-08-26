"""Módulo de Auditoria de Roteiro.

Lógica pura (sem Flask) para:
  1. Ler a planilha de carregamento (romaneio, ex: "carreg.xls"), filtrar pela
     placa selecionada, ignorar colunas financeiras e deduplicar clientes/
     endereços para obter uma lista única de pontos de entrega planejados.
  2. Geocodificar esses pontos cruzando o nome do cliente com a base de POIs
     já cadastrada no sistema (que já possui latitude/longitude).
  3. Cruzar os pontos de entrega com os logs de rastreio da placa (schema
     "bruto" com latitude/longitude, ou schema "plataforma" com POI/distância)
     usando uma tolerância de distância configurável, para classificar cada
     entrega como executada, não executada ou sem geolocalização disponível.
  4. Calcular estatísticas operacionais (planejado x executado).

Seguindo o mesmo estilo dos demais módulos do projeto (utils.py,
filtro_geometria.py): funções puras, tolerantes a variações de planilha e
fáceis de testar isoladamente.
"""

from __future__ import annotations

import math
import unicodedata
from typing import Any

import numpy as np
import pandas as pd


def _normalizar_chave(texto: Any) -> str:
    """Normaliza um texto (nome de cliente, endereço etc.) para uso como chave
    de deduplicação/matching: minúsculas, sem acentos, sem espaços extras."""
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    if not texto or texto in {"nan", "none", "n/a", "na"}:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = " ".join(texto.split())
    return texto


def _normalize_column_name(name: Any) -> str:
    name = str(name).strip().lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.replace(" ", "_").replace("/", "_").replace("-", "_")
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_normalize_column_name(col) for col in df.columns]
    return df


def _resolver_coluna_flex(df: pd.DataFrame, aliases: list[str]) -> str | None:
    """Como o resolvedor de colunas usado no resto do projeto, mas tolerante:
    retorna None em vez de levantar exceção quando a coluna não existe (a
    planilha de carregamento tem formato menos previsível que as demais)."""
    columns = list(df.columns)
    for alias in aliases:
        alias_norm = _normalize_column_name(alias)
        for col in columns:
            if _normalize_column_name(col) == alias_norm:
                return col
    for alias in aliases:
        alias_norm = _normalize_column_name(alias)
        for col in columns:
            col_norm = _normalize_column_name(col)
            if not col_norm:
                continue
            if alias_norm in col_norm or col_norm in alias_norm:
                return col
    return None


# Aliases de colunas conhecidas da planilha de carregamento/romaneio.
_ALIASES_CLIENTE = ["cliente", "nome_cliente", "razao_social", "destinatario", "nome", "loja"]
_ALIASES_ENDERECO = ["endereco_entrega", "endereco", "logradouro", "address"]
_ALIASES_CIDADE = ["cidade", "municipio"]
_ALIASES_ESTADO = ["estado", "uf"]
_ALIASES_PLACA = ["placa", "veiculo", "placa_veiculo", "plate"]
_ALIASES_VALOR = ["valor_nf", "valor_total", "valor_nota", "valor", "vlr", "preco"]


def parse_carregamento(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza a planilha de carregamento e remove colunas financeiras
    (requisito: ignorar valores financeiros ao montar a lista de entregas)."""
    if df is None or df.empty:
        raise ValueError("Planilha de carregamento vazia ou não informada.")

    working = normalize_columns(df.copy())

    col_cliente = _resolver_coluna_flex(working, _ALIASES_CLIENTE)
    if not col_cliente:
        raise ValueError(
            "Não foi possível identificar a coluna de Cliente na planilha de carregamento. "
            f"Colunas lidas: {list(df.columns)}"
        )

    col_endereco = _resolver_coluna_flex(working, _ALIASES_ENDERECO)
    col_cidade = _resolver_coluna_flex(working, _ALIASES_CIDADE)
    col_estado = _resolver_coluna_flex(working, _ALIASES_ESTADO)
    col_placa = _resolver_coluna_flex(working, _ALIASES_PLACA)

    # Remove qualquer coluna que pareça conter valores financeiros — elas não
    # fazem parte da lógica de auditoria de entregas e não devem ser exibidas.
    colunas_valor = [c for c in working.columns if any(alias in c for alias in _ALIASES_VALOR)]
    if colunas_valor:
        working = working.drop(columns=colunas_valor)

    resultado = pd.DataFrame({
        "cliente": working[col_cliente].astype(str).str.strip(),
        "endereco": working[col_endereco].astype(str).str.strip() if col_endereco else "",
        "cidade": working[col_cidade].astype(str).str.strip() if col_cidade else "",
        "estado": working[col_estado].astype(str).str.strip() if col_estado else "",
        "placa": working[col_placa].astype(str).str.strip().str.upper() if col_placa else "",
    })

    # Descarta linhas sem cliente identificável.
    resultado = resultado[resultado["cliente"].map(_normalizar_chave) != ""]
    return resultado.reset_index(drop=True)


def filtrar_por_placa(df: pd.DataFrame, placa: str) -> pd.DataFrame:
    """Filtra a planilha de carregamento pela placa selecionada. Se a
    planilha não tiver coluna de placa (ex: romaneio já é específico de um
    único veículo), retorna todas as linhas sem filtrar."""
    if not placa or "placa" not in df.columns or df["placa"].eq("").all():
        return df
    placa_norm = str(placa).strip().upper()
    filtrado = df[df["placa"].str.upper() == placa_norm]
    return filtrado if not filtrado.empty else df


def deduplicar_pontos_entrega(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Remove clientes/endereços duplicados, mantendo uma lista única de
    pontos de entrega planejados (requisito de limpeza de dados)."""
    if df.empty:
        return []

    chaves_cliente = df["cliente"].map(_normalizar_chave)
    chaves_endereco = df["endereco"].map(_normalizar_chave)
    chave_composta = chaves_cliente + "||" + chaves_endereco

    working = df.copy()
    working["_chave"] = chave_composta
    working = working.drop_duplicates(subset=["_chave"], keep="first")

    pontos: list[dict[str, Any]] = []
    for _, row in working.iterrows():
        pontos.append({
            "cliente": row["cliente"],
            "endereco": row["endereco"],
            "cidade": row["cidade"],
            "estado": row["estado"],
            "chave_cliente": _normalizar_chave(row["cliente"]),
        })
    return pontos


def geocodificar_pontos(
    pontos: list[dict[str, Any]], pois_cadastrados: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Cruza cada ponto de entrega com a base de POIs já cadastrada no
    sistema (por nome normalizado) para obter latitude/longitude. Pontos sem
    correspondência ficam marcados como não geocodificados — a auditoria
    continua funcionando para os demais (degradação graciosa)."""
    indice_pois: dict[str, dict[str, Any]] = {}
    for poi in pois_cadastrados:
        chave = _normalizar_chave(poi.get("nome"))
        if chave and chave not in indice_pois:
            indice_pois[chave] = poi

    resultado: list[dict[str, Any]] = []
    for ponto in pontos:
        ponto = dict(ponto)
        poi_encontrado = indice_pois.get(ponto["chave_cliente"])

        if not poi_encontrado:
            # Fallback: correspondência parcial (contém) quando a
            # correspondência exata por nome não é encontrada.
            for chave_poi, poi in indice_pois.items():
                if chave_poi and (chave_poi in ponto["chave_cliente"] or ponto["chave_cliente"] in chave_poi):
                    poi_encontrado = poi
                    break

        if poi_encontrado:
            ponto["latitude"] = float(poi_encontrado["latitude"])
            ponto["longitude"] = float(poi_encontrado["longitude"])
            ponto["geocodificado"] = True
        else:
            ponto["latitude"] = None
            ponto["longitude"] = None
            ponto["geocodificado"] = False

        resultado.append(ponto)

    return resultado


_ALIASES_LAT = ["latitude", "lat"]
_ALIASES_LON = ["longitude", "lon", "lng"]


def extrair_coordenadas_rastreio(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Extrai os arrays numpy de latitude/longitude do log de rastreio da
    placa. Aceita tanto o schema "bruto" quanto variações de nome de coluna
    já usadas no restante do sistema."""
    working = normalize_columns(df.copy())
    col_lat = _resolver_coluna_flex(working, _ALIASES_LAT)
    col_lon = _resolver_coluna_flex(working, _ALIASES_LON)

    if not col_lat or not col_lon:
        return np.array([]), np.array([])

    lat = pd.to_numeric(
        working[col_lat].astype(str).str.replace(",", ".", regex=False), errors="coerce"
    ).to_numpy(dtype=float)
    lon = pd.to_numeric(
        working[col_lon].astype(str).str.replace(",", ".", regex=False), errors="coerce"
    ).to_numpy(dtype=float)

    mask_validos = ~(np.isnan(lat) | np.isnan(lon))
    return lat[mask_validos], lon[mask_validos]


def cruzar_entregas_com_rastreio(
    pontos_geocodificados: list[dict[str, Any]],
    lat_rastreio: np.ndarray,
    lon_rastreio: np.ndarray,
    tolerancia_m: float = 50.0,
) -> list[dict[str, Any]]:
    """Classifica cada ponto de entrega como executado (o veículo passou a
    até `tolerancia_m` metros do ponto, segundo o log de rastreio) ou não
    executado. Vetorizado com numpy (haversine), no mesmo padrão já usado em
    analisador_rastreio.py, para performance em bases grandes."""
    resultado: list[dict[str, Any]] = []

    tem_rastreio = lat_rastreio.size > 0
    lat_rastreio_rad = np.radians(lat_rastreio) if tem_rastreio else np.array([])
    lon_rastreio_rad = np.radians(lon_rastreio) if tem_rastreio else np.array([])
    R = 6371000.0

    for ponto in pontos_geocodificados:
        ponto = dict(ponto)

        if not ponto.get("geocodificado"):
            ponto["status"] = "sem_geolocalizacao"
            ponto["distancia_m"] = None
            resultado.append(ponto)
            continue

        if not tem_rastreio:
            ponto["status"] = "sem_rastreio"
            ponto["distancia_m"] = None
            resultado.append(ponto)
            continue

        lat_rad = math.radians(ponto["latitude"])
        lon_rad = math.radians(ponto["longitude"])
        dphi = lat_rastreio_rad - lat_rad
        dlambda = lon_rastreio_rad - lon_rad
        a = (
            np.sin(dphi / 2.0) ** 2
            + math.cos(lat_rad) * np.cos(lat_rastreio_rad) * np.sin(dlambda / 2.0) ** 2
        )
        distancias = 2 * R * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
        menor_distancia = float(np.min(distancias))

        ponto["distancia_m"] = round(menor_distancia, 1)
        ponto["status"] = "executado" if menor_distancia <= tolerancia_m else "nao_executado"
        resultado.append(ponto)

    return resultado


_ALIASES_PLACA_RASTREIO = ["placa", "veiculo", "plate"]


def filtrar_rastreio_por_placa(df: pd.DataFrame, placa: str) -> pd.DataFrame:
    """Filtra o log de rastreio pela placa selecionada, se houver coluna de
    placa disponível; caso contrário assume que o arquivo já é específico
    dessa placa e retorna sem alterações."""
    working = normalize_columns(df.copy())
    col_placa = _resolver_coluna_flex(working, _ALIASES_PLACA_RASTREIO)
    if not col_placa or not placa:
        return df
    placa_norm = str(placa).strip().upper()
    mask = working[col_placa].astype(str).str.strip().str.upper() == placa_norm
    filtrado = df[mask.to_numpy()]
    return filtrado if not filtrado.empty else df


def calcular_estatisticas(pontos_classificados: list[dict[str, Any]]) -> dict[str, Any]:
    """Gera as estatísticas operacionais da auditoria: planejado x executado."""
    total = len(pontos_classificados)
    executados = [p for p in pontos_classificados if p["status"] == "executado"]
    nao_executados = [p for p in pontos_classificados if p["status"] == "nao_executado"]
    sem_geo = [p for p in pontos_classificados if p["status"] == "sem_geolocalizacao"]
    sem_rastreio = [p for p in pontos_classificados if p["status"] == "sem_rastreio"]

    total_avaliavel = len(executados) + len(nao_executados)
    percentual_execucao = round((len(executados) / total_avaliavel) * 100, 1) if total_avaliavel else 0.0

    return {
        "total_planejado": total,
        "total_executado": len(executados),
        "total_nao_executado": len(nao_executados),
        "total_sem_geolocalizacao": len(sem_geo),
        "total_sem_rastreio": len(sem_rastreio),
        "percentual_execucao": percentual_execucao,
        "clientes_nao_executados": [p["cliente"] for p in nao_executados],
    }


def executar_auditoria(
    df_carregamento: pd.DataFrame,
    df_rastreio: pd.DataFrame,
    placa: str,
    pois_cadastrados: list[dict[str, Any]],
    tolerancia_m: float = 50.0,
) -> dict[str, Any]:
    """Orquestra o pipeline completo da Auditoria de Roteiro:
    parse -> filtro por placa -> deduplicação -> geocodificação -> matching
    de proximidade -> estatísticas. Retorna um dicionário pronto para ser
    usado pela rota Flask e pelo resumo executivo de IA."""
    carregamento = parse_carregamento(df_carregamento)
    carregamento_da_placa = filtrar_por_placa(carregamento, placa)
    pontos_unicos = deduplicar_pontos_entrega(carregamento_da_placa)
    pontos_geocodificados = geocodificar_pontos(pontos_unicos, pois_cadastrados)

    rastreio_da_placa = filtrar_rastreio_por_placa(df_rastreio, placa)
    lat_rastreio, lon_rastreio = extrair_coordenadas_rastreio(rastreio_da_placa)

    pontos_classificados = cruzar_entregas_com_rastreio(
        pontos_geocodificados, lat_rastreio, lon_rastreio, tolerancia_m
    )
    estatisticas = calcular_estatisticas(pontos_classificados)

    return {
        "placa": placa,
        "tolerancia_m": tolerancia_m,
        "pontos": pontos_classificados,
        "estatisticas": estatisticas,
    }
