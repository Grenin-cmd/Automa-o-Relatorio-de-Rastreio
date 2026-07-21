from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

import math
import os
import unicodedata
import pandas as pd


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


class RastreamentoAnalyzer:
    def __init__(self, pois: List[Dict[str, Any]], velocidade_limite_kmh: float = 10.0, tempo_parado_seg: int = 120):
        self.pois = [PontoInteresse(**poi) for poi in pois]
        self.velocidade_limite_kmh = velocidade_limite_kmh
        self.tempo_parado_seg = tempo_parado_seg

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

        # Exact match first
        for alias in aliases:
            alias_norm = self._normalize_column_name(alias)
            for i, col in enumerate(columns):
                if alias_norm == col:
                    return df.columns[i]

        # Partial match by best candidate length to avoid shorter accidental hits
        for alias in aliases:
            alias_norm = self._normalize_column_name(alias)
            candidates = []
            for i, col in enumerate(columns):
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
        # "Hoje" é a data mais recente presente no próprio arquivo (não o
        # relógio do sistema) — evita comparar com o dia real quando o
        # relatório é gerado bem depois dos dados.
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
        if "matriz" in cleaned or "camara fria" in cleaned or "camarafria" in cleaned or "camera fria" in cleaned or "camarafria" in cleaned:
            return "matriz"
        return cleaned

    def _poi_label(self, poi_name: str | None) -> str:
        if self._poi_key(poi_name) == "matriz":
            return "Matriz"
        return str(poi_name).strip()

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
        timestamp_col = self._resolver_coluna(df, ["data", "timestamp", "data_hora", "datetime", "date_time", "horario"])
        poi_col = self._resolver_coluna(df, ["poi"])
        distance_col = self._resolver_coluna(df, ["poi_distancia", "poi_distância", "poi_-_distancia", "poi - distancia", "poi distancia"])
        speed_col = self._resolver_coluna(df, ["velocidade", "velocidade_kmh", "speed", "speed_kmh", "speed_km_h"])

        df = df.copy()
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], dayfirst=True, errors="coerce")
        df[distance_col] = pd.to_numeric(df[distance_col], errors="coerce").fillna(9999)
        df[speed_col] = _parse_velocidade(df[speed_col]).fillna(0)
        df = df.dropna(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)

        if df.empty:
            return "Nenhum evento detectado."

        reference_date = df[timestamp_col].max().date()
        stops = self._construir_paradas_poi(df, poi_col, distance_col, speed_col, timestamp_col)

        last_poi = None
        last_poi_raw = None
        last_poi_time = None
        last_poi_inside = False
        last_stopped = False
        if not df.empty:
            last_row = df.iloc[-1]
            last_poi_raw = str(last_row[poi_col]).strip() if pd.notna(last_row[poi_col]) else None
            last_poi = self._poi_key(last_poi_raw)
            last_stopped = float(last_row[speed_col]) <= self.velocidade_limite_kmh
            last_poi_inside = bool(last_poi) and float(last_row[distance_col]) <= 200 and last_stopped
            last_poi_time = last_row[timestamp_col] if last_poi_inside else None

        if not stops:
            if last_poi_inside:
                if last_poi == "matriz":
                    return f"Está na matriz desde {self._format_relative_time(last_poi_time, reference_date)}."
                return f"Está em {self._poi_label(last_poi_raw)} desde {self._format_relative_time(last_poi_time, reference_date)}."
            if last_stopped:
                return f"Parada sem POI identificado desde {self._format_relative_time(last_row[timestamp_col], reference_date)}."
            return "Nenhum evento relevante detectado."

        lines = ["Relatório de rastreamento", "========================", ""]
        for stop in stops:
            label = stop.get("label") or self._poi_label(stop["poi"])
            if stop["saida"] is None:
                if stop["poi"] == "matriz":
                    lines.append(f"Está na matriz desde {self._format_relative_time(stop['inicio'], reference_date)}.")
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
    ) -> List[Dict[str, Any]]:
        """Percorre o df (já normalizado, ordenado e com colunas resolvidas) e
        monta a lista de paradas em POI (chegada/saída). Reaproveitado tanto
        pelo relatório em texto quanto pela timeline de viagem."""
        relevant_stop_sec = max(self.tempo_parado_seg, 600)
        stops: List[Dict[str, Any]] = []
        current_poi = None
        current_label = None
        entry_start: datetime | None = None
        entry_end: datetime | None = None
        inside = False

        def finalize_stop(poi_key, poi_label, start, end, departure):
            if poi_key and start and end and (end - start).total_seconds() >= relevant_stop_sec:
                stops.append({"poi": poi_key, "label": poi_label or "", "inicio": start, "fim": end, "saida": departure})

        for _, row in df.iterrows():
            poi_raw = str(row[poi_col]).strip() if pd.notna(row[poi_col]) else ""
            poi_key = self._poi_key(poi_raw)
            poi_label = self._poi_label(poi_raw)
            is_near = row[distance_col] <= 200
            is_stopped = row[speed_col] <= self.velocidade_limite_kmh
            at_poi = bool(poi_key) and is_near and is_stopped
            current_time = row[timestamp_col]

            if at_poi and not inside:
                inside = True
                current_poi = poi_key
                current_label = poi_label
                entry_start = current_time
                entry_end = current_time
            elif at_poi and inside and poi_key == current_poi:
                entry_end = current_time
            elif at_poi and inside and poi_key != current_poi:
                finalize_stop(current_poi, current_label, entry_start, entry_end, current_time)
                current_poi = poi_key
                current_label = poi_label
                entry_start = current_time
                entry_end = current_time
            elif not at_poi and inside:
                finalize_stop(current_poi, current_label, entry_start, entry_end, current_time)
                inside = False
                current_poi = None
                current_label = None
                entry_start = None
                entry_end = None

        if inside and entry_start and entry_end:
            if (entry_end - entry_start).total_seconds() >= relevant_stop_sec:
                stops.append({"poi": current_poi, "label": current_label or "", "inicio": entry_start, "fim": entry_end, "saida": None})

        return stops

    def detectar_excesso_velocidade(self, df: pd.DataFrame, limite_kmh: float) -> List[Dict[str, Any]]:
        """Detecta períodos consecutivos em que a velocidade ultrapassa o
        limite informado (ex: 95 km/h para caminhão/carreta, 110 para carro)."""
        if df is None or df.empty:
            return []

        df = self._normalize_columns(df)
        try:
            timestamp_col = self._resolver_coluna(df, ["data", "timestamp", "data_hora", "datetime", "date_time", "horario"])
            speed_col = self._resolver_coluna(df, ["velocidade", "velocidade_kmh", "speed", "speed_kmh", "speed_km_h"])
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
        """Monta uma timeline única (paradas em POI + excesso de velocidade)
        para uma viagem de UM veículo, em ordem cronológica. A detecção de
        paradas suspeitas (sem POI) fica a cargo do app.py, que já tem essa
        lógica pronta e a mescla ao resultado deste método."""
        if not self._has_plataforma_schema(df) or df is None or df.empty:
            return []

        df_norm = self._normalize_columns(df.copy())
        timestamp_col = self._resolver_coluna(df_norm, ["data", "timestamp", "data_hora", "datetime", "date_time", "horario"])
        poi_col = self._resolver_coluna(df_norm, ["poi"])
        distance_col = self._resolver_coluna(df_norm, ["poi_distancia", "poi_distância", "poi_-_distancia", "poi - distancia", "poi distancia"])
        speed_col = self._resolver_coluna(df_norm, ["velocidade", "velocidade_kmh", "speed", "speed_kmh", "speed_km_h"])

        df_norm[timestamp_col] = pd.to_datetime(df_norm[timestamp_col], dayfirst=True, errors="coerce")
        df_norm[distance_col] = pd.to_numeric(df_norm[distance_col], errors="coerce").fillna(9999)
        df_norm[speed_col] = _parse_velocidade(df_norm[speed_col]).fillna(0)
        df_norm = df_norm.dropna(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)

        if df_norm.empty:
            return []

        stops = self._construir_paradas_poi(df_norm, poi_col, distance_col, speed_col, timestamp_col)
        excessos = self.detectar_excesso_velocidade(df, limite_velocidade_kmh)

        eventos: List[Dict[str, Any]] = []
        for stop in stops:
            label = stop.get("label") or self._poi_label(stop["poi"])
            eventos.append(
                {
                    "tipo": "poi",
                    "local": label,
                    "inicio": stop["inicio"],
                    "fim": stop["saida"] if stop["saida"] is not None else stop["fim"],
                    "em_andamento": stop["saida"] is None,
                }
            )

        for evento in excessos:
            eventos.append(
                {
                    "tipo": "excesso_velocidade",
                    "local": None,
                    "inicio": evento["inicio"],
                    "fim": evento["fim"],
                    "velocidade_maxima": evento["velocidade_maxima"],
                    "em_andamento": False,
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
            link_col = self._resolver_coluna(df, ["Link Google", "link_google", "link google"])
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
        timestamp_col = self._resolver_coluna(df, ["timestamp", "data_hora", "datetime", "date_time", "horario", "data"])
        df = self._ensure_coordinates(df)
        latitude_col = self._resolver_coluna(df, ["latitude", "lat"])
        longitude_col = self._resolver_coluna(df, ["longitude", "lon"])
        velocidade_col = self._resolver_coluna(df, ["velocidade_kmh", "speed_kmh", "velocidade", "speed"])

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
