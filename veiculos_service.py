from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from dispositivos_service import normalizar_payload_dispositivo


class VeiculosService:
    """Gerencia veículos, dispositivos e última posição recebida."""

    def __init__(self) -> None:
        self._veiculos: dict[str, dict[str, Any]] = {}
        self._dispositivos: dict[str, dict[str, Any]] = {}

    def registrar_ou_atualizar(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalizado = normalizar_payload_dispositivo(payload)
        placa = str(payload.get("placa") or payload.get("plate") or payload.get("veiculo") or "SEM_PLACA").strip().upper()
        dispositivo_id = str(normalizado["dispositivo_id"])

        if placa == "SEM_PLACA":
            placa = f"VEICULO-{dispositivo_id[:8]}"

        veiculo = self._veiculos.setdefault(placa, {
            "veiculo_id": placa,
            "dispositivo_id": dispositivo_id,
            "ultimo_status": {},
            "ultima_posicao": {
                "latitude": None,
                "longitude": None,
                "data_hora": None,
                "velocidade_kmh": None,
            },
        })

        self._dispositivos[dispositivo_id] = {
            "dispositivo_id": dispositivo_id,
            "veiculo_id": placa,
            "imei": normalizado.get("imei"),
            "ultimo_status": deepcopy(normalizado),
            "atualizado_em": normalizado["data_hora"],
        }

        veiculo["dispositivo_id"] = dispositivo_id
        veiculo["ultimo_status"] = deepcopy(normalizado)
        veiculo["ultima_posicao"] = {
            "latitude": normalizado.get("latitude"),
            "longitude": normalizado.get("longitude"),
            "data_hora": normalizado.get("data_hora"),
            "velocidade_kmh": normalizado.get("velocidade_kmh"),
            "ignicao": normalizado.get("ignicao"),
            "bateria_pct": normalizado.get("bateria_pct"),
        }

        return {
            "veiculo_id": veiculo["veiculo_id"],
            "dispositivo_id": veiculo["dispositivo_id"],
            "ultima_posicao": veiculo["ultima_posicao"],
            "ultimo_status": veiculo["ultimo_status"],
        }

    def listar_veiculos(self) -> list[dict[str, Any]]:
        return [
            {
                "veiculo_id": v["veiculo_id"],
                "dispositivo_id": v["dispositivo_id"],
                "ultima_posicao": v["ultima_posicao"],
                "ultimo_status": v["ultimo_status"],
            }
            for v in self._veiculos.values()
        ]

    def obter_veiculo(self, veiculo_id: str) -> dict[str, Any] | None:
        veiculo = self._veiculos.get(veiculo_id.upper())
        if not veiculo:
            return None
        return {
            "veiculo_id": veiculo["veiculo_id"],
            "dispositivo_id": veiculo["dispositivo_id"],
            "ultima_posicao": veiculo["ultima_posicao"],
            "ultimo_status": veiculo["ultimo_status"],
        }
