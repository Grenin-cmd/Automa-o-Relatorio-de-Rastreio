"""Análises de rastreamento independentes do Flask: importação de POIs,
paradas não cadastradas, linha do tempo, resumo geral e exportação Word."""
from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd

from analisador_rastreio import RastreamentoAnalyzer

try:
    from docx import Document  # type: ignore[reportMissingImports]
except ImportError:  # pragma: no cover
    Document = None

DOCX_DISPONIVEL = Document is not None
from geo import pontos_dentro_de_algum_poi
from utils import converter_coordenada, converter_numero_opcional, format_duration, normalize_column_name, normalize_columns, parse_velocidade_series, resolver_coluna


def parse_poi_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        raise ValueError("Arquivo de POIs vazio.")

    # Limpa os nomes das colunas (remove espaços, acentos, caixa e caracteres especiais)
    # para tornar a detecção de colunas resiliente a variações da planilha (ex: " Latitude").
    working = normalize_columns(df.copy())

    def _find_col(keywords: list[str]) -> str | None:
        return next((c for c in working.columns if any(k in c for k in keywords)), None)

    col_nome = _find_col(["local", "nome", "descricao", "poi", "localizacao"])
    col_lat = _find_col(["latitude", "lat"])
    col_lon = _find_col(["longitude", "longitud", "lon", "lng"])
    col_tipo = _find_col(["tipo", "categoria"])
    col_raio = _find_col(["raio"])
    col_tempo = _find_col(["tempo_parado", "tempo"])
    col_velocidade = _find_col(["velocidade_maxima", "velocidade"])
    col_cidade = _find_col(["cidade"])
    col_estado = _find_col(["estado", "uf"])
    col_rodovia = _find_col(["rodovia"])

    if not col_lat or not col_lon:
        raise ValueError(f"Colunas de Latitude e Longitude não encontradas. Colunas lidas: {list(df.columns)}")

    n = len(working)

    def _text_col(col: str | None, default: str) -> pd.Series:
        if not col:
            return pd.Series([default] * n, index=working.index)
        serie = working[col].astype(str).str.strip()
        return serie.where(working[col].notna() & (serie != ""), default)

    def _num_col(col: str | None, cast: type, default: float | int) -> pd.Series:
        if not col:
            return pd.Series([default] * n, index=working.index)
        # .map() opera célula a célula (mesma lógica de converter_numero_opcional),
        # mas evita a reconstrução de uma Series por linha que .iterrows() faz,
        # sendo significativamente mais rápido em planilhas com milhares de POIs.
        return working[col].map(lambda v: converter_numero_opcional(v, cast, default))

    nomes = _text_col(col_nome, "POI sem nome")
    tipos = _text_col(col_tipo, "Geral")
    cidades = _text_col(col_cidade, "")
    estados = _text_col(col_estado, "")
    rodovias = _text_col(col_rodovia, "")

    latitudes = working[col_lat].map(converter_coordenada)
    longitudes = working[col_lon].map(converter_coordenada)
    raios = _num_col(col_raio, float, 200.0)
    tempos = _num_col(col_tempo, int, 120)
    velocidades = _num_col(col_velocidade, float, 10.0)

    resultado = pd.DataFrame({
        "nome": nomes,
        "tipo": tipos,
        "latitude": latitudes,
        "longitude": longitudes,
        "cidade": cidades,
        "estado": estados,
        "rodovia": rodovias,
        "raio_metros": raios,
        "tempo_parado_seg": tempos,
        "velocidade_maxima_kmh": velocidades,
    })

    # Descarta linhas sem coordenadas válidas (mesmo critério do loop original).
    resultado = resultado.dropna(subset=["latitude", "longitude"])

    pois = resultado.to_dict("records")
    for poi in pois:
        poi["id"] = uuid.uuid4().hex

    return pois # type: ignore


