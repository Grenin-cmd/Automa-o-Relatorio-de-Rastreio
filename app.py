from __future__ import annotations

import io
from io import BytesIO
import os
import socket
import sys
import tempfile
import threading
import time
import webbrowser

from flask import Flask, render_template, request, flash, session, send_file, redirect
try:
    from docx import Document  # type: ignore[reportMissingImports]
except ImportError:  # pragma: no cover
    Document = None
import pandas as pd

from analisador_rastreio import RastreamentoAnalyzer

def _template_folder() -> str | None:
    """Quando o app roda como .exe empacotado (PyInstaller), os arquivos ficam
    numa pasta temporária diferente da pasta do script — isso aponta pro
    lugar certo em ambos os casos (rodando normal ou como .exe)."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "templates")  # type: ignore[attr-defined]
    return None


app = Flask(__name__, template_folder=_template_folder())
app.secret_key = "mudar_para_uma_chave_secreta"


import unicodedata

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


def _parse_velocidade(series: pd.Series) -> pd.Series:
    """Converte velocidade em texto (ex: '37 km/h', '105,5') para número.
    Extrai só a parte numérica, ignorando a unidade, e aceita tanto vírgula
    quanto ponto como separador decimal."""
    extraida = series.astype(str).str.extract(r"(-?\d+(?:[.,]\d+)?)")[0]
    return pd.to_numeric(extraida.str.replace(",", ".", regex=False), errors="coerce")


def _resolver_coluna(df: pd.DataFrame, aliases: list[str]) -> str:
    columns = [_normalize_column_name(col) for col in df.columns]
    for alias in aliases:
        alias_norm = _normalize_column_name(alias)
        for i, col in enumerate(columns):
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
                "latitude": float(lat),
                "longitude": float(lon),
                "raio_metros": float(raio),
                "tempo_parado_seg": int(tempo),
                "velocidade_maxima_kmh": float(velocidade),
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


def _find_missing_poi_rows(df: pd.DataFrame) -> tuple[list[dict[str, object]], list[str]]:
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

    # Em algumas plataformas (ex: exportação com coluna "Distância"), o POI
    # sempre vem preenchido com o nome do ponto mais próximo, mesmo quando o
    # veículo está longe dele — quem diz se realmente "está no POI" é a
    # distância. Quando essa coluna existir, ela manda mais que o texto do POI.
    distance_col = None
    for alias in ["poi_distancia", "distancia", "distance"]:
        try:
            distance_col = _resolver_coluna(df, [alias])
            break
        except ValueError:
            continue

    working = _normalize_columns(df.copy())
    working[timestamp_col] = pd.to_datetime(working[timestamp_col], dayfirst=True, errors="coerce")
    working[speed_col] = _parse_velocidade(working[speed_col]).fillna(9999)

    if distance_col is not None:
        working[distance_col] = pd.to_numeric(working[distance_col], errors="coerce").fillna(9999)
        sem_poi_real = working[distance_col] > 200
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


def _gerar_timeline_viagem(df: pd.DataFrame, placa: str, pois: list[dict[str, object]], limite_velocidade_kmh: float) -> list[dict[str, object]]:
    """Junta, para UMA placa: paradas em POI + excesso de velocidade (via
    RastreamentoAnalyzer) e paradas suspeitas (via _find_missing_poi_rows),
    tudo em ordem cronológica, pra alimentar a timeline de viagem na tela."""
    try:
        placa_col = _resolver_coluna(df, ["Placa", "placa", "plate"])
    except ValueError:
        return []

    subset = df[df[placa_col].astype(str) == placa]
    if subset.empty:
        return []

    analyzer = RastreamentoAnalyzer(pois=pois)
    eventos = list(analyzer.gerar_eventos_viagem(subset, limite_velocidade_kmh))

    missing_rows, _ = _find_missing_poi_rows(subset)
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


def _find_suspicious_stops(df: pd.DataFrame) -> list[dict[str, object]]:
    """Verifica, para TODAS as placas do arquivo, paradas acima de 10 minutos
    em um local sem POI identificado (independente da placa selecionada na tela)."""
    try:
        placa_col = _resolver_coluna(df, ["Placa", "placa", "plate"])
    except ValueError:
        return []

    resultados: list[dict[str, object]] = []
    placas = sorted(df[placa_col].dropna().astype(str).unique().tolist())
    for placa in placas:
        subset = df[df[placa_col].astype(str) == placa]
        rows, _ = _find_missing_poi_rows(subset)
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

        # Use the analyzer to produce a report for the subset and take its most relevant part
        report = analyzer.gerar_relatorio(subset)
        if report.startswith("Relatório de rastreamento"):
            body = report.split("\n\n", 1)[-1].strip()
        else:
            body = report.strip()

        # Collapse multiple lines into a compact paragraph
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
        abas = pd.ExcelFile(uploaded_file).sheet_names
        if len(abas) == 1:
            df = pd.read_excel(uploaded_file)
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
    action = request.form.get("action", "analyze")
    tipo_veiculo = request.form.get("tipo_veiculo", "pesado")
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
            missing_rows, missing_columns = _find_missing_poi_rows(df)
            paradas_suspeitas = _find_suspicious_stops(df)
            if file_name and columns:
                resumo_geral = None
        except Exception:
            _cleanup_cached_file()
            uploaded_file_path = None
            file_name = ""

    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        pois_text = request.form.get("pois", pois_text)

        uploaded_file_path = session.get("uploaded_file_path")
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
                    placas=placas,
                    columns=columns,
                    missing_rows=missing_rows,
                    missing_columns=missing_columns,
                    paradas_suspeitas=paradas_suspeitas,
                    timeline_eventos=timeline_eventos,
                    tipo_veiculo=tipo_veiculo,
                    file_name=file_name,
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
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                tipo_veiculo=tipo_veiculo,
                file_name=file_name,
                resumo_geral=resumo_geral,
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
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                tipo_veiculo=tipo_veiculo,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
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
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                tipo_veiculo=tipo_veiculo,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
            )

        placas = sorted(df[placa_col].dropna().astype(str).unique().tolist())
        if not placa_escolhida and placas:
            placa_escolhida = placas[0]

        paradas_suspeitas = _find_suspicious_stops(df)

        if placa_escolhida:
            df = df[df[placa_col].astype(str) == placa_escolhida]

        missing_rows, missing_columns = _find_missing_poi_rows(df)

        pois = ler_pois(pois_text)
        if not pois:
            flash("Informe pelo menos um POI no formato correto.", "warning")
            return render_template(
                "index.html",
                report=report,
                pois_text=pois_text,
                placa_escolhida=placa_escolhida,
                placas=placas,
                columns=columns,
                missing_rows=missing_rows,
                missing_columns=missing_columns,
                paradas_suspeitas=paradas_suspeitas,
                timeline_eventos=timeline_eventos,
                tipo_veiculo=tipo_veiculo,
                file_name=file_name,
                resumo_geral=resumo_geral,
                docx_available=docx_available,
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
                    carregar_arquivo(uploaded_file_path), placa_escolhida, pois, limite_velocidade_kmh
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
            placas=placas,
            columns=columns,
            missing_rows=missing_rows,
            missing_columns=missing_columns,
            paradas_suspeitas=paradas_suspeitas,
            timeline_eventos=timeline_eventos,
            tipo_veiculo=tipo_veiculo,
            file_name=file_name,
            resumo_geral=resumo_geral,
            docx_available=docx_available,
        )

    return render_template(
        "index.html",
        report=report,
        pois_text=pois_text,
        placa_escolhida="",
        placas=[],
        columns=[],
        missing_rows=missing_rows,
        missing_columns=missing_columns,
        paradas_suspeitas=paradas_suspeitas,
        timeline_eventos=timeline_eventos,
        tipo_veiculo=tipo_veiculo,
        file_name=file_name,
        resumo_geral=resumo_geral,
        docx_available=docx_available,
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


def _open_browser_when_ready(url: str) -> None:
    """Espera o servidor subir e então abre o navegador padrão automaticamente."""
    time.sleep(1.2)
    webbrowser.open(url)


if __name__ == "__main__":
    PORT = 5000
    URL = f"http://127.0.0.1:{PORT}"

    print(f"Iniciando a aplicação em {URL} ...")

    # Abre o navegador sozinho, sem precisar digitar o endereço na mão.
    threading.Thread(target=_open_browser_when_ready, args=(URL,), daemon=True).start()

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )
