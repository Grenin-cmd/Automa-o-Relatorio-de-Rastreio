"""Excel com os pontos sem cadastro, para o aprendiz cadastrar na plataforma da SS."""
from __future__ import annotations

from io import BytesIO

import pandas as pd

from mensagem_saidas.constantes import RAIO_PADRAO_M
from mensagem_saidas.locais import Local
from mensagem_saidas.regras import ItemConferir

COLUNAS = ["Placa", "Início", "Fim", "Duração (min)", "Nome sugerido", "Tipo", "Endereço", "Cidade", "UF",
           "Latitude", "Longitude", "Link Google Maps", "POI SS mais próximo", "Distância POI SS (m)",
           "Raio sugerido (m)", "Cadastrado na SS"]


def _link(lat: float | None, lon: float | None) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}" if lat is not None and lon is not None else ""


def gerar_excel_pontos(
    itens: list[ItemConferir],
    sugestoes: dict[str, str | None],
    locais_pendentes: list[Local] | tuple[Local, ...] = (),
) -> bytes:
    """Pontos sem cadastro da lista Conferir + locais já cadastrados no sistema que ainda
    não estão na SS (`cadastrado_na_ss = não`), com o nome e tipo escolhidos."""
    linhas = []
    for local in locais_pendentes:
        linhas.append([
            "", "", "", "", local.nome_exibicao, local.tipo, "", "", "", local.latitude, local.longitude,
            _link(local.latitude, local.longitude), ", ".join(local.aliases_ss), None, local.raio_m, "",
        ])
    for item in itens:
        p = item.parada
        if item.motivo != "local_desconhecido" or p is None:
            continue
        fim = p.saida or p.fim
        link = _link(p.lat, p.lon)
        linhas.append([
            item.placa, f"{p.inicio:%d/%m/%Y %H:%M}", f"{fim:%d/%m/%Y %H:%M}", round(p.duracao_min),
            sugestoes.get(item.chave) or "", "", p.endereco, p.cidade, p.uf, p.lat, p.lon, link,
            p.poi_ss or "", p.poi_ss_dist_m, RAIO_PADRAO_M, "",
        ])
    saida = BytesIO()
    with pd.ExcelWriter(saida, engine="openpyxl") as writer:
        pd.DataFrame(linhas, columns=COLUNAS).to_excel(writer, index=False, sheet_name="Pontos sem cadastro")
    return saida.getvalue()