def find_missing_poi_rows(
    df: pd.DataFrame, 
    raio_tolerancia_m: float = 200.0, 
    nomes_pois_registrados: set[str] | None = None,
    pois_lista: list[dict[str, object]] | None = None
) -> tuple[list[dict[str, object]], list[str]]:
    # Resolve as colunas já no DataFrame normalizado, onde elas serão usadas.
    working = normalize_columns(df.copy())
    try:
        timestamp_col = resolver_coluna(working, ["timestamp", "data_hora", "datetime", "date_time", "horario", "data"])
        speed_col = resolver_coluna(working, ["velocidade_kmh", "speed_kmh", "velocidade", "speed"])
    except ValueError:
        return [], []

    lat_col = None
    lon_col = None
    for alias in ["latitude", "lat"]:
        try:
            lat_col = resolver_coluna(working, [alias])
            break
        except ValueError:
            continue

    for alias in ["longitude", "lon", "lng"]:
        try:
            lon_col = resolver_coluna(working, [alias])
            break
        except ValueError:
            continue

    working[timestamp_col] = pd.to_datetime(working[timestamp_col], dayfirst=True, format="mixed", errors="coerce")
    working[speed_col] = parse_velocidade_series(working[speed_col]).fillna(9999)

    parados = working[working[speed_col] <= 10].dropna(subset=[timestamp_col]).copy()
    if parados.empty:
        return [], []

    # Uma parada só é "não cadastrada" se nenhuma fonte de informação a explica:
    # (a) a coluna de POI da própria planilha está vazia (quando existe) e
    # (b) o ponto está fora do raio de todos os POIs cadastrados (quando há base).
    mascara_suspeita = np.ones(len(parados), dtype=bool)

    # Busca exata: a busca por substring confundiria "local" com "localizacao"
    # (endereço, sempre preenchido) e "poi" com "poi_distancia".
    poi_col = next(
        (c for c in ["poi", "ponto_de_interesse", "local", "location"] if c in working.columns),
        None,
    )
    if poi_col:
        sem_poi = parados[poi_col].isna() | parados[poi_col].astype(str).str.strip().eq("")
        mascara_suspeita &= sem_poi.to_numpy()

    if pois_lista and lat_col and lon_col:
        lats_p = pd.to_numeric(parados[lat_col].astype(str).str.replace(",", "."), errors="coerce").to_numpy()
        lons_p = pd.to_numeric(parados[lon_col].astype(str).str.replace(",", "."), errors="coerce").to_numpy()
        perto_de_poi = pontos_dentro_de_algum_poi(lats_p, lons_p, pois_lista, raio_tolerancia_m)
        if perto_de_poi is not None:
            mascara_suspeita &= ~perto_de_poi

    missing = parados[mascara_suspeita].copy()

    missing = missing.sort_values(timestamp_col).reset_index(drop=True)
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
                        "Duração": format_duration(int((current_end - current_start).total_seconds())),
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
                "Duração": format_duration(int((current_end - current_start).total_seconds())),
                "Registros": current_count,
            }
        )

    if not groups:
        return [], []

    columns = ["Início", "Fim", "Duração", "Registros"]
    rows = [{str(key): value for key, value in record.items()} for record in groups]
    return rows, columns


def find_suspicious_stops(
    df: pd.DataFrame, 
    raio_tolerancia_m: float = 200.0, 
    nomes_pois_registrados: set[str] | None = None,
    pois_lista: list[dict[str, object]] | None = None
) -> list[dict[str, object]]:
    try:
        placa_col = resolver_coluna(df, ["Placa", "placa", "plate"])
    except ValueError:
        return []

    resultados: list[dict[str, object]] = []
    # Calcula a coluna de placa como string uma única vez e usa groupby para obter
    # os subsets por placa, evitando refazer `df[placa_col].astype(str) == placa`
    # (custo O(n_placas * n_linhas)) a cada iteração — importante em planilhas
    # grandes com muitas placas distintas.
    placas_str = df[placa_col].astype(str)
    for placa, subset in df.groupby(placas_str, sort=True):
        if not placa or placa == "nan":
            continue
        rows, _ = find_missing_poi_rows(subset, raio_tolerancia_m, nomes_pois_registrados, pois_lista)
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

    resultados.sort(key=lambda item: str(item.get("Início", "")))
    return resultados


