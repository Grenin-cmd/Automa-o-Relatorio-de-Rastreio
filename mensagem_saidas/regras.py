"""Regras da Mensagem do dia (spec v1 §6 e v2 §2): linhas por placa, situações,
números do topo e pontos sem POI."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd

from mensagem_saidas.constantes import MIN_CD_MIN, MIN_DESCONHECIDO_CONFERIR_MIN, MIN_POSTO_MIN
from mensagem_saidas.locais import Local
from mensagem_saidas.paradas import Parada, detectar_paradas

HORA_CORTE = time(21, 0)  # registros antes das 21:00 do dia anterior são descartados


@dataclass
class ResultadoMensagem:
    data_mensagem: date | None
    linhas: dict[str, str] = field(default_factory=dict)       # placa -> texto após "PLACA: "
    situacoes: dict[str, str] = field(default_factory=dict)    # placa -> "Saiu 05:41", "Parado"…
    pontos_sem_poi: list[Parada] = field(default_factory=list)
    aviso_periodo: str | None = None
    totais: dict[str, int] = field(default_factory=dict)

    @property
    def texto(self) -> str:
        return montar_texto(self.data_mensagem, self.linhas) if self.data_mensagem else ""


def montar_texto(data: date, linhas: dict[str, str], edicoes: dict[str, str] | None = None) -> str:
    edicoes = edicoes or {}
    corpo = "\n\n".join(f"{placa}: {edicoes.get(placa, texto).strip()}" for placa, texto in linhas.items())
    return f"*Horário de saída das Carretas {data:%d/%m/%Y}*\n\n{corpo}"


def _hora(dt: datetime, data_mensagem: date) -> str:
    texto = f"{dt:%H:%M}"
    dias = (data_mensagem - dt.date()).days
    if dias == 1:
        return f"{texto} de ontem"
    if dias > 1:
        return f"{texto} de {dt:%d/%m}"
    return texto


def _onde(p: Parada) -> tuple[str, str, str]:
    if p.local is not None:
        return p.local.art_de, p.local.art_em, p.local.nome_exibicao
    return "de", "em", f"{p.cidade} {p.uf}".strip() or "local não identificado"


def _entra_na_mensagem(p: Parada, local: Local) -> bool:
    if local.tipo == "MATRIZ":
        return True
    if local.tipo == "CD":
        return p.em_andamento or p.duracao_min >= MIN_CD_MIN
    if local.tipo in ("POSTO", "RESTAURANTE"):
        return p.duracao_min >= MIN_POSTO_MIN
    return False


_ROTULO_TIPO = {"MATRIZ": "Na Matriz", "CD": "No CD", "POSTO": "No posto", "RESTAURANTE": "No restaurante"}


def _placa(regs: pd.DataFrame, locais: list[Local], data_msg: date) -> tuple[str, str, list[Parada], bool | None]:
    """(linha, situação, paradas sem POI, saiu?) de um veículo."""
    paradas = detectar_paradas(regs, locais)
    if not paradas:
        return "Em trânsito.", "Em trânsito", [], None

    sem_poi = [p for p in paradas if p.local is None and p.duracao_min >= MIN_DESCONHECIDO_CONFERIR_MIN]
    origem = paradas[0]
    de, em, nome = _onde(origem)
    if origem.saida is None:
        return f"Está {em} {nome}.", "Parado", sem_poi, False

    frases = [f"Saída {de} {nome} as {_hora(origem.saida, data_msg)}."]
    situacao = f"Saiu {_hora(origem.saida, data_msg)}"
    for p in paradas[1:]:
        if p.local is None or not _entra_na_mensagem(p, p.local):
            continue
        frase = f"Chegada {p.local.art_em} {p.local.nome_exibicao} as {_hora(p.chegada, data_msg)}"
        if p.saida is not None:
            frase += f" e saiu as {_hora(p.saida, data_msg)}"
            situacao = f"Saiu {_hora(p.saida, data_msg)}"
        else:
            situacao = f"{_ROTULO_TIPO.get(p.local.tipo, 'Chegou')} {_hora(p.chegada, data_msg)}"
        frases.append(frase + ".")
    return " ".join(frases), situacao, sem_poi, True


def montar_mensagem(df: pd.DataFrame, locais: list[Local]) -> ResultadoMensagem:
    if df.empty:
        return ResultadoMensagem(data_mensagem=None, aviso_periodo="A planilha não tem registros.")

    data_msg = df["data_hora"].max().date()
    corte = datetime.combine(data_msg - timedelta(days=1), HORA_CORTE)
    df = df[df["data_hora"] >= corte]
    inicio = df["data_hora"].min()
    aviso = None
    if inicio > corte + timedelta(minutes=30):
        aviso = (f"A planilha começa em {inicio:%d/%m} às {inicio:%H:%M}; saídas antes disso podem faltar "
                 "(o ideal é exportar a partir das 21:00 do dia anterior).")

    res = ResultadoMensagem(data_mensagem=data_msg, aviso_periodo=aviso)
    sairam = parados = 0
    for placa in sorted(df["placa"].unique()):
        linha, situacao, sem_poi, saiu = _placa(df[df["placa"] == placa], locais, data_msg)
        res.linhas[placa] = linha
        res.situacoes[placa] = situacao
        res.pontos_sem_poi.extend(sem_poi)
        sairam += saiu is True
        parados += saiu is False
    res.totais = {"veiculos": len(res.linhas), "sairam": sairam, "parados": parados, "sem_poi": len(res.pontos_sem_poi)}
    return res
