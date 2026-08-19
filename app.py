from __future__ import annotations

import io
from io import BytesIO
import os
import socket
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from typing import Any

from flask import Flask, render_template, request, flash, session, send_file, redirect
try:
    from docx import Document  # type: ignore[reportMissingImports]
except ImportError:  # pragma: no cover
    Document = None
import pandas as pd

from analisador_rastreio import RastreamentoAnalyzer


def _template_folder() -> str:
    """Quando o app roda como .exe empacotado (PyInstaller), os arquivos
    ficam numa pasta temporária diferente da pasta do script — isso aponta
    pro lugar certo em ambos os casos (rodando normal ou como .exe).
    IMPORTANTE: nunca devolver None aqui — isso desativaria a pasta de
    templates do Flask por completo, em vez de usar o padrão."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "templates")  # type: ignore[attr-defined]
    return "templates"


app = Flask(__name__, template_folder=_template_folder())
app.secret_key = "mudar_para_uma_chave_secreta"


import unicodedata
import sqlite3

def _normalize_column_name(name: str) -> str:
    name = str(name).strip().lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.replace(" ", "_")
    name = name.replace("/", "_")
    name = name.replace("-", "_")
    while "__" in name:
        name = name.replace("__", "_")
    return name


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_normalize_column_name(col) for col in df.columns]
    return df


def _parse_number(value: Any, cast: type, error_message: str):
    if pd.isna(value):
        raise ValueError(error_message)

    if isinstance(value, str):
        normalized = value.strip().replace("\xa0", " ")
        normalized = normalized.replace("\u202f", " ")
        normalized = normalized.replace(" ", "")
        if not normalized:
            raise ValueError(error_message)
        if normalized.lower() in {"nan", "n/a", "na", "none", "null", "-", "--"}:
            raise ValueError(error_message)

        if "," in normalized:
            if "." in normalized and normalized.rfind(".") < normalized.rfind(","):
                normalized = normalized.replace(".", "")
            normalized = normalized.replace(",", ".")
        elif normalized.count(".") > 1:
            first_dot = normalized.find(".")
            normalized = normalized[:first_dot+1] + normalized[first_dot+1:].replace(".", "")

        value = normalized

    try:
        return cast(value)
    except Exception:
        raise ValueError(error_message)


def _resolver_coluna(df: pd.DataFrame, aliases: list[str]) -> str:
    columns = [_normalize_column_name(col) for col in df.columns]
    for alias in aliases:
        alias_norm = _normalize_column_name(alias)
        for i, col in enumerate(columns):
            # Colunas sem nome (ex: cabeçalho com um ";" sobrando no fim do
            # arquivo) não podem "casar" com nada — uma string vazia é
            # tecnicamente substring de qualquer palavra, então sem essa
            # checagem elas roubavam a vaga de colunas de verdade.
            if not col:
                continue
            if alias_norm == col or alias_norm in col or col in alias_norm:
                return df.columns[i]
    raise ValueError(f"Coluna não encontrada. Esperava uma das opções: {aliases}")


def ler_pois(texto: str) -> list[dict[str, object]]:
    pois = []
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        partes = linha.strip().split(":")
        if len(partes) != 7:
            continue
        nome, tipo, lat, lon, raio, tempo, velocidade = partes
        pois.append(
            {
                "nome": nome,
                "tipo": tipo,
                "latitude": _parse_number(lat, float, "Latitude ou longitude inválida no arquivo de POIs."),
                "longitude": _parse_number(lon, float, "Latitude ou longitude inválida no arquivo de POIs."),
                "raio_metros": _parse_number(raio, float, "Raio inválido no arquivo de POIs."),
                "tempo_parado_seg": _parse_number(tempo, int, "Tempo parado inválido no arquivo de POIs."),
                "velocidade_maxima_kmh": _parse_number(velocidade, float, "Velocidade máxima inválida no arquivo de POIs."),
            }
        )
    return pois


def _save_uploaded_file(uploaded_file) -> str:
    dados = uploaded_file.read()
    _, extensao = os.path.splitext(uploaded_file.filename)
    extensao = extensao.lower() if extensao else ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=extensao)
    tmp.write(dados)
    tmp.flush()
    tmp.close()
    return tmp.name


def _persistent_data_dir() -> str:
    """Onde guardar arquivos que precisam sobreviver entre execuções do
    programa (como o banco de POIs). Rodando como .exe empacotado, a pasta
    onde o PyInstaller extrai os arquivos é temporária e some quando o
    programa fecha — por isso usamos a pasta onde o próprio .exe está
    salvo, não essa pasta temporária."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(_persistent_data_dir(), "poi_store.db")


