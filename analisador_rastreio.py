from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

import math
import os
import re
import unicodedata
import pandas as pd


_UFS_POR_NOME = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}


def _normalizar_texto_simples(texto: str) -> str:
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


def _extrair_rodovia(endereco: str | None) -> str:
    """Acha algo tipo 'BR-381' ou 'MG-050' dentro do texto do endereço."""
    if not endereco or not isinstance(endereco, str):
        return ""
    match = re.search(r"\b([A-Z]{2}-\d{2,3})\b", endereco.upper())
    return match.group(1) if match else ""


def _extrair_cidade_estado(endereco: str | None) -> tuple[str, str]:
    """Extrai cidade e UF de endereços em qualquer um destes formatos:
    - 'Rua X, 123 - Bairro, São Gonçalo - MG' (sigla no final)
    - 'Rua X - Bairro - Contagem - Minas Gerais - Brasil' (nome do estado
      por extenso, com 'Brasil' no final — formato real da plataforma)."""
    if not endereco or not isinstance(endereco, str):
        return "", ""
    texto = re.sub(r"[\s,\-]*Brasil\s*$", "", endereco.strip(), flags=re.IGNORECASE).strip()
    partes = [p.strip() for p in texto.split(" - ") if p.strip()]

    for i in range(len(partes) - 1, -1, -1):
        segmento = partes[i]
        chave = _normalizar_texto_simples(segmento)
        if chave in _UFS_POR_NOME:
            estado = _UFS_POR_NOME[chave]
            cidade = partes[i - 1] if i > 0 else ""
            cidade = cidade.split(",")[-1].strip()
            return cidade, estado
        if re.fullmatch(r"[A-Z]{2}", segmento):
            estado = segmento
            cidade = partes[i - 1] if i > 0 else ""
            cidade = cidade.split(",")[-1].strip()
            return cidade, estado

    return "", ""


def _parse_velocidade(series: pd.Series) -> pd.Series:
    """Converte velocidade em texto (ex: '37 km/h', '105,5') para número.
    Extrai só a parte numérica, ignorando a unidade, e aceita tanto vírgula
    quanto ponto como separador decimal."""
    extraida = series.astype(str).str.extract(r"(-?\d+(?:[.,]\d+)?)")[0]
    return pd.to_numeric(extraida.str.replace(",", ".", regex=False), errors="coerce")


@dataclass
class PontoInteresse:
    nome: str
    tipo: str
    latitude: float
    longitude: float
    raio_metros: float = 200.0
    tempo_parado_seg: int = 120
    velocidade_maxima_kmh: float = 10.0
    cidade: str = ""
    estado: str = ""
    rodovia: str = ""
    address: str = ""
    search_query: str = ""