def gerar_timeline_viagem(df: pd.DataFrame, placa: str, pois: list[dict[str, object]], limite_velocidade_kmh: float, raio_tolerancia_m: float = 200.0) -> list[dict[str, object]]:
    try:
        placa_col = resolver_coluna(df, ["Placa", "placa", "plate"])
    except ValueError:
        return []

    subset = df[df[placa_col].astype(str) == placa]
    if subset.empty:
        return []

    analyzer = RastreamentoAnalyzer(pois=pois)
    eventos = list(analyzer.gerar_eventos_viagem(subset, limite_velocidade_kmh))

    nomes_pois_registrados = {normalize_column_name(str(p["nome"])) for p in pois if p.get("nome")}
    missing_rows, _ = find_missing_poi_rows(subset, raio_tolerancia_m, nomes_pois_registrados, pois)
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


def gerar_resumo_geral_placas(
    df: pd.DataFrame,
    pois: list[dict[str, object]],
    raio_tolerancia_m: float = 200.0,
    refinar: Callable[[str], str] | None = None,
) -> str:
    """Gera um parágrafo por placa. `refinar`, se informado, recebe o texto
    bruto e devolve a versão refinada (ex: pela IA com as regras ativas)."""
    try:
        working = normalize_columns(df.copy())
        placa_col = resolver_coluna(working, ["Placa", "placa", "plate"])
    except ValueError:
        return "Não foi possível detectar a coluna de placa para gerar o resumo geral."

    placas_str = working[placa_col].astype(str)
    if placas_str.dropna().empty:
        return "Nenhuma placa encontrada no arquivo."

    analyzer = RastreamentoAnalyzer(pois=pois, raio_tolerancia_m=raio_tolerancia_m)
    try:
        nome_col = resolver_coluna(
            working,
            [
                "nome_supervisor",
                "supervisor",
                "nome_motorista",
                "motorista",
                "condutor",
                "responsavel",
                "colaborador",
                "nome",
            ],
        )
    except ValueError:
        nome_col = None
    lines: list[str] = []
    # groupby computa todos os subsets de placa em uma única passada vetorizada,
    # em vez de refazer o filtro booleano `df[placa_col].astype(str) == placa`
    # para cada placa (O(n_placas * n_linhas) no código anterior).
    for placa, subset in working.groupby(placas_str, sort=True):
        if not placa or placa == "nan" or subset.empty:
            continue

        report = analyzer.gerar_relatorio(subset)
        report_body = report
        if report.startswith("Relatório de rastreamento"):
            report_body = report.split("\n\n", 1)[-1]

        report_body = report_body.strip()
        if not report_body:
            report_body = "Nenhum evento relevante detectado."

        nome = ""
        if nome_col:
            nomes = subset[nome_col].dropna().astype(str).str.strip()
            nomes = nomes[~nomes.str.lower().isin({"", "nan", "none", "null"})]
            if not nomes.empty:
                nome = nomes.iloc[0]

        lines.append(formatar_linha_resumo(placa, report_body, nome))

    resumo_bruto = "\n\n".join(lines)
    if refinar is not None:
        resumo_bruto = refinar(resumo_bruto)

    return separar_resumo_por_placa(resumo_bruto, lines)


def formatar_linha_resumo(placa: str, report_body: str, nome: str = "") -> str:
    """Formata paradas em residência no padrão operacional dos supervisores."""
    texto = " ".join(str(report_body).split())
    residencia_match = re.search(
        r"\bresid(?:e|ê)ncia(?:\s+(?:de|da|do))?\s+(.+?)(?=\s+(?:desde|às|as|em|na)\b|[.;]|$)",
        texto,
        flags=re.IGNORECASE,
    )
    nome_exibicao = nome.strip() or (residencia_match.group(1).strip(" .,:;") if residencia_match else "")
    prefixo = f"{placa} {nome_exibicao}".strip()
    if not residencia_match:
        return f"{prefixo}: {texto}"

    saida_match = re.search(
        r"\b(?:saiu|sa[ií]da)\b.*?\b(?:às|as)\s+(\d{1,2}:\d{2})",
        texto,
        flags=re.IGNORECASE,
    )
    if saida_match:
        return f"{prefixo}: Saída da residência as {saida_match.group(1)}."

    if re.search(r"\bestá\s+(?:em|na)\b", texto, flags=re.IGNORECASE):
        return f"{prefixo}: Está na residência."

    return f"{placa}: {texto}"


def separar_resumo_por_placa(resumo: str, linhas_originais: list[str]) -> str:
    """Garante uma linha/parágrafo separado para cada placa após o refinamento."""
    if not resumo or len(linhas_originais) < 2:
        return resumo

    placas = [linha.split(":", 1)[0].strip() for linha in linhas_originais]
    for placa in placas[1:]:
        resumo = re.sub(rf"\s+(?={re.escape(placa)}\s*:)", "\n\n", resumo, count=1)
    return resumo


def obter_posicoes_placas(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Retorna a última coordenada válida de cada placa para links de mapa."""
    try:
        working = normalize_columns(df.copy())
        placa_col = resolver_coluna(working, ["Placa", "placa", "plate"])
    except ValueError:
        return {}

    def _parece_placa_texto(texto: str) -> bool:
        texto_limpo = re.sub(r"[^A-Z0-9]", "", str(texto).upper())
        if not texto_limpo:
            return False
        return bool(re.fullmatch(r"[A-Z]{2,4}\d{2,5}[A-Z0-9]*", texto_limpo)) or bool(re.fullmatch(r"\d{2,5}[A-Z0-9]{2,5}", texto_limpo))

    def _extrair_par_coordenadas(valor: object) -> tuple[float | None, float | None]:
        texto = str(valor).strip()
        if not texto or texto.lower() in {"nan", "none", "null"}:
            return None, None
        if _parece_placa_texto(texto):
            return None, None

        pares = [
            re.search(r"[?&]q=(-?\d+(?:[.,]\d+)?),\s*(-?\d+(?:[.,]\d+)?)", texto, re.IGNORECASE),
            re.search(r"@(-?\d+(?:[.,]\d+)?),\s*(-?\d+(?:[.,]\d+)?)", texto, re.IGNORECASE),
        ]
        valores = next((match.groups() for match in pares if match), None)
        if valores is None:
            numeros = re.findall(r"-?\d+(?:[.,]\d+)?", texto)
            if len(numeros) < 2:
                return None, None
            valores = tuple(numeros[:2])

        latitude = converter_coordenada(valores[0])
        longitude = converter_coordenada(valores[1])
        if latitude is None or longitude is None or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return None, None
        return latitude, longitude

    lat_col = lon_col = None
    try:
        lat_col = resolver_coluna(working, ["latitude", "lat"])
        lon_col = resolver_coluna(working, ["longitude", "lon", "lng"])
    except ValueError:
        pass

    if lat_col and lon_col and lat_col != lon_col:
        working["_latitude_mapa"] = working[lat_col].map(converter_coordenada)
        working["_longitude_mapa"] = working[lon_col].map(converter_coordenada)
    else:
        coluna_combinada = None
        for aliases in (
            ["latitude_longitude", "latitude___longitude", "lat_lon", "coordenadas", "coordenada"],
            ["link_google", "google_maps", "link_mapa"],
        ):
            try:
                coluna_combinada = resolver_coluna(working, aliases)
                break
            except ValueError:
                continue

        if coluna_combinada is None:
            return {}

        pares = working[coluna_combinada].map(_extrair_par_coordenadas)
        working["_latitude_mapa"] = pares.map(lambda par: par[0] if isinstance(par, tuple) else None)
        working["_longitude_mapa"] = pares.map(lambda par: par[1] if isinstance(par, tuple) else None)

    working = working.dropna(subset=["_latitude_mapa", "_longitude_mapa"])
    if working.empty:
        return {}

    posicoes: dict[str, tuple[float, float]] = {}
    for placa, subset in working.groupby(placa_col, sort=False):
        placa_texto = str(placa).strip()
        if placa_texto and placa_texto.lower() != "nan":
            ultima = subset.iloc[-1]
            posicoes[placa_texto] = (float(ultima["_latitude_mapa"]), float(ultima["_longitude_mapa"]))
    return posicoes


def gerar_word_bytes(summary: str) -> bytes:
    if Document is None:
        raise RuntimeError("python-docx não está instalado. Instale com 'pip install python-docx'.")

    document = Document()
    document.add_heading("Resumo Geral de Placas", level=1)
    document.add_paragraph("Análise Inteligente de Frotas", style="Intense Quote")
    for line in summary.split("\n\n"):
        document.add_paragraph(line)

    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output.read()
