"""Excel com os pontos sem POI, para o aprendiz cadastrar na plataforma da SS."""
from __future__ import annotations

from io import BytesIO

import pandas as pd

from mensagem_saidas.paradas import Parada

COLUNAS = ["Nome sugerido", "Latitude", "Longitude", "Link Google Maps"]


def chave_sugestao(lat: float, lon: float) -> str:
    return f"{lat:.5f},{lon:.5f}"


def gerar_excel_pontos(pontos: list[Parada], sugestoes: dict[str, str | None]) -> bytes:
    linhas, vistos = [], set()
    for p in pontos:
        if p.lat is None or p.lon is None:
            continue
        marca = (round(p.lat, 4), round(p.lon, 4))
        if marca in vistos:
            continue
        vistos.add(marca)
        linhas.append([sugestoes.get(chave_sugestao(p.lat, p.lon)) or "", p.lat, p.lon,
                       f"https://www.google.com/maps/search/?api=1&query={p.lat},{p.lon}"])
    saida = BytesIO()
    with pd.ExcelWriter(saida, engine="openpyxl") as writer:
        pd.DataFrame(linhas, columns=COLUNAS).to_excel(writer, index=False, sheet_name="Pontos sem POI")
    return saida.getvalue()