class RastreamentoAnalyzer:
    def __init__(self, pois: List[Dict[str, Any]], velocidade_limite_kmh: float = 10.0, tempo_parado_seg: int = 120):
        campos_validos = set(PontoInteresse.__dataclass_fields__.keys())
        self.pois = [
            PontoInteresse(**{k: v for k, v in poi.items() if k in campos_validos})
            for poi in pois
        ]
        self.velocidade_limite_kmh = velocidade_limite_kmh
        self.tempo_parado_seg = tempo_parado_seg

        # Com listas grandes de POIs (importação com milhares de linhas), um
        # scan linear a cada parada fica lento — monta um dicionário de
        # lookup por nome (normalizado) uma única vez aqui. Guarda TODOS os
        # POIs com o mesmo nome (ex: uma rede com várias unidades), porque
        # sobrescrever um pelo outro perdia a localização certa em silêncio.
        self._pois_por_chave: Dict[str, List[PontoInteresse]] = {}
        for poi in self.pois:
            chave = self._poi_key(poi.nome)
            if chave:
                self._pois_por_chave.setdefault(chave, []).append(poi)

    def _distancia_metros(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _normalize_column_name(self, name: str) -> str:
        name = str(name).strip().lower()
        name = unicodedata.normalize("NFKD", name)
        name = "".join(ch for ch in name if not unicodedata.combining(ch))
        name = name.replace(" ", "_")
        name = name.replace("/", "_")
        name = name.replace("-", "_")
        name = name.replace("(kmh)", "")
        name = name.replace("(km/h)", "")
        name = name.replace("kmh", "")
        name = name.replace("km_h", "")
        name = name.replace("ç", "c")
        name = name.replace("ã", "a")
        name = name.replace("á", "a")
        name = name.replace("é", "e")
        name = name.replace("í", "i")
        name = name.replace("ó", "o")
        name = name.replace("ú", "u")
        name = name.replace("à", "a")
        name = name.replace("õ", "o")
        name = name.replace("ç", "c")
        while "__" in name:
            name = name.replace("__", "_")
        return name.strip("_")

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [self._normalize_column_name(col) for col in df.columns]
        return df

    def _resolver_coluna(self, df: pd.DataFrame, aliases: List[str]) -> str:
        columns = [self._normalize_column_name(col) for col in df.columns]

        for alias in aliases:
            alias_norm = self._normalize_column_name(alias)
            for i, col in enumerate(columns):
                if alias_norm == col:
                    return df.columns[i]

        for alias in aliases:
            alias_norm = self._normalize_column_name(alias)
            candidates = []
            for i, col in enumerate(columns):
                if not col:
                    continue
                if alias_norm in col or col in alias_norm:
                    candidates.append((len(col), i))
            if candidates:
                _, best_index = max(candidates)
                return df.columns[best_index]

        raise ValueError(f"Coluna não encontrada. Esperava uma das opções: {aliases}")

    def _parse_google_link(self, url: str) -> tuple[float, float] | None:
        if not isinstance(url, str):
            return None
        if "q=" in url:
            try:
                latlon = url.split("q=")[1].split("&")[0]
                lat, lon = latlon.split(",")
                return float(lat), float(lon)
            except Exception:
                return None
        return None

    def _format_relative_time(self, timestamp: datetime | None, reference_date=None) -> str:
        if timestamp is None:
            return ""
        today = reference_date if reference_date is not None else datetime.now().date()
        if timestamp.date() == today:
            return timestamp.strftime("%H:%M")
        return timestamp.strftime("%H:%M de %d/%m/%Y")

    def _poi_key(self, poi_name: str | None) -> str:
        if not poi_name:
            return ""
        cleaned = str(poi_name).strip().lower()
        cleaned = unicodedata.normalize("NFKD", cleaned)
        cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
        if "matriz" in cleaned or "camara fria" in cleaned or "camarafria" in cleaned or "camera fria" in cleaned:
            return "matriz"
        return cleaned

    def _poi_label(self, poi_name: str | None) -> str:
        if self._poi_key(poi_name) == "matriz":
            return "Matriz"
        return str(poi_name).strip()

    def _localizar_poi_configurado(
        self, poi_key: str | None, cidade_hint: str | None = None, estado_hint: str | None = None
    ) -> PontoInteresse | None:
        """Casa o nome do POI que vem no CSV (ex: 'CECOTI MATRIZ') com um dos
        POIs cadastrados (importados pro banco ou digitados na tela), por
        nome. Quando existe mais de um POI com o mesmo nome (ex: uma rede
        com várias unidades), usa a cidade/estado extraídos do endereço da
        própria linha do rastreio pra escolher o certo, em vez de pegar
        qualquer um."""
        if not poi_key:
            return None
        candidatos = self._pois_por_chave.get(poi_key)
        if not candidatos:
            return None
        if len(candidatos) == 1:
            return candidatos[0]

        estado_hint_norm = (estado_hint or "").strip().upper()
        cidade_hint_norm = _normalizar_texto_simples(cidade_hint) if cidade_hint else ""

        if cidade_hint_norm and estado_hint_norm:
            for poi in candidatos:
                if poi.estado.strip().upper() == estado_hint_norm and _normalizar_texto_simples(poi.cidade) == cidade_hint_norm:
                    return poi
        if estado_hint_norm:
            for poi in candidatos:
                if poi.estado.strip().upper() == estado_hint_norm:
                    return poi
        if cidade_hint_norm:
            for poi in candidatos:
                if _normalizar_texto_simples(poi.cidade) == cidade_hint_norm:
                    return poi

        # Não deu pra desambiguar (endereço sem cidade/estado reconhecíveis
        # ou nenhum POI cadastrado bate com a cidade) — usa o primeiro como
        # antes, mas isso agora é só o último recurso, não a regra.
        return candidatos[0]

    def _label_com_localizacao(self, poi_key: str | None, label: str, endereco: str | None = None) -> str:
        """Acrescenta 'em Cidade UF' (e a rodovia, se tiver) ao lado do nome
        do POI. Prioriza o que dá pra extrair do endereço do próprio arquivo
        de rastreio (sempre disponível, por evento) e usa o POI cadastrado
        como reforço/alternativa quando o endereço não tem essa informação."""
        cidade, estado = _extrair_cidade_estado(endereco)
        rodovia = _extrair_rodovia(endereco)

        if not (cidade or estado or rodovia):
            configurado = self._localizar_poi_configurado(poi_key, cidade, estado)
            if configurado is not None:
                cidade = configurado.cidade
                estado = configurado.estado
                rodovia = configurado.rodovia

        texto = label
        if rodovia:
            texto = f"{texto} na {rodovia}"
        if cidade and estado:
            texto = f"{texto} em {cidade} {estado}"
        elif cidade:
            texto = f"{texto} em {cidade}"
        elif estado:
            texto = f"{texto} em {estado}"

        return texto

    def _has_plataforma_schema(self, df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            return False
        normalized_columns = [self._normalize_column_name(col) for col in df.columns]
        required = ["poi", "poi_distancia", "velocidade", "data"]
        return all(any(alias == col or alias in col or col in alias for col in normalized_columns) for alias in required)

    def _gerar_relatorio_plataforma(self, df: pd.DataFrame) -> str:
        if df is None or df.empty:
            return "Nenhum evento detectado."
        df = self._normalize_columns(df)
        timestamp_col: str = self._resolver_coluna(df, ["data", "timestamp", "data_hora", "datetime", "date_time", "horario"])
        poi_col: str = self._resolver_coluna(df, ["poi"])
        distance_col: str = self._resolver_coluna(df, ["poi_distancia", "poi_distância", "poi_-_distancia", "poi - distancia", "poi distancia"])
        speed_col: str = self._resolver_coluna(df, ["velocidade", "velocidade_kmh", "speed", "speed_kmh", "speed_km_h"])
        try:
            endereco_col: str | None = self._resolver_coluna(df, ["endereco", "address", "logradouro"])
        except ValueError:
            endereco_col = None

        df = df.copy()
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], dayfirst=True, errors="coerce")
        df[distance_col] = pd.to_numeric(df[distance_col], errors="coerce").fillna(9999)
        df[speed_col] = _parse_velocidade(df[speed_col]).fillna(0)
        df = df.dropna(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)

        if df.empty:
            return "Nenhum evento detectado."

        reference_date = df[timestamp_col].max().date()
        stops = self._construir_paradas_poi(df, poi_col, distance_col, speed_col, timestamp_col, endereco_col)

        last_poi = None
        last_poi_raw = None
        last_poi_time = None
        last_poi_inside = False
        last_stopped = False
        last_endereco = None
        if not df.empty:
            last_row = df.iloc[-1]
            last_poi_raw = str(last_row[poi_col]).strip() if pd.notna(last_row[poi_col]) else None
            last_poi = self._poi_key(last_poi_raw)
            last_stopped = float(last_row[speed_col]) <= self.velocidade_limite_kmh
            last_poi_inside = bool(last_poi) and float(last_row[distance_col]) <= 200 and last_stopped
            last_poi_time = last_row[timestamp_col] if last_poi_inside else None
            last_endereco = str(last_row[endereco_col]).strip() if endereco_col and pd.notna(last_row[endereco_col]) else None

        if not stops:
            if last_poi_inside:
                if last_poi == "matriz":
                    label_matriz = self._label_com_localizacao("matriz", "Matriz", last_endereco)
                    return f"Está na {label_matriz} desde {self._format_relative_time(last_poi_time, reference_date)}."
                label_atual = self._label_com_localizacao(last_poi, self._poi_label(last_poi_raw), last_endereco)
                return f"Está em {label_atual} desde {self._format_relative_time(last_poi_time, reference_date)}."
            if last_stopped:
                return f"Parada sem POI identificado desde {self._format_relative_time(last_row[timestamp_col], reference_date)}."
            return "Nenhum evento relevante detectado."

        lines = ["Relatório de rastreamento", "========================", ""]
        for stop in stops:
            label = self._label_com_localizacao(stop["poi"], stop.get("label") or self._poi_label(stop["poi"]), stop.get("endereco"))
            if stop["saida"] is None:
                if stop["poi"] == "matriz":
                    label_matriz = self._label_com_localizacao("matriz", "Matriz", stop.get("endereco"))
                    lines.append(f"Está na {label_matriz} desde {self._format_relative_time(stop['inicio'], reference_date)}.")
                else:
                    lines.append(f"Está em {label} desde {self._format_relative_time(stop['inicio'], reference_date)}.")
            else:
                lines.append(
                    f"Chegou no {label} às {self._format_relative_time(stop['inicio'], reference_date)} e saiu às {self._format_relative_time(stop['saida'], reference_date)}."
                )
        return "\n".join(lines)

    def _construir_paradas_poi(
        self,
        df: pd.DataFrame,
        poi_col: str,
        distance_col: str,
        speed_col: str,
        timestamp_col: str,
        endereco_col: str | None = None,
    ) -> List[Dict[str, Any]]:
        relevant_stop_sec = max(self.tempo_parado_seg, 600)
        stops: List[Dict[str, Any]] = []
        current_poi = None
        current_label = None
        current_endereco = None
        entry_start: datetime | None = None
        entry_end: datetime | None = None
        inside = False

        def finalize_stop(poi_key, poi_label, start, end, departure, endereco):
            if poi_key and start and end and (end - start).total_seconds() >= relevant_stop_sec:
                stops.append({"poi": poi_key, "label": poi_label or "", "inicio": start, "fim": end, "saida": departure, "endereco": endereco or ""})

        for _, row in df.iterrows():
            poi_raw = str(row[poi_col]).strip() if pd.notna(row[poi_col]) else ""
            poi_key = self._poi_key(poi_raw)
            poi_label = self._poi_label(poi_raw)
            is_near = row[distance_col] <= 200
            is_stopped = row[speed_col] <= self.velocidade_limite_kmh
            at_poi = bool(poi_key) and is_near and is_stopped
            current_time = row[timestamp_col]
            endereco_atual = str(row[endereco_col]).strip() if endereco_col and pd.notna(row[endereco_col]) else ""

            if at_poi and not inside:
                inside = True
                current_poi = poi_key
                current_label = poi_label
                current_endereco = endereco_atual
                entry_start = current_time
                entry_end = current_time
            elif at_poi and inside and poi_key == current_poi:
                entry_end = current_time
            elif at_poi and inside and poi_key != current_poi:
                finalize_stop(current_poi, current_label, entry_start, entry_end, current_time, current_endereco)
                current_poi = poi_key
                current_label = poi_label
                current_endereco = endereco_atual
                entry_start = current_time
                entry_end = current_time
            elif not at_poi and inside:
                finalize_stop(current_poi, current_label, entry_start, entry_end, current_time, current_endereco)
                inside = False
                current_poi = None
                current_label = None
                current_endereco = None
                entry_start = None
                entry_end = None

        if inside and entry_start and entry_end:
            if (entry_end - entry_start).total_seconds() >= relevant_stop_sec:
                stops.append({"poi": current_poi, "label": current_label or "", "inicio": entry_start, "fim": entry_end, "saida": None, "endereco": current_endereco or ""})

        return stops

    def detectar_excesso_velocidade(self, df: pd.DataFrame, limite_kmh: float) -> List[Dict[str, Any]]:
        if df is None or df.empty:
            return []

        df = self._normalize_columns(df)
        try:
            timestamp_col: str = self._resolver_coluna(df, ["data", "timestamp", "data_hora", "datetime", "date_time", "horario"])
            speed_col: str = self._resolver_coluna(df, ["velocidade", "velocidade_kmh", "speed", "speed_kmh", "speed_km_h"])
        except ValueError:
            return []

        df = df.copy()
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], dayfirst=True, errors="coerce")
        df[speed_col] = _parse_velocidade(df[speed_col]).fillna(0)
        df = df.dropna(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)

        eventos: List[Dict[str, Any]] = []
        inicio: datetime | None = None
        fim: datetime | None = None
        velocidade_maxima = 0.0

        for _, row in df.iterrows():
            velocidade = float(row[speed_col])
            current_time = row[timestamp_col]
            if velocidade > limite_kmh:
                if inicio is None:
                    inicio = current_time
                    velocidade_maxima = velocidade
                fim = current_time
                velocidade_maxima = max(velocidade_maxima, velocidade)
            else:
                if inicio is not None and fim is not None:
                    eventos.append({"inicio": inicio, "fim": fim, "velocidade_maxima": velocidade_maxima})
                inicio = None
                fim = None
                velocidade_maxima = 0.0

        if inicio is not None and fim is not None:
            eventos.append({"inicio": inicio, "fim": fim, "velocidade_maxima": velocidade_maxima})

        return eventos

    def gerar_eventos_viagem(self, df: pd.DataFrame, limite_velocidade_kmh: float = 95.0) -> List[Dict[str, Any]]:
        if not self._has_plataforma_schema(df) or df is None or df.empty:
            return []

        df_norm = self._normalize_columns(df.copy())
        timestamp_col: str = self._resolver_coluna(df_norm, ["data", "timestamp", "data_hora", "datetime", "date_time", "horario"])
        poi_col: str = self._resolver_coluna(df_norm, ["poi"])
        distance_col: str = self._resolver_coluna(df_norm, ["poi_distancia", "poi_distância", "poi_-_distancia", "poi - distancia", "poi distancia"])
        speed_col: str = self._resolver_coluna(df_norm, ["velocidade", "velocidade_kmh", "speed", "speed_kmh", "speed_km_h"])
        try:
            endereco_col: str | None = self._resolver_coluna(df_norm, ["endereco", "address", "logradouro"])
        except ValueError:
            endereco_col = None

        df_norm[timestamp_col] = pd.to_datetime(df_norm[timestamp_col], dayfirst=True, errors="coerce")
        df_norm[distance_col] = pd.to_numeric(df_norm[distance_col], errors="coerce").fillna(9999)
        df_norm[speed_col] = _parse_velocidade(df_norm[speed_col]).fillna(0)
        df_norm = df_norm.dropna(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)

        if df_norm.empty:
            return []

        stops = self._construir_paradas_poi(df_norm, poi_col, distance_col, speed_col, timestamp_col, endereco_col)
        excessos = self.detectar_excesso_velocidade(df, limite_velocidade_kmh)

        eventos: List[Dict[str, Any]] = []
        for stop in stops:
            label = self._label_com_localizacao(stop["poi"], stop.get("label") or self._poi_label(stop["poi"]), stop.get("endereco"))
            cidade_hint, estado_hint = _extrair_cidade_estado(stop.get("endereco"))
            configurado = self._localizar_poi_configurado(stop["poi"], cidade_hint, estado_hint)
            eventos.append(
                {
                    "tipo": "poi",
                    "local": label,
                    "inicio": stop["inicio"],
                    "fim": stop["saida"] if stop["saida"] is not None else stop["fim"],
                    "em_andamento": stop["saida"] is None,
                    "latitude": configurado.latitude if configurado else None,
                    "longitude": configurado.longitude if configurado else None,
                    "search_query": configurado.search_query if configurado else None,
                }
            )

        eventos.sort(key=lambda e: e["inicio"])
        return eventos

    def _ensure_coordinates(self, df: pd.DataFrame) -> pd.DataFrame:
        latitude_cols = [c for c in ["latitude", "lat"] if c in df.columns]
        longitude_cols = [c for c in ["longitude", "lon"] if c in df.columns]

        if latitude_cols and longitude_cols:
            return df

        if "Link Google" in df.columns or "link_google" in df.columns or "link google" in df.columns:
            link_col: str = self._resolver_coluna(df, ["Link Google", "link_google", "link google"])
            latitudes = []
            longitudes = []
            for value in df[link_col].fillna(""):
                coords = self._parse_google_link(value)
                if coords is None:
                    latitudes.append(None)
                    longitudes.append(None)
                else:
                    latitudes.append(coords[0])
                    longitudes.append(coords[1])
            df = df.copy()
            df["latitude"] = latitudes
            df["longitude"] = longitudes
            return df

        return df

    def detect_events(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        if df.empty:
            return []

        eventos: List[Dict[str, Any]] = []
        df = self._normalize_columns(df)
        timestamp_col: str = self._resolver_coluna(df, ["timestamp", "data_hora", "datetime", "date_time", "horario", "data"])
        df = self._ensure_coordinates(df)
        latitude_col: str = self._resolver_coluna(df, ["latitude", "lat"])
        longitude_col: str = self._resolver_coluna(df, ["longitude", "lon"])
        velocidade_col: str = self._resolver_coluna(df, ["velocidade_kmh", "speed_kmh", "velocidade", "speed"])

        df = df.copy()
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors="coerce")
        df[velocidade_col] = _parse_velocidade(df[velocidade_col]).fillna(0)
        df = df.dropna(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)

        if df.empty:
            return []

        for poi in self.pois:
            inside = False
            entry_detected = False
            entry_start_time: datetime | None = None
            entry_end_time: datetime | None = None

            for _, row in df.iterrows():
                dist = self._distancia_metros(poi.latitude, poi.longitude, row[latitude_col], row[longitude_col])
                velocidade = float(row[velocidade_col])
                current_time = row[timestamp_col]
                is_inside = dist <= poi.raio_metros

                if is_inside and velocidade <= poi.velocidade_maxima_kmh:
                    if not inside:
                        inside = True
                        entry_start_time = current_time
                        entry_end_time = current_time
                    else:
                        entry_end_time = current_time

                    if entry_start_time is not None and (current_time - entry_start_time).total_seconds() >= poi.tempo_parado_seg and not entry_detected:
                        eventos.append(
                            {
                                "tipo": "entrada",
                                "poi": poi.nome,
                                "tipo_poi": poi.tipo,
                                "inicio": entry_start_time,
                                "fim": entry_end_time,
                                "duracao_seg": int((current_time - entry_start_time).total_seconds()),
                            }
                        )
                        entry_detected = True
                else:
                    if inside and entry_detected and entry_end_time is not None:
                        eventos.append(
                            {
                                "tipo": "saida",
                                "poi": poi.nome,
                                "tipo_poi": poi.tipo,
                                "inicio": entry_end_time,
                                "fim": current_time,
                                "duracao_seg": 0,
                            }
                        )
                    inside = False
                    entry_detected = False
                    entry_start_time = None
                    entry_end_time = None

            if inside and entry_detected and entry_start_time and entry_end_time:
                eventos.append(
                    {
                        "tipo": "entrada",
                        "poi": poi.nome,
                        "tipo_poi": poi.tipo,
                        "inicio": entry_start_time,
                        "fim": entry_end_time,
                        "duracao_seg": int((entry_end_time - entry_start_time).total_seconds()),
                    }
                )

        return eventos

    def gerar_relatorio(self, df: pd.DataFrame) -> str:
        if self._has_plataforma_schema(df):
            return self._gerar_relatorio_plataforma(df)

        eventos = self.detect_events(df)
        if not eventos:
            return "Nenhum evento detectado."

        linhas = ["Relatório de rastreamento", "========================", ""]
        for evento in eventos:
            linhas.append(
                f"- {evento['tipo'].upper()} | {evento['poi']} ({evento['tipo_poi']}) | "
                f"{evento['inicio']} -> {evento['fim']} | duração: {evento['duracao_seg']} s"
            )
        return "\n".join(linhas)


