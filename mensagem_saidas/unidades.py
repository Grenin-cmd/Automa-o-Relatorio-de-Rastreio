"""Locais fixos da mensagem (unidades da empresa e destinos frequentes) e
nomes/tipos derivados do POI da SS para todo o resto (spec v2 §2, opção B)."""
from __future__ import annotations

import re

from mensagem_saidas.constantes import RAIO_PADRAO_M
from mensagem_saidas.locais import Local, normalizar_nome_poi

# (nome na mensagem, gênero, tipo, nomes do POI na SS, latitude, longitude, raio)
_FIXOS = [
    ("Matriz", "a", "MATRIZ", ["CECOTI MATRIZ", "CAMARA FRIA MATRIZ"], None, None, 250),
    ("CD de Contagem", "o", "CD", ["CECOTI CD CONTAGEM"], None, None, 150),
    ("CD de Uberlândia", "o", "CD", ["CECOTI CD UBERLANDIA"], None, None, 250),
    ("CD Supermercados BH em Contagem MG", "o", "CD", ["CD Mart Minas Contagem"], None, None, 300),
    ("CD Supermercado BH em Contagem MG", "o", "CD", ["CD SUPERMERCADO BH"], None, None, 250),
    ("Fontini em São Francisco de Paula MG", "a", "CD", ["FONTINI AGILMAX SFP"], None, None, 250),
    ("CEMA Central Mineira Atacadista em Ribeirão das Neves", "a", "CD", ["CEMA CENTRAL MINEIRA ATACADISTA"], None, None, 250),
    ("Cemil em Patos de Minas MG", "a", "CLIENTE", ["CEMIL"], None, None, 250),
    ("Posto Caxuxa na BR-262 em Luz MG", "o", "POSTO", ["POSTO CAXUXA LUZ BR-262 EM LUZ", "RESTAURANTE CAXUXA"], None, None, 250),
    ("Restaurante Ponto do Peixe em Nova Serrana MG", "o", "RESTAURANTE", ["RESTAURANTE PONTO DO PEIXE"], None, None, 250),
    ("Posto Dom Pedro na SP-065 em Atibaia SP", "o", "POSTO", [], -23.10011, -46.60962, 300),
]

LOCAIS: list[Local] = [
    Local(id=f"u:{i}", nome_exibicao=n, genero=g, tipo=t, aliases_ss=tuple(a), latitude=la, longitude=lo,
          raio_m=float(r), cadastrado_na_ss=bool(a))
    for i, (n, g, t, a, la, lo, r) in enumerate(_FIXOS)
]

_MINUSCULAS = {"em", "de", "da", "do", "das", "dos", "e", "na", "no", "nas", "nos", "a", "o"}
_UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
        "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
_SIGLAS = _UFS | {"CD", "BR", "II", "III", "IV", "LTDA", "ME", "SA"}


def _palavra(p: str, primeira: bool) -> str:
    if not p:
        return p
    if p != p.upper():               # já tem minúsculas: respeita como veio
        return p
    if any(ch.isdigit() for ch in p) or "." in p or p in _SIGLAS:
        return p
    minusc = p.lower()
    if minusc in _MINUSCULAS and not primeira:
        return minusc
    return minusc[:1].upper() + minusc[1:]


def formatar_nome_ss(nome: str) -> str:
    """'POSTO JALÉ BR-262 EM ARAÚJOS' -> 'Posto Jalé BR-262 em Araújos' (siglas e números mantidos).
    Partes separadas por '/', '(' ou ')' são tratadas uma a uma: 'LUZIA/MG' -> 'Luzia/MG'."""
    texto = " ".join(str(nome).split())
    partes = re.split(r"([\s/()]+)", texto)
    saida, primeira = [], True
    for parte in partes:
        if not parte or re.fullmatch(r"[\s/()]+", parte):
            saida.append(parte)
            continue
        saida.append(_palavra(parte, primeira))
        primeira = False
    return "".join(saida)


def tipo_por_nome(nome: str) -> str:
    n = normalizar_nome_poi(nome)
    palavras = set(re.split(r"[\s\-/]+", n))
    if n.startswith("CD ") or "CD" in palavras:
        return "CD"
    if "MATRIZ" in palavras:
        return "MATRIZ"
    if "POSTO" in palavras or n.startswith("P.S.") or n.startswith("PS "):
        return "POSTO"
    if palavras & {"RESTAURANTE", "CHURRASCARIA", "LANCHONETE"}:
        return "RESTAURANTE"
    return "OUTRO"


def local_da_ss(poi_ss: str) -> Local:
    """Local derivado de um POI da SS que não está na lista fixa."""
    chave = normalizar_nome_poi(poi_ss)
    return Local(id=f"ss:{chave}", nome_exibicao=formatar_nome_ss(poi_ss), genero="o", tipo=tipo_por_nome(poi_ss),
                 aliases_ss=(poi_ss,), latitude=None, longitude=None, raio_m=float(RAIO_PADRAO_M), cadastrado_na_ss=True)
