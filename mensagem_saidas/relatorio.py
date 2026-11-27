"""Excel com os pontos sem cadastro, para o aprendiz cadastrar na plataforma da SS."""
from __future__ import annotations

from io import BytesIO

import pandas as pd

from mensagem_saidas.constantes import RAIO_PADRAO_M
from mensagem_saidas.regras import ItemConferir

COLUNAS = ["Placa", "Início", "Fim", "Duração (min)", "Nome sugerido", "Tipo", "Endereço", "Cidade", "UF",
           "Latitude", "Longitude", "Link Google Maps", "POI SS mais próximo", "Distância POI SS (m)",
           "Raio sugerido (m)", "Cadastrado na SS"]


def gerar_excel_pontos(itens: list[ItemConferir], sugestoes: dict[str, str | None]) -> bytes:
    linhas = []
    for item in itens:
        p = item.parada
        if item.motivo != "local_desconhecido" or p is None:
            continue
        fim = p.saida or p.fim
        link = f"https://www.google.com/maps/search/?api=1&query={p.lat},{p.lon}" if p.lat is not None else ""
        linhas.append([
            item.placa, f"{p.inicio:%d/%m/%Y %H:%M}", f"{fim:%d/%m/%Y %H:%M}", round(p.duracao_min),
            sugestoes.get(item.chave) or "", "", p.endereco, p.cidade, p.uf, p.lat, p.lon, link,
            p.poi_ss or "", p.poi_ss_dist_m, RAIO_PADRAO_M, "",
        ])
    saida = BytesIO()
    with pd.ExcelWriter(saida, engine="openpyxl") as writer:
        pd.DataFrame(linhas, columns=COLUNAS).to_excel(writer, index=False, sheet_name="Pontos sem cadastro")
    return saida.getvalue()