def carregar_excel(caminho: str) -> pd.DataFrame:
    if not os.path.exists(caminho):
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho}. Verifique se o caminho está correto e se o arquivo existe."
        )
    return pd.read_excel(caminho)


def carregar_planilha(caminho: str) -> pd.DataFrame:
    if not os.path.exists(caminho):
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho}. Verifique se o caminho está correto e se o arquivo existe."
        )

    extensao = os.path.splitext(caminho)[1].lower()
    if extensao == ".csv":
        return pd.read_csv(caminho)
    if extensao in {".xlsx", ".xls"}:
        return pd.read_excel(caminho)

    raise ValueError("Formato de arquivo não suportado. Use CSV ou Excel.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analisa rastreamento de carretas e gera um relatório")
    parser.add_argument("arquivo", nargs="?", help="Caminho do arquivo Excel")
    parser.add_argument("--pois", nargs="+", default=[], help="POIs no formato nome:tipo:lat:lon:raio:tempo:velocidade")
    args = parser.parse_args()

    if not args.arquivo:
        arquivos = [f for f in os.listdir(".") if f.lower().endswith((".xlsx", ".xls"))]
        if arquivos:
            print("Arquivos Excel encontrados na pasta atual:")
            for idx, nome in enumerate(arquivos, start=1):
                print(f"  {idx}. {nome}")
            escolha = input("Digite o número do arquivo ou digite o caminho completo/relativo: ").strip().strip('"')
            if escolha.isdigit() and 1 <= int(escolha) <= len(arquivos):
                args.arquivo = arquivos[int(escolha) - 1]
            else:
                args.arquivo = escolha
        else:
            args.arquivo = input("Digite o caminho completo ou relativo do arquivo Excel: ").strip().strip('"')

    if not args.arquivo:
        raise SystemExit("Nenhum arquivo fornecido. Execute novamente e informe o caminho do arquivo.")

    pois = []
    for item in args.pois:
        nome, tipo, lat, lon, raio, tempo, velocidade = item.split(":")
        pois.append(
            {
                "nome": nome,
                "tipo": tipo,
                "latitude": float(lat),
                "longitude": float(lon),
                "raio_metros": float(raio),
                "tempo_parado_seg": int(tempo),
                "velocidade_maxima_kmh": float(velocidade),
            }
        )

    analyzer = RastreamentoAnalyzer(pois=pois)
    df = carregar_excel(args.arquivo)
    print(analyzer.gerar_relatorio(df))
