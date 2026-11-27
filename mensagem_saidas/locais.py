"""Locais importantes (cadastro do usuário) e identificação do local de um registro."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from geo import haversine_metros

TIPOS = ("MATRIZ", "CD", "POSTO", "RESTAURANTE", "CLIENTE", "OUTRO")


@dataclass(frozen=True)
class Local:
    id: str
    nome_exibicao: str
    genero: str            # "o" ou "a"
    tipo: str              # um de TIPOS
    aliases_ss: tuple[str, ...]
    latitude: float | None
    longitude: float | None
    raio_m: float
    cadastrado_na_ss: bool

    @property
    def art_de(self) -> str:
        return "da" if self.genero == "a" else "do"

    @property
    def art_em(self) -> str:
        return "na" if self.genero == "a" else "no"


def normalizar_nome_poi(nome: str | None) -> str:
    """Maiúsculas, sem acento e com espaços colapsados (para comparar nomes de POI)."""
    if not nome:
        return ""
    texto = unicodedata.normalize("NFKD", str(nome))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return " ".join(texto.upper().split())


def resolver_local(
    lat: float | None,
    lon: float | None,
    poi_ss: str | None,
    poi_ss_dist_m: float | None,
    locais: list[Local],
) -> Local | None:
    """1º: local com coordenadas a <= raio (o mais próximo); 2º: local cujo alias é o POI
    da SS, com a distância informada pela SS <= raio. Senão, None."""
    if lat is not None and lon is not None and lat == lat and lon == lon:
        candidatos = []
        for local in locais:
            if local.latitude is None or local.longitude is None:
                continue
            dist = haversine_metros(lat, lon, local.latitude, local.longitude)
            if dist <= local.raio_m:
                candidatos.append((dist, local))
        if candidatos:
            return min(candidatos, key=lambda c: c[0])[1]

    chave = normalizar_nome_poi(poi_ss)
    if chave and poi_ss_dist_m is not None:
        for local in locais:
            if poi_ss_dist_m <= local.raio_m and any(normalizar_nome_poi(a) == chave for a in local.aliases_ss):
                return local
    return None
