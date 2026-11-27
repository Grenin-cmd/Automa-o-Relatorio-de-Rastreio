"""Cálculos geográficos (distâncias em metros entre coordenadas)."""
from __future__ import annotations

import math

import numpy as np

TAMANHO_BLOCO_DISTANCIAS = 256


def haversine_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre dois pontos (latitude/longitude em graus)."""
    lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    return r * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)))


def pontos_dentro_de_algum_poi(
    lats: np.ndarray,
    lons: np.ndarray,
    pois_lista: list[dict[str, object]],
    raio_tolerancia_m: float,
) -> np.ndarray | None:
    """Retorna, para cada ponto, se ele está dentro do raio de ao menos um POI.

    A matriz pontos × POIs é calculada em blocos de pontos: com ~17 mil POIs,
    a versão anterior alocava várias matrizes N×17000 de uma vez e podia
    passar de 1 GB de RAM em planilhas grandes. Cada bloco também descarta,
    por uma caixa de latitude, os POIs que não têm como estar no raio.
    Retorna None se não houver POI com coordenadas válidas."""
    poi_lat: list[float] = []
    poi_lon: list[float] = []
    poi_raio: list[float] = []
    for p in pois_lista:
        try:
            plat = float(str(p.get("latitude")).replace(",", "."))
            plon = float(str(p.get("longitude")).replace(",", "."))
            praio = float(str(p.get("raio_metros", 200.0)).replace(",", "."))
        except (ValueError, TypeError):
            continue
        if math.isnan(plat) or math.isnan(plon):
            continue
        poi_lat.append(plat)
        poi_lon.append(plon)
        poi_raio.append(max(praio, float(raio_tolerancia_m)))

    if not poi_lat:
        return None

    poi_lat_deg = np.array(poi_lat)
    poi_lat_rad = np.radians(poi_lat_deg)
    poi_lon_rad = np.radians(np.array(poi_lon))
    raios = np.array(poi_raio)
    # 1 grau de latitude ≈ 111 km; margem em graus para o maior raio cadastrado.
    margem_lat = float(raios.max()) / 111_000.0 + 1e-6

    resultado = np.zeros(len(lats), dtype=bool)
    validos = ~(np.isnan(lats) | np.isnan(lons))
    indices_validos = np.flatnonzero(validos)

    for inicio in range(0, len(indices_validos), TAMANHO_BLOCO_DISTANCIAS):
        idx = indices_validos[inicio:inicio + TAMANHO_BLOCO_DISTANCIAS]
        bloco_lat = lats[idx]
        candidatos = (poi_lat_deg >= bloco_lat.min() - margem_lat) & (poi_lat_deg <= bloco_lat.max() + margem_lat)
        if not candidatos.any():
            continue

        c_lat = poi_lat_rad[candidatos][None, :]
        c_lon = poi_lon_rad[candidatos][None, :]
        c_raio = raios[candidatos][None, :]
        r_lat = np.radians(bloco_lat)[:, None]
        r_lon = np.radians(lons[idx])[:, None]

        a = np.sin((c_lat - r_lat) / 2.0) ** 2 + np.cos(r_lat) * np.cos(c_lat) * np.sin((c_lon - r_lon) / 2.0) ** 2
        dist = 6371000.0 * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
        resultado[idx] = np.any(dist <= c_raio, axis=1)

    return resultado
