"""Regras da mensagem de saídas e montagem do texto (spec §6 e §7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from mensagem_saidas.constantes import MIN_CD_MIN, MIN_DESCONHECIDO_CONFERIR_MIN, MIN_POSTO_MIN, ORIGEM_CONFIAVEL_MIN
from mensagem_saidas.locais import Local
from mensagem_saidas.paradas import Parada, detectar_paradas, veio_em_movimento

MOTIVOS = {
    "local_desconhecido": "Parada sem local cadastrado",
    "em_movimento_no_inicio": "Já estava em movimento no início da planilha (a saída pode ter sido antes)",
    "sem_paradas": "Em movimento durante todo o período, sem nenhuma parada",
}


@dataclass
class ItemConferir:
    placa: str
    motivo: str
    parada: Parada | None
    chave: str

    @property
    def descricao(self) -> str:
        return MOTIVOS[self.motivo]


@dataclass
class ResultadoMensagem:
    texto: str
    conferir: list[ItemConferir] = field(default_factory=list)
    data_mensagem: date | None = None
    aviso_periodo: str | None = None


def _hora(dt: datetime, data_mensagem: date) -> str:
    texto = f"{dt:%H:%M}"
    dias = (data_mensagem - dt.date()).days
    if dias == 1:
        return f"{texto} de ontem"
    if dias > 1:
        return f"{texto} de {dt:%d/%m}"
    return texto


def _onde(p: Parada) -> tuple[str, str, str]:
    """(artigo 'de', artigo 'em', nome) — local cadastrado ou 'Cidade UF'."""
    if p.local is not None:
        return p.local.art_de, p.local.art_em, p.local.nome_exibicao
    nome = f"{p.cidade} {p.uf}".strip() or "local não identificado"
    return "de", "em", nome


def _entra_na_mensagem(p: Parada, local: Local) -> bool:
    if local.tipo == "MATRIZ":
        return True
    if local.tipo == "CD":
        return p.em_andamento or p.duracao_min >= MIN_CD_MIN
    if local.tipo in ("POSTO", "RESTAURANTE"):
        return p.duracao_min >= MIN_POSTO_MIN
    return False


def _item(placa: str, motivo: str, parada: Parada | None, momento: datetime) -> ItemConferir:
    return ItemConferir(placa, motivo, parada, f"{placa}|{motivo}|{momento:%Y%m%d%H%M}")


def _frases_da_placa(placa: str, regs: pd.DataFrame, locais: list[Local], data_msg: date) -> tuple[str, list[ItemConferir]]:
    paradas = detectar_paradas(regs, locais)
    if not paradas:
        return f"{placa}: Em trânsito.", [_item(placa, "sem_paradas", None, regs["data_hora"].min())]

    itens: list[ItemConferir] = []
    origem = paradas[0]
    if veio_em_movimento(regs) and origem.duracao_min < ORIGEM_CONFIAVEL_MIN:
        itens.append(_item(placa, "em_movimento_no_inicio", origem, origem.inicio))
    if origem.local is None:
        itens.append(_item(placa, "local_desconhecido", origem, origem.inicio))

    de, em, nome = _onde(origem)
    if origem.saida is not None:
        frases = [f"Saída {de} {nome} as {_hora(origem.saida, data_msg)}."]
    else:
        frases = [f"Está {em} {nome}."]

    for p in paradas[1:]:
        if p.local is None:
            if p.duracao_min >= MIN_DESCONHECIDO_CONFERIR_MIN:
                itens.append(_item(placa, "local_desconhecido", p, p.inicio))
            continue
        if not _entra_na_mensagem(p, p.local):
            continue
        frase = f"Chegada {p.local.art_em} {p.local.nome_exibicao} as {_hora(p.chegada, data_msg)}"
        if p.saida is not None:
            frase += f" e saiu as {_hora(p.saida, data_msg)}"
        frases.append(frase + ".")
    return f"{placa}: " + " ".join(frases), itens


def montar_mensagem(df: pd.DataFrame, locais: list[Local], ignorar: set[str] | frozenset[str] = frozenset()) -> ResultadoMensagem:
    """Monta a mensagem do WhatsApp a partir dos registros lidos por `ler_exportacao_ss`."""
    if df.empty:
        return ResultadoMensagem(texto="", conferir=[], data_mensagem=None, aviso_periodo="A planilha não tem registros.")

    inicio, fim = df["data_hora"].min(), df["data_hora"].max()
    data_msg = fim.date()
    aviso = None
    if inicio.date() == data_msg:
        aviso = (f"A planilha começa em {inicio:%d/%m} às {inicio:%H:%M}: saídas da véspera não aparecem. "
                 "Exporte a partir das 18:00 do dia anterior.")

    linhas: list[str] = []
    conferir: list[ItemConferir] = []
    for placa in sorted(df["placa"].unique()):
        linha, itens = _frases_da_placa(placa, df[df["placa"] == placa], locais, data_msg)
        linhas.append(linha)
        conferir.extend(i for i in itens if i.chave not in ignorar)

    texto = f"*Horário de saída das Carretas {data_msg:%d/%m/%Y}*\n\n" + "\n\n".join(linhas)
    return ResultadoMensagem(texto=texto, conferir=conferir, data_mensagem=data_msg, aviso_periodo=aviso)
