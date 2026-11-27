"""Sugestão de nome para um ponto sem cadastro, via OpenStreetMap (Overpass API).

A sugestão nunca entra na mensagem sem o usuário aceitar. Falhas de rede
retornam None — a tela continua funcionando sem sugestão.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable

from geo import haversine_metros
from mensagem_saidas.constantes import RAIO_SUGESTAO_M

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Automacao-Relatorio-Rastreio/1.0"
_CACHE: dict[tuple[float, float], str | None] = {}


def _consulta(lat: float, lon: float) -> str:
    perto = f"(around:{RAIO_SUGESTAO_M},{lat},{lon})"
    filtros = ['["amenity"~"fuel|restaurant|fast_food|cafe"]', '["shop"]', '["office"]', '["industrial"]', '["landuse"="industrial"]']
    corpo = "".join(f'nwr{perto}["name"]{f};' for f in filtros)
    return f"[out:json][timeout:5];({corpo});out center tags 30;"


def _buscar_overpass(consulta: str, timeout_s: float) -> bytes:
    dados = urllib.parse.urlencode({"data": consulta}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=dados, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (URL fixa)
        return resp.read()


def sugerir_nome(
    lat: float,
    lon: float,
    *,
    buscar: Callable[[str], bytes] | None = None,
    timeout_s: float = 4.0,
) -> str | None:
    """Nome do lugar com nome mais próximo (preferindo postos) num raio de 300 m."""
    chave = (round(lat, 4), round(lon, 4))
    if chave in _CACHE:
        return _CACHE[chave]
    try:
        bruto = (buscar or (lambda q: _buscar_overpass(q, timeout_s)))(_consulta(lat, lon))
        elementos = json.loads(bruto).get("elements", [])
    except Exception:
        return None  # não guarda no cache: pode ter sido uma falha temporária

    candidatos = []
    for el in elementos:
        tags = el.get("tags") or {}
        nome = tags.get("name")
        pos = el if "lat" in el else el.get("center") or {}
        if not nome or "lat" not in pos:
            continue
        dist = haversine_metros(lat, lon, pos["lat"], pos["lon"])
        candidatos.append((tags.get("amenity") != "fuel", dist, nome))
    resultado = min(candidatos)[2] if candidatos else None
    _CACHE[chave] = resultado
    return resultado
