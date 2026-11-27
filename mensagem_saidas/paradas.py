"""Detecção de paradas de um veículo, com unificação de manobras (spec §5)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from geo import haversine_metros
from mensagem_saidas.constantes import MERGE_DIST_M, MERGE_MOVIMENTO_MIN, VEL_PARADO_KMH
from mensagem_saidas.locais import Local, normalizar_nome_poi, resolver_local


@dataclass
class Parada:
    placa: str
    inicio: datetime
    fim: datetime                 # último registro parado
    chegada: datetime             # primeiro registro parado dentro do local
    saida: datetime | None        # primeiro registro seguinte com velocidade > 3 km/h
    local: Local | None
    cidade: str
    uf: str
    endereco: str
    lat: float | None
    lon: float | None
    poi_ss: str | None
    poi_ss_dist_m: float | None
    em_andamento_no_inicio: bool

    @property
    def em_andamento(self) -> bool:
        return self.saida is None

    @property
    def duracao_min(self) -> float:
        fim = self.saida or self.fim
        return (fim - self.chegada).total_seconds() / 60.0


@dataclass
class _Trecho:
    regs: list[dict]
    saida: datetime | None
    local: Local | None
    reg_local: dict          # registro que define local/chegada (1º dentro de um local, senão o 1º)
    primeiro_do_veiculo: bool


def _coord(reg: dict) -> tuple[float, float] | None:
    lat, lon = reg.get("lat"), reg.get("lon")
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return None
    return float(lat), float(lon)


def _parado(reg: dict) -> bool:
    v = reg.get("velocidade_kmh")
    return v is not None and not pd.isna(v) and v <= VEL_PARADO_KMH


def veio_em_movimento(registros: pd.DataFrame) -> bool:
    """True se o primeiro registro do veículo já está em movimento (> 3 km/h)."""
    if registros.empty:
        return False
    return not _parado(registros.iloc[0].to_dict())


def _pode_unificar(atual: _Trecho, prox: _Trecho) -> bool:
    if atual.saida is None:
        return False
    movimento_min = (prox.regs[0]["data_hora"] - atual.saida).total_seconds() / 60.0
    if movimento_min > MERGE_MOVIMENTO_MIN:
        return False
    if atual.local and prox.local and atual.local.id != prox.local.id:
        return False
    a, b = _coord(atual.regs[-1]), _coord(prox.regs[0])
    if a and b:
        return haversine_metros(*a, *b) <= MERGE_DIST_M
    poi_a, poi_b = normalizar_nome_poi(atual.regs[-1].get("poi_ss")), normalizar_nome_poi(prox.regs[0].get("poi_ss"))
    return bool(poi_a) and poi_a == poi_b


def detectar_paradas(registros: pd.DataFrame, locais: list[Local]) -> list[Parada]:
    """Paradas de UM veículo, em ordem cronológica."""
    regs = [r for r in registros.sort_values("data_hora").to_dict("records")
            if r.get("velocidade_kmh") is not None and not pd.isna(r.get("velocidade_kmh"))]

    trechos: list[_Trecho] = []
    i = 0
    while i < len(regs):
        if not _parado(regs[i]):
            i += 1
            continue
        j = i
        while j + 1 < len(regs) and _parado(regs[j + 1]):
            j += 1
        bloco = regs[i:j + 1]
        local, reg_local = None, bloco[0]
        for r in bloco:
            achado = resolver_local(_coord(r)[0] if _coord(r) else None, _coord(r)[1] if _coord(r) else None,
                                    r.get("poi_ss"), r.get("poi_ss_dist_m"), locais)
            if achado:
                local, reg_local = achado, r
                break
        saida = regs[j + 1]["data_hora"] if j + 1 < len(regs) else None
        trechos.append(_Trecho(bloco, saida, local, reg_local, primeiro_do_veiculo=(i == 0)))
        i = j + 1

    unificados: list[_Trecho] = []
    for t in trechos:
        if unificados and _pode_unificar(unificados[-1], t):
            atual = unificados[-1]
            atual.regs.extend(t.regs)
            atual.saida = t.saida
            if atual.local is None and t.local is not None:
                atual.local, atual.reg_local = t.local, t.reg_local
        else:
            unificados.append(t)

    paradas = []
    for t in unificados:
        r = t.reg_local
        c = _coord(r)
        paradas.append(Parada(
            placa=str(r["placa"]), inicio=t.regs[0]["data_hora"], fim=t.regs[-1]["data_hora"],
            chegada=r["data_hora"], saida=t.saida, local=t.local,
            cidade=r.get("cidade") or "", uf=r.get("uf") or "", endereco=r.get("endereco") or "",
            lat=c[0] if c else None, lon=c[1] if c else None,
            poi_ss=r.get("poi_ss"), poi_ss_dist_m=r.get("poi_ss_dist_m"),
            em_andamento_no_inicio=t.primeiro_do_veiculo,
        ))
    return paradas