def _get_db_connection() -> "sqlite3.Connection":
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_poi_db() -> None:
    conn = _get_db_connection()
    try:
        colunas_existentes = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(pois)").fetchall()}
        if colunas_existentes and colunas_existentes.get("id", "").upper() != "TEXT":
            # poi_store.db já existia com outro schema (id não era TEXT) —
            # é isso que causava "datatype mismatch" ao inserir o uuid.
            conn.execute("DROP TABLE IF EXISTS pois")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pois (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                tipo TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                cidade TEXT,
                estado TEXT,
                rodovia TEXT,
                raio_metros REAL,
                tempo_parado_seg INTEGER,
                velocidade_maxima_kmh REAL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


_init_poi_db()


def _create_poi_id() -> str:
    return uuid.uuid4().hex


def _get_saved_pois() -> list[dict[str, object]]:
    conn = _get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM pois ORDER BY nome COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _save_saved_pois(pois: list[dict[str, object]]) -> None:
    """Substitui todos os POIs salvos no banco pelos que foram importados agora."""
    conn = _get_db_connection()
    try:
        conn.execute("DELETE FROM pois")
        conn.executemany(
            """
            INSERT INTO pois (id, nome, tipo, latitude, longitude, cidade, estado, rodovia, raio_metros, tempo_parado_seg, velocidade_maxima_kmh)
            VALUES (:id, :nome, :tipo, :latitude, :longitude, :cidade, :estado, :rodovia, :raio_metros, :tempo_parado_seg, :velocidade_maxima_kmh)
            """,
            pois,
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_poi(poi: dict[str, object]) -> None:
    conn = _get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO pois (id, nome, tipo, latitude, longitude, cidade, estado, rodovia, raio_metros, tempo_parado_seg, velocidade_maxima_kmh)
            VALUES (:id, :nome, :tipo, :latitude, :longitude, :cidade, :estado, :rodovia, :raio_metros, :tempo_parado_seg, :velocidade_maxima_kmh)
            ON CONFLICT(id) DO UPDATE SET
                nome=excluded.nome, tipo=excluded.tipo, latitude=excluded.latitude,
                longitude=excluded.longitude, cidade=excluded.cidade, estado=excluded.estado,
                rodovia=excluded.rodovia, raio_metros=excluded.raio_metros,
                tempo_parado_seg=excluded.tempo_parado_seg, velocidade_maxima_kmh=excluded.velocidade_maxima_kmh
            """,
            poi,
        )
        conn.commit()
    finally:
        conn.close()


def _delete_poi(poi_id: str) -> None:
    conn = _get_db_connection()
    try:
        conn.execute("DELETE FROM pois WHERE id = ?", (poi_id,))
        conn.commit()
    finally:
        conn.close()


def _clear_all_pois() -> None:
    conn = _get_db_connection()
    try:
        conn.execute("DELETE FROM pois")
        conn.commit()
    finally:
        conn.close()


def _find_saved_poi(poi_id: str, pois: list[dict[str, object]]) -> dict[str, object] | None:
    for poi in pois:
        if str(poi.get("id")) == str(poi_id):
            return poi
    return None


def _parse_poi_dataframe(df: pd.DataFrame) -> list[dict[str, object]]:
    if df.empty:
        raise ValueError("Arquivo de POIs vazio.")

    working = _normalize_columns(df.copy())

    def _find_column(aliases: list[str]) -> str | None:
        for alias in aliases:
            try:
                return _resolver_coluna(working, [alias])
            except ValueError:
                continue
        return None

    columns = {
        "nome": _find_column(["nome", "name", "poi", "ponto", "nome_poi", "poi_nome", "local", "localizacao", "localidade", "location"]),
        "tipo": _find_column(["tipo", "type", "categoria", "category", "grupo", "group"]),
        "latitude": _find_column(["latitude", "lat", "latidude", "latidude"],),
        "longitude": _find_column(["longitude", "lon", "lng", "longitutde", "longitud", "longitute"]),
        "raio_metros": _find_column(["raio_metros", "raio", "radius", "distancia", "distance"]),
        "tempo_parado_seg": _find_column(["tempo_parado_seg", "tempo_parado", "tempo", "tempo_segundos", "stop_time"]),
        "velocidade_maxima_kmh": _find_column(["velocidade_maxima_kmh", "velocidade_maxima", "velocidade", "velocidade_kmh", "speed_kmh", "speed"]),
        "cidade": _find_column(["cidade", "city"]),
        "estado": _find_column(["estado", "state"]),
        "rodovia": _find_column(["rodovia", "highway", "road"]),
    }

    missing = [key for key in ["nome", "tipo", "latitude", "longitude"] if columns[key] is None]
    if missing:
        raise ValueError(
            "Arquivo de POIs inválido. Faltam colunas obrigatórias: " + ", ".join(missing)
        )

    nome_col = columns["nome"]
    latitude_col = columns["latitude"]
    longitude_col = columns["longitude"]
    tipo_col = columns["tipo"]
    cidade_col = columns["cidade"]
    estado_col = columns["estado"]
    rodovia_col = columns["rodovia"]
    raio_col = columns["raio_metros"]
    tempo_col = columns["tempo_parado_seg"]
    velocidade_col = columns["velocidade_maxima_kmh"]

    assert nome_col is not None and latitude_col is not None and longitude_col is not None

    pois: list[dict[str, object]] = []
    for _, row in working.iterrows():
        nome = str(row[nome_col]).strip()
        if not nome:
            continue

        try:
            latitude = _parse_number(row[latitude_col], float, "Latitude ou longitude inválida no arquivo de POIs.")
            longitude = _parse_number(row[longitude_col], float, "Latitude ou longitude inválida no arquivo de POIs.")
        except ValueError:
            continue

        tipo = str(row[tipo_col]).strip() if tipo_col else ""
        cidade = str(row[cidade_col]).strip() if cidade_col else ""
        estado = str(row[estado_col]).strip() if estado_col else ""
        rodovia = str(row[rodovia_col]).strip() if rodovia_col else ""

        if raio_col and pd.notna(row[raio_col]):
            try:
                raio_metros = _parse_number(row[raio_col], float, "Raio inválido no arquivo de POIs.")
            except ValueError:
                raio_metros = 200.0
        else:
            raio_metros = 200.0

        if tempo_col and pd.notna(row[tempo_col]):
            try:
                tempo_parado_seg = _parse_number(row[tempo_col], int, "Tempo parado inválido no arquivo de POIs.")
            except ValueError:
                tempo_parado_seg = 120
        else:
            tempo_parado_seg = 120

        if velocidade_col and pd.notna(row[velocidade_col]):
            try:
                velocidade_maxima_kmh = _parse_number(row[velocidade_col], float, "Velocidade máxima inválida no arquivo de POIs.")
            except ValueError:
                velocidade_maxima_kmh = 10.0
        else:
            velocidade_maxima_kmh = 10.0

        pois.append(
            {
                "id": _create_poi_id(),
                "nome": nome,
                "tipo": tipo,
                "latitude": latitude,
                "longitude": longitude,
                "cidade": cidade,
                "estado": estado,
                "rodovia": rodovia,
                "raio_metros": raio_metros,
                "tempo_parado_seg": tempo_parado_seg,
                "velocidade_maxima_kmh": velocidade_maxima_kmh,
            }
        )

    if not pois:
        raise ValueError("Nenhum POI válido encontrado no arquivo.")

    return pois


def _cleanup_cached_file() -> None:
    file_path = session.pop("uploaded_file_path", None)
    session.pop("uploaded_file_name", None)
    if file_path and os.path.exists(file_path):
        try:
            os.unlink(file_path)
        except OSError:
            pass


def _format_duration(seconds: int) -> str:
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _parse_velocidade_series(series: pd.Series) -> pd.Series:
    extraida = series.astype(str).str.extract(r"(-?\d+(?:[.,]\d+)?)")[0]
    return pd.to_numeric(extraida.str.replace(",", ".", regex=False), errors="coerce")


def _find_missing_poi_rows(df: pd.DataFrame, raio_tolerancia_m: float = 200.0, nomes_pois_registrados: set[str] | None = None) -> tuple[list[dict[str, object]], list[str]]:
    poi_col = None
    for alias in ["poi", "local", "location", "ponto_de_interesse", "ponto_interesse"]:
        try:
            poi_col = _resolver_coluna(df, [alias])
            break
        except ValueError:
            continue

    if poi_col is None:
        return [], []

    try:
        timestamp_col = _resolver_coluna(df, ["timestamp", "data_hora", "datetime", "date_time", "horario", "data"])
        speed_col = _resolver_coluna(df, ["velocidade_kmh", "speed_kmh", "velocidade", "speed"])
    except ValueError:
        return [], []

    working = _normalize_columns(df.copy())
    working[timestamp_col] = pd.to_datetime(working[timestamp_col], dayfirst=True, errors="coerce")
    working[speed_col] = _parse_velocidade_series(working[speed_col]).fillna(9999)

    if nomes_pois_registrados:
        # Parada é "suspeita" quando o nome do POI da linha NÃO bate com
        # nenhum dos POIs cadastrados no banco (mesmo que a plataforma de
        # origem tenha atribuído algum nome de POI genérico/aleatório ali).
        poi_normalizado = working[poi_col].astype(str).map(_normalize_column_name)
        poi_vazio = working[poi_col].isna() | working[poi_col].astype(str).str.strip().eq("")
        sem_poi_real = poi_vazio | ~poi_normalizado.isin(nomes_pois_registrados)
    else:
        # Sem nenhum POI cadastrado ainda, cai pro critério antigo: usa a
        # coluna de distância da própria plataforma, se existir.
        distance_col = None
        for alias in ["poi_distancia", "distancia", "distance"]:
            try:
                distance_col = _resolver_coluna(df, [alias])
                break
            except ValueError:
                continue

        if distance_col is not None:
            working[distance_col] = pd.to_numeric(working[distance_col], errors="coerce").fillna(9999)
            sem_poi_real = working[distance_col] > raio_tolerancia_m
        else:
            sem_poi_real = working[poi_col].isna() | working[poi_col].astype(str).str.strip().eq("")

    missing = working[
        sem_poi_real
        & (working[speed_col] <= 10)
    ].copy()
    missing = missing.dropna(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)
    if missing.empty:
        return [], []

    groups: list[dict[str, object]] = []
    current_start = None
    current_end = None
    current_count = 0

    for _, row in missing.iterrows():
        timestamp = row[timestamp_col]
        if current_start is None:
            current_start = timestamp
            current_end = timestamp
            current_count = 1
            continue

        if timestamp - current_end <= pd.Timedelta(minutes=10):
            current_end = timestamp
            current_count += 1
        else:
            if (current_end - current_start).total_seconds() >= 600:
                groups.append(
                    {
                        "Início": current_start,
                        "Fim": current_end,
                        "Duração": _format_duration(int((current_end - current_start).total_seconds())),
                        "Registros": current_count,
                    }
                )
            current_start = timestamp
            current_end = timestamp
            current_count = 1

    if current_start is not None and current_end is not None and (current_end - current_start).total_seconds() >= 600:
        groups.append(
            {
                "Início": current_start,
                "Fim": current_end,
                "Duração": _format_duration(int((current_end - current_start).total_seconds())),
                "Registros": current_count,
            }
        )

    if not groups:
        return [], []

    columns = ["Início", "Fim", "Duração", "Registros"]
    rows = [
        {str(key): value for key, value in record.items()}
        for record in groups
    ]
    return rows, columns


def _gerar_timeline_viagem(df: pd.DataFrame, placa: str, pois: list[dict[str, object]], limite_velocidade_kmh: float, raio_tolerancia_m: float = 200.0) -> list[dict[str, object]]:
    """Junta, para UMA placa: paradas em POI + excesso de velocidade (via
    RastreamentoAnalyzer) e paradas suspeitas (via _find_missing_poi_rows),
    em ordem cronológica, pra alimentar a timeline de viagem na tela."""
    try:
        placa_col = _resolver_coluna(df, ["Placa", "placa", "plate"])
    except ValueError:
        return []

    subset = df[df[placa_col].astype(str) == placa]
    if subset.empty:
        return []

    analyzer = RastreamentoAnalyzer(pois=pois)
    eventos = list(analyzer.gerar_eventos_viagem(subset, limite_velocidade_kmh))

    nomes_pois_registrados = {_normalize_column_name(p["nome"]) for p in pois if p.get("nome")}
    missing_rows, _ = _find_missing_poi_rows(subset, raio_tolerancia_m, nomes_pois_registrados)
    for row in missing_rows:
        eventos.append(
            {
                "tipo": "parada_suspeita",
                "local": None,
                "inicio": row["Início"],
                "fim": row["Fim"],
                "em_andamento": False,
            }
        )

    eventos.sort(key=lambda e: e["inicio"])
    return eventos


def _find_suspicious_stops(df: pd.DataFrame, raio_tolerancia_m: float = 200.0, nomes_pois_registrados: set[str] | None = None) -> list[dict[str, object]]:
    """Verifica, para TODAS as placas do arquivo, paradas acima de 10 minutos
    em um local que não bate com nenhum POI cadastrado."""
    try:
        placa_col = _resolver_coluna(df, ["Placa", "placa", "plate"])
    except ValueError:
        return []

    resultados: list[dict[str, object]] = []
    placas = sorted(df[placa_col].dropna().astype(str).unique().tolist())
    for placa in placas:
        subset = df[df[placa_col].astype(str) == placa]
        rows, _ = _find_missing_poi_rows(subset, raio_tolerancia_m, nomes_pois_registrados)
        for row in rows:
            resultados.append(
                {
                    "Placa": placa,
                    "Início": row["Início"],
                    "Fim": row["Fim"],
                    "Duração": row["Duração"],
                    "Registros": row["Registros"],
                }
            )

    resultados.sort(key=lambda item: item["Início"])  # type: ignore[arg-type]
    return resultados


def _gerar_resumo_geral_placas(df: pd.DataFrame, pois: list[dict[str, object]]) -> str:
    try:
        working = _normalize_columns(df.copy())
        placa_col = _resolver_coluna(working, ["Placa", "placa", "plate"])
    except ValueError:
        return "Não foi possível detectar a coluna de placa para gerar o resumo geral."

    placas = sorted(working[placa_col].dropna().astype(str).unique().tolist())
    if not placas:
        return "Nenhuma placa encontrada no arquivo."

    analyzer = RastreamentoAnalyzer(pois=pois)
    lines: list[str] = []
    for placa in placas:
        subset = df[df[placa_col].astype(str) == placa]
        if subset.empty:
            continue

        report = analyzer.gerar_relatorio(subset)
        report_body = report
        if report.startswith("Relatório de rastreamento"):
            report_body = report.split("\n\n", 1)[-1]

        report_body = report_body.strip()
        if not report_body:
            report_body = "Nenhum evento relevante detectado."

        lines.append(f"{placa}: {report_body}")

    return "\n\n".join(lines)


def _create_word_bytes(summary: str) -> bytes:
    if Document is None:
        raise RuntimeError("python-docx não está instalado. Instale com 'pip install python-docx'.")

    document = Document()
    document.add_heading("Resumo Geral de Placas", level=1)
    document.add_paragraph("CecotiFood Services", style="Intense Quote")
    for line in summary.split("\n\n"):
        document.add_paragraph(line)

    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output.read()


def _gerar_resumo_ultimo_estado(df: pd.DataFrame, pois: list[dict[str, object]]) -> str:
    try:
        working = _normalize_columns(df.copy())
        placa_col = _resolver_coluna(working, ["Placa", "placa", "plate"])
    except ValueError:
        return "Não foi possível detectar a coluna de placa para gerar o resumo rápido."

    placas = sorted(working[placa_col].dropna().astype(str).unique().tolist())
    if not placas:
        return "Nenhuma placa encontrada no arquivo."

    analyzer = RastreamentoAnalyzer(pois=pois)
    lines: list[str] = []
    for placa in placas:
        subset = df[df[placa_col].astype(str) == placa]
        if subset.empty:
            continue

        report = analyzer.gerar_relatorio(subset)
        if report.startswith("Relatório de rastreamento"):
            body = report.split("\n\n", 1)[-1].strip()
        else:
            body = report.strip()

        compact = " ".join(line.strip() for line in body.splitlines() if line.strip())
        lines.append(f"{placa}: {compact}")

    return "\n\n".join(lines)


@app.route("/download_word")
def download_word():
    resumo = session.get("word_summary")
    if not resumo:
        flash("Gere o resumo geral primeiro para poder baixar o Word.", "warning")
        return redirect("/")

    try:
        doc_bytes = _create_word_bytes(resumo)
    except RuntimeError as error:
        flash(str(error), "danger")
        return redirect("/")

    return send_file(
        BytesIO(doc_bytes),
        as_attachment=True,
        download_name="resumo_geral_cecotifood.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def carregar_arquivo(uploaded_file) -> pd.DataFrame:
    if isinstance(uploaded_file, str):
        caminho = uploaded_file
        if not os.path.exists(caminho):
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}.")

        extensao = os.path.splitext(caminho)[1].lower()
        if extensao == ".csv":
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
                for sep in [",", ";", "\t", "|"]:
                    try:
                        df = pd.read_csv(caminho, encoding=encoding, sep=sep)
                        df = _normalize_columns(df)
                        if len(df.columns) > 1:
                            return df
                    except UnicodeDecodeError:
                        break
                    except Exception as error:
                        if "Expected" in str(error) or "C error" in str(error) or "Too many columns" in str(error):
                            continue
                        raise
            raise ValueError("Não foi possível decodificar o CSV. Verifique o encoding e o delimitador do arquivo.")

        if extensao in {".xls", ".xlsx"}:
            df = pd.read_excel(caminho)
            df = _normalize_columns(df)
            return df

        raise ValueError("Formato não suportado. Use CSV ou Excel.")

    nome = uploaded_file.filename
    if not nome:
        raise ValueError("Nenhum arquivo selecionado.")

    _, extensao = os.path.splitext(nome)
    extensao = extensao.lower()

    if extensao == ".csv":
        dados = uploaded_file.read()
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
            for sep in [",", ";", "\t", "|"]:
                try:
                    df = pd.read_csv(io.BytesIO(dados), encoding=encoding, sep=sep)
                    df = _normalize_columns(df)
                    if len(df.columns) > 1:
                        return df
                except UnicodeDecodeError:
                    break
                except Exception as error:
                    if "Expected" in str(error) or "C error" in str(error) or "Too many columns" in str(error):
                        continue
                    raise
        raise ValueError("Não foi possível decodificar o CSV. Verifique o encoding e o delimitador do arquivo.")

    if extensao in {".xls", ".xlsx"}:
        dados = uploaded_file.read()
        buffer = io.BytesIO(dados)
        abas = pd.ExcelFile(buffer).sheet_names
        if len(abas) == 1:
            buffer.seek(0)
            df = pd.read_excel(buffer)
            df = _normalize_columns(df)
            return df
        raise ValueError(f"Planilha Excel com várias abas encontradas: {abas}. Use um arquivo com apenas uma aba ou selecione corretamente.")

    raise ValueError("Formato não suportado. Use CSV ou Excel.")


@app.route("/", methods=["GET", "POST"])
def index():
    report = None
    pois_text = (
        "ClienteA:cliente:-23.5505:-46.6333:300:120:10\n"
        "PostoX:posto:-23.5600:-46.6400:250:120:10"
    )
    placa_escolhida = request.form.get("placa", "")
    tipo_veiculo = request.form.get("tipo_veiculo", "pesado")
    try:
        raio_suspeita = float(request.form.get("raio_suspeita", 200) or 200)
    except (TypeError, ValueError):
        raio_suspeita = 200.0
    selected_poi_id = request.form.get("selected_poi", "")
    poi_form_data = {
        "nome": "",
        "tipo": "",
        "latitude": "",
        "longitude": "",
        "cidade": "",
        "estado": "",
        "rodovia": "",
        "raio_metros": 200.0,
        "tempo_parado_seg": 120,
        "velocidade_maxima_kmh": 10.0,
    }
    action = request.form.get("action", "analyze")
    columns: list[str] = []
    missing_rows: list[dict[str, object]] = []
    missing_columns: list[str] = []
    placas: list[str] = []
    resumo_geral = None
    paradas_suspeitas: list[dict[str, object]] = []
    timeline_eventos: list[dict[str, object]] = []
    docx_available = Document is not None
    uploaded_file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name", "")
    saved_pois = _get_saved_pois()
    saved_pois_count = len(saved_pois)
    nomes_pois_registrados = {_normalize_column_name(p["nome"]) for p in saved_pois if p.get("nome")}

    if uploaded_file_path and not os.path.exists(uploaded_file_path):
        _cleanup_cached_file()
        uploaded_file_path = None
        file_name = ""

    if request.method == "GET" and uploaded_file_path and os.path.exists(uploaded_file_path):
        try:
            df = carregar_arquivo(uploaded_file_path)
            columns = list(df.columns)
            placa_col = _resolver_coluna(df, ["Placa", "placa", "plate"])
            placas = sorted(df[placa_col].dropna().astype(str).unique().tolist())
            if not placa_escolhida and placas:
                placa_escolhida = placas[0]
            missing_rows, missing_columns = _find_missing_poi_rows(df, raio_suspeita, nomes_pois_registrados)
            paradas_suspeitas = _find_suspicious_stops(df, raio_suspeita, nomes_pois_registrados)
            if placa_escolhida:
                paradas_suspeitas = [p for p in paradas_suspeitas if str(p.get("Placa")) == str(placa_escolhida)]
            if file_name and columns:
                resumo_geral = None
        except Exception:
            _cleanup_cached_file()
            uploaded_file_path = None
            file_name = ""

    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        arquivo_pois = request.files.get("arquivo_pois")
        pois_text = request.form.get("pois", pois_text)
        saved_pois = _get_saved_pois()
        saved_pois_count = len(saved_pois)

        uploaded_file_path = session.get("uploaded_file_path")

        if action in ("save_poi", "load_poi", "delete_poi", "clear_pois"):
            if action == "save_poi":
                try:
                    poi_id = selected_poi_id or _create_poi_id()
                    novo_poi = {
                        "id": poi_id,
                        "nome": request.form.get("poi_nome", "").strip(),
                        "tipo": request.form.get("poi_tipo", "").strip(),
                        "latitude": _parse_number(request.form.get("poi_latitude", ""), float, "Latitude inválida."),
                        "longitude": _parse_number(request.form.get("poi_longitude", ""), float, "Longitude inválida."),
                        "cidade": request.form.get("poi_cidade", "").strip(),
                        "estado": request.form.get("poi_estado", "").strip(),
                        "rodovia": request.form.get("poi_rodovia", "").strip(),
                        "raio_metros": _parse_number(request.form.get("poi_raio_metros", "200"), float, "Raio inválido.") if request.form.get("poi_raio_metros") else 200.0,
                        "tempo_parado_seg": _parse_number(request.form.get("poi_tempo_parado_seg", "120"), int, "Tempo parado inválido.") if request.form.get("poi_tempo_parado_seg") else 120,
                        "velocidade_maxima_kmh": _parse_number(request.form.get("poi_velocidade_maxima_kmh", "10"), float, "Velocidade máxima inválida.") if request.form.get("poi_velocidade_maxima_kmh") else 10.0,
                    }
                    if not novo_poi["nome"]:
                        raise ValueError("Informe o nome do POI.")
                    _upsert_poi(novo_poi)
                    selected_poi_id = poi_id
                    flash("POI salvo com sucesso.", "success")
                except Exception as error:
                    flash(str(error), "danger")

            elif action == "load_poi":
                if selected_poi_id:
                    encontrado = _find_saved_poi(selected_poi_id, _get_saved_pois())
                    if encontrado:
                        poi_form_data = {
                            "nome": encontrado.get("nome", ""),
                            "tipo": encontrado.get("tipo", ""),
                            "latitude": encontrado.get("latitude", ""),
                            "longitude": encontrado.get("longitude", ""),
                            "cidade": encontrado.get("cidade", ""),
                            "estado": encontrado.get("estado", ""),
                            "rodovia": encontrado.get("rodovia", ""),
                            "raio_metros": encontrado.get("raio_metros", 200.0),
                            "tempo_parado_seg": encontrado.get("tempo_parado_seg", 120),
                            "velocidade_maxima_kmh": encontrado.get("velocidade_maxima_kmh", 10.0),
                        }
                    else:
                        flash("POI não encontrado.", "warning")

            elif action == "delete_poi":
                if selected_poi_id:
                    _delete_poi(selected_poi_id)
                    selected_poi_id = ""
                    flash("POI excluído.", "success")

            elif action == "clear_pois":
                _clear_all_pois()
                selected_poi_id = ""
                flash("Todos os POIs foram removidos.", "success")

            saved_pois = _get_saved_pois()
            saved_pois_count = len(saved_pois)
            return render_template(
                "index.html",
                report=report,
                pois_text=pois_text,
                placa_escolhida=placa_escolhida,
                tipo_veiculo=tipo_veiculo,
                raio_suspeita=raio_suspeita,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
                saved_pois_count=saved_pois_count,
                saved_pois=saved_pois,
                selected_poi_id=selected_poi_id,
                poi_form_data=poi_form_data,
            )

        if action == "import_pois":
            if not arquivo_pois or not arquivo_pois.filename:
                flash("Selecione um arquivo CSV ou Excel de POIs para importar.", "warning")
                return render_template(
                    "index.html",
                    report=report,
                    pois_text=pois_text,
                    placa_escolhida=placa_escolhida,
                    tipo_veiculo=tipo_veiculo,
                    raio_suspeita=raio_suspeita,
                    paradas_suspeitas=paradas_suspeitas,
                    timeline_eventos=timeline_eventos,
                    placas=placas,
                    columns=columns,
                    missing_rows=missing_rows,
                    missing_columns=missing_columns,
                    file_name=file_name,
                    resumo_geral=resumo_geral,
                    docx_available=docx_available,
                    saved_pois_count=saved_pois_count,
                    saved_pois=saved_pois,
                    selected_poi_id=selected_poi_id,
                    poi_form_data=poi_form_data,
                )

            try:
                df_pois = carregar_arquivo(arquivo_pois)
                imported_pois = _parse_poi_dataframe(df_pois)
                _save_saved_pois(imported_pois)
                saved_pois = imported_pois
                saved_pois_count = len(imported_pois)
                session["last_import_file"] = arquivo_pois.filename
                flash(f"{saved_pois_count} POI{'s' if saved_pois_count != 1 else ''} importado(s) com sucesso.", "success")
            except Exception as error:
                flash(str(error), "danger")

            return render_template(
                "index.html",
                report=report,
                pois_text=pois_text,
                placa_escolhida=placa_escolhida,
                tipo_veiculo=tipo_veiculo,
                raio_suspeita=raio_suspeita,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
                saved_pois_count=saved_pois_count,
                saved_pois=saved_pois,
                selected_poi_id=selected_poi_id,
                poi_form_data=poi_form_data,
            )

        if arquivo and arquivo.filename:
            try:
                new_path = _save_uploaded_file(arquivo)
            except Exception as error:
                flash(str(error), "danger")
                return render_template(
                    "index.html",
                    report=report,
                    pois_text=pois_text,
                    placa_escolhida=placa_escolhida,
                    tipo_veiculo=tipo_veiculo,
                    raio_suspeita=raio_suspeita,
                    paradas_suspeitas=paradas_suspeitas,
                    timeline_eventos=timeline_eventos,
                    placas=placas,
                    columns=columns,
                    missing_rows=missing_rows,
                    missing_columns=missing_columns,
                    file_name=file_name,
                    saved_pois_count=saved_pois_count,
                    saved_pois=saved_pois,
                    selected_poi_id=selected_poi_id,
                    poi_form_data=poi_form_data,
                )

            if uploaded_file_path and uploaded_file_path != new_path and os.path.exists(uploaded_file_path):
                try:
                    os.unlink(uploaded_file_path)
                except OSError:
                    pass

            uploaded_file_path = new_path
            session["uploaded_file_path"] = new_path
            session["uploaded_file_name"] = arquivo.filename
            file_name = arquivo.filename

        if not uploaded_file_path or not os.path.exists(uploaded_file_path):
            flash("Selecione um arquivo CSV ou Excel para continuar.", "warning")
            return render_template(
                "index.html",
                report=report,
                pois_text=pois_text,
                placa_escolhida=placa_escolhida,
                tipo_veiculo=tipo_veiculo,
                raio_suspeita=raio_suspeita,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                file_name=file_name,
                resumo_geral=resumo_geral,
                saved_pois_count=saved_pois_count,
                saved_pois=saved_pois,
                selected_poi_id=selected_poi_id,
                poi_form_data=poi_form_data,
            )

        try:
            df = carregar_arquivo(uploaded_file_path)
            columns = list(df.columns)
        except Exception as error:
            flash(str(error), "danger")
            return render_template(
                "index.html",
                report=report,
                pois_text=pois_text,
                placa_escolhida=placa_escolhida,
                tipo_veiculo=tipo_veiculo,
                raio_suspeita=raio_suspeita,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
                saved_pois_count=saved_pois_count,
                saved_pois=saved_pois,
                selected_poi_id=selected_poi_id,
                poi_form_data=poi_form_data,
            )

        try:
            placa_col = _resolver_coluna(df, ["Placa", "placa", "plate"])
        except Exception as error:
            flash(str(error), "danger")
            flash(f"Colunas detectadas: {columns}", "info")
            return render_template(
                "index.html",
                report=report,
                pois_text=pois_text,
                placa_escolhida=placa_escolhida,
                tipo_veiculo=tipo_veiculo,
                raio_suspeita=raio_suspeita,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
                saved_pois_count=saved_pois_count,
                saved_pois=saved_pois,
                selected_poi_id=selected_poi_id,
                poi_form_data=poi_form_data,
            )

        placas = sorted(df[placa_col].dropna().astype(str).unique().tolist())
        if not placa_escolhida and placas:
            placa_escolhida = placas[0]

        if placa_escolhida:
            df = df[df[placa_col].astype(str) == placa_escolhida]

        missing_rows, missing_columns = _find_missing_poi_rows(df, raio_suspeita, nomes_pois_registrados)

        paradas_suspeitas = _find_suspicious_stops(carregar_arquivo(uploaded_file_path), raio_suspeita, nomes_pois_registrados)
        if placa_escolhida:
            paradas_suspeitas = [p for p in paradas_suspeitas if str(p.get("Placa")) == str(placa_escolhida)]

        pois = ler_pois(pois_text) + [
            {k: v for k, v in p.items() if k != "id"} for p in saved_pois
        ]
        if not pois:
            flash("Informe pelo menos um POI no formato correto.", "warning")
            return render_template(
                "index.html",
                report=report,
                pois_text=pois_text,
                placa_escolhida=placa_escolhida,
                tipo_veiculo=tipo_veiculo,
                raio_suspeita=raio_suspeita,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
                saved_pois_count=saved_pois_count,
                saved_pois=saved_pois,
                selected_poi_id=selected_poi_id,
                poi_form_data=poi_form_data,
            )

        analyzer = RastreamentoAnalyzer(pois=pois)
        limite_velocidade_kmh = 95.0 if tipo_veiculo == "pesado" else 110.0
        try:
            if action == "summary":
                resumo_geral = _gerar_resumo_geral_placas(carregar_arquivo(uploaded_file_path), pois)
                session["word_summary"] = resumo_geral
            elif action == "summary_latest":
                resumo_geral = _gerar_resumo_ultimo_estado(carregar_arquivo(uploaded_file_path), pois)
                session["word_summary"] = resumo_geral
            elif action == "timeline":
                timeline_eventos = _gerar_timeline_viagem(
                    carregar_arquivo(uploaded_file_path), placa_escolhida, pois, limite_velocidade_kmh, raio_suspeita
                )
            else:
                report = analyzer.gerar_relatorio(df)
        except Exception as error:
            flash(str(error), "danger")
            flash(f"Colunas detectadas: {columns}", "info")

        return render_template(
            "index.html",
            report=report,
            pois_text=pois_text,
            placa_escolhida=placa_escolhida,
            tipo_veiculo=tipo_veiculo,
            raio_suspeita=raio_suspeita,
            paradas_suspeitas=paradas_suspeitas,
            timeline_eventos=timeline_eventos,
            placas=placas,
            columns=columns,
            missing_rows=missing_rows,
            missing_columns=missing_columns,
            file_name=file_name,
            resumo_geral=resumo_geral,
            docx_available=docx_available,
            saved_pois_count=saved_pois_count,
            saved_pois=saved_pois,
            selected_poi_id=selected_poi_id,
            poi_form_data=poi_form_data,
        )

    return render_template(
        "index.html",
        report=report,
        pois_text=pois_text,
        placa_escolhida="",
        tipo_veiculo=tipo_veiculo,
        raio_suspeita=raio_suspeita,
        paradas_suspeitas=paradas_suspeitas,
        timeline_eventos=timeline_eventos,
        placas=[],
        columns=[],
        missing_rows=missing_rows,
        missing_columns=missing_columns,
        file_name=file_name,
        resumo_geral=resumo_geral,
        docx_available=docx_available,
        saved_pois_count=saved_pois_count,
        saved_pois=saved_pois,
        selected_poi_id=selected_poi_id,
        poi_form_data=poi_form_data,
    )


def _find_available_port(initial_port: int = 5000) -> int:
    port = initial_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        while True:
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                port += 1


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _get_server_port(default_port: int = 5000) -> int:
    port_str = os.environ.get("PORT")
    if port_str:
        try:
            port = int(port_str)
        except ValueError:
            raise RuntimeError("Valor inválido para a variável de ambiente PORT. Use um número inteiro.")

        if _is_port_available(port):
            return port
        raise RuntimeError(f"Porta {port} já está em uso. Pare o serviço existente ou defina PORT com outra porta.")

    if _is_port_available(default_port):
        return default_port

    # Em vez de travar o programa quando a porta padrão já está ocupada
    # (ex: sobrou um processo antigo rodando), procura a próxima porta livre
    # automaticamente — assim o servidor sempre sobe.
    return _find_available_port(default_port + 1)


def _open_browser(port: int) -> None:
    url = f"http://127.0.0.1:{port}/"

    def _try_open() -> None:
        time.sleep(1.0)
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass

    thread = threading.Thread(target=_try_open, daemon=True)
    thread.start()


if __name__ == "__main__":
    port = _get_server_port(5000)
    print(f"Iniciando a aplicação na porta {port}...")
    _open_browser(port)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
