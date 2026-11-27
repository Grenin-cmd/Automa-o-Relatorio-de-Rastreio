from __future__ import annotations

from typing import Any, cast
import pandas as pd

from geo import haversine_metros


# Mantido por compatibilidade: a implementação única fica em geo.py.
calcular_haversine = haversine_metros


def sanitizar_telemetria(
    df: pd.DataFrame,
    col_lat: str = "latitude",
    col_lon: str = "longitude",
    col_vel: str = "velocidade",
    col_data: str = "data_hora",
    limiar_vel_parado: float = 3.0,
    limiar_deslocamento_ruido_m: float = 25.0,
) -> pd.DataFrame:
    """
    Remove ruídos de GPS fixando a posição quando o veículo está essencialmente parado.
    """
    if df.empty:
        return df

    df_limpo = df.copy().sort_values(by=col_data).reset_index(drop=True)
    
    ultima_lat = cast(float, df_limpo.at[0, col_lat])
    ultima_lon = cast(float, df_limpo.at[0, col_lon])

    for i in range(1, len(df_limpo)):
        lat_atual = cast(float, df_limpo.at[i, col_lat])
        lon_atual = cast(float, df_limpo.at[i, col_lon])
        vel_atual = cast(float, df_limpo.at[i, col_vel])

        distancia = calcular_haversine(ultima_lat, ultima_lon, lat_atual, lon_atual)

        if float(vel_atual) <= limiar_vel_parado and distancia <= limiar_deslocamento_ruido_m:
            df_limpo.at[i, col_lat] = ultima_lat
            df_limpo.at[i, col_lon] = ultima_lon
        else:
            ultima_lat = lat_atual
            ultima_lon = lon_atual

    return df_limpo


def consolidar_falsas_saidas(
    eventos_paradas: list[dict[str, Any]],
    janela_tolerancia_min: int = 8,
    distancia_tolerancia_m: float = 150.0,
) -> list[dict[str, Any]]:
    """
    Funde eventos consecutivos no mesmo POI separados por micro-movimentações breves.
    """
    if not eventos_paradas:
        return []

    consolidados: list[dict[str, Any]] = [eventos_paradas[0]]

    for evento_atual in eventos_paradas[1:]:
        ultimo = consolidados[-1]

        mesmo_poi = (
            ultimo.get("poi_id") is not None
            and ultimo.get("poi_id") == evento_atual.get("poi_id")
        )

        fim_ultimo = pd.to_datetime(ultimo["data_fim"])
        inicio_atual = pd.to_datetime(evento_atual["data_inicio"])
        intervalo_min = (inicio_atual - fim_ultimo).total_seconds() / 60.0

        dist = calcular_haversine(
            float(ultimo["latitude"]),
            float(ultimo["longitude"]),
            float(evento_atual["latitude"]),
            float(evento_atual["longitude"]),
        )

        if (
            mesmo_poi
            and intervalo_min <= janela_tolerancia_min
            and dist <= distancia_tolerancia_m
        ):
            ultimo["data_fim"] = evento_atual["data_fim"]
            duracao = (pd.to_datetime(ultimo["data_fim"]) - pd.to_datetime(ultimo["data_inicio"])).total_seconds() / 60.0
            ultimo["duracao_min"] = duracao
            ultimo["observacao_pre_filtro"] = "Micro-movimentação interna unificada pelo pré-filtro geométrico."
        else:
            consolidados.append(evento_atual)

    return consolidados