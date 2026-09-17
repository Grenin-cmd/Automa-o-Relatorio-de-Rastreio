from __future__ import annotations

from datetime import datetime
import re
from typing import Any


def _extrair_numero_texto(valor: Any) -> float | None:
    if valor is None:
        return None

    if isinstance(valor, (int, float)):
        return float(valor)

    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        texto = texto.replace("%", "").replace(" ", "")
        texto = texto.replace(".", "", 1) if texto.count(".") > 1 and "," not in texto and texto.rfind(".") > 0 else texto
        if "," in texto and "." in texto:
            if texto.rfind(",") > texto.rfind("."):
                texto = texto.replace(".", "").replace(",", ".")
            else:
                texto = texto.replace(",", "")
        elif "," in texto:
            texto = texto.replace(",", ".")

        try:
            return float(texto)
        except ValueError:
            match = re.search(r"-?\d+(?:[.,]\d+)?", texto)
            if match:
                return float(match.group(0).replace(",", "."))
            return None

    return None


def _extrair_data_hora(valor: Any) -> datetime | None:
    if valor is None:
        return None

    if isinstance(valor, datetime):
        return valor

    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None

        formatos = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y/%m/%d %H:%M:%S",
        ]
        for fmt in formatos:
            try:
                return datetime.strptime(texto, fmt)
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(texto)
        except ValueError:
            pass

    return None


def _valor_bool(valor: Any) -> bool | None:
    if valor is None:
        return None
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    if isinstance(valor, str):
        texto = valor.strip().lower()
        if texto in {"1", "true", "on", "ligado", "ativo", "yes"}:
            return True
        if texto in {"0", "false", "off", "desligado", "inativo", "no"}:
            return False
    return None


def normalizar_payload_dispositivo(payload: dict[str, Any]) -> dict[str, Any]:
    """Normaliza qualquer payload de chip/rastreador para o formato interno do sistema."""
    if not isinstance(payload, dict):
        raise ValueError("Payload do dispositivo deve ser um dicionário.")

    dispositivo_id = (
        payload.get("deviceId")
        or payload.get("device_id")
        or payload.get("id")
        or payload.get("vehicle_id")
        or payload.get("placa")
        or "DESCONHECIDO"
    )

    latitude = _extrair_numero_texto(
        payload.get("latitude")
        or payload.get("lat")
        or payload.get("latitude_gps")
    )
    longitude = _extrair_numero_texto(
        payload.get("longitude")
        or payload.get("lon")
        or payload.get("lng")
        or payload.get("longitude_gps")
    )
    velocidade = _extrair_numero_texto(
        payload.get("speed")
        or payload.get("velocidade_kmh")
        or payload.get("velocidade")
        or payload.get("speed_kmh")
    )
    bateria = _extrair_numero_texto(
        payload.get("battery")
        or payload.get("bateria")
        or payload.get("battery_pct")
        or payload.get("bateria_pct")
    )

    ignicao = _valor_bool(
        payload.get("ignition")
        or payload.get("ignicao")
        or payload.get("engine_on")
        or payload.get("motor_ligado")
    )

    data_hora = _extrair_data_hora(
        payload.get("timestamp")
        or payload.get("ts")
        or payload.get("datetime")
        or payload.get("data_hora")
    )

    if data_hora is None:
        data_hora = datetime.now()

    resultado = {
        "dispositivo_id": str(dispositivo_id),
        "imei": str(payload.get("imei") or payload.get("device_imei") or ""),
        "latitude": latitude,
        "longitude": longitude,
        "velocidade_kmh": velocidade,
        "ignicao": ignicao,
        "bateria_pct": int(bateria) if bateria is not None and bateria == int(bateria) else bateria,
        "data_hora": data_hora,
        "fonte": payload.get("source") or payload.get("fonte") or "GENERICA",
        "raw": payload,
    }

    if not isinstance(resultado["imei"], str):
        resultado["imei"] = str(resultado["imei"])

    if isinstance(resultado["bateria_pct"], float) and resultado["bateria_pct"].is_integer():
        resultado["bateria_pct"] = int(resultado["bateria_pct"])

    return resultado
