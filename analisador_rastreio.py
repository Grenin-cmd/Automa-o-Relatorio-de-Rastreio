from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

import math
import os
import unicodedata
import pandas as pd


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

    def _format_relative_time(self, timestamp: datetime | None) -> str:
        if timestamp is None:
            return ""
        now = datetime.now()
        today = now.date()
        date = timestamp.date()
        time_text = timestamp.strftime("%H:%M")
        if date == today:
            return time_text
        if date == today - pd.Timedelta(days=1):
            return f"{time_text} de ontem"
        return f"{time_text} de {timestamp.strftime('%d/%m/%Y')}"

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
        df[speed_col] = pd.to_numeric(df[speed_col], errors="coerce").fillna(0)
        df = df.dropna(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)

        relevant_stop_sec = max(self.tempo_parado_seg, 600)
        stops: List[Dict[str, Any]] = []
        current_poi = None
        entry_start: datetime | None = None
        entry_end: datetime | None = None
        inside = False

        def finalize_stop(poi_key: str | None, poi_label: str | None, start: datetime | None, end: datetime | None, departure: datetime | None):
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
            else:
                inside = False

        last_poi = None
        last_poi_time = None
        last_poi_inside = False
        if not df.empty:
            last_row = df.iloc[-1]
            last_poi_raw = str(last_row[poi_col]).strip() if pd.notna(last_row[poi_col]) else None
            last_poi = self._poi_key(last_poi_raw)
            last_poi_inside = bool(last_poi) and float(last_row[distance_col]) <= 200 and float(last_row[speed_col]) <= self.velocidade_limite_kmh
            last_poi_time = last_row[timestamp_col] if last_poi_inside else None

        if not stops:
            if last_poi_inside:
                if last_poi == "matriz":
                    return f"Está na matriz desde {self._format_relative_time(last_poi_time)}."
                return f"Está em {self._poi_label(last_poi_raw)} desde {self._format_relative_time(last_poi_time)}."
            return "Nenhum evento relevante detectado."

        lines = ["Relatório de rastreamento", "========================", ""]
        for stop in stops:
            label = stop.get("label") or self._poi_label(stop["poi"])
            if stop["saida"] is None:
                if stop["poi"] == "matriz":
                    lines.append(f"Está na matriz desde {self._format_relative_time(stop['inicio'])}.")
                else:
                    lines.append(f"Está em {label} desde {self._format_relative_time(stop['inicio'])}.")
            else:
                lines.append(
                    f"Chegou no {label} às {self._format_relative_time(stop['inicio'])} e saiu às {self._format_relative_time(stop['saida'])}."
                )
        return "\n".join(lines)

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
