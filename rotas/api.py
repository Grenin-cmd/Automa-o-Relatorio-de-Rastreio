"""APIs JSON (dispositivos, veículos e busca de POIs)."""
from __future__ import annotations


from flask import Blueprint, request


bp = Blueprint("api", __name__)
from banco import get_saved_pois
from rotas.comum import VEICULOS_SERVICE, api_auth_required, registrar_dispositivo_recebido
from utils import normalizar_busca


@bp.route("/api/dispositivos/receber", methods=["POST"])
@api_auth_required
def api_receber_dispositivo():
    try:
        payload = request.get_json(silent=True)
        if payload is None:
            payload = request.form.to_dict()
        if not payload:
            return {"ok": False, "erro": "Nenhum payload recebido."}, 400

        if not isinstance(payload, dict):
            return {"ok": False, "erro": "Payload deve ser um objeto JSON."}, 400

        normalizado = registrar_dispositivo_recebido(payload)
        return {
            "ok": True,
            "mensagem": "Payload do dispositivo recebido e normalizado.",
            "dados": normalizado,
        }, 200
    except Exception as error:
        return {"ok": False, "erro": str(error)}, 400


@bp.route("/api/dispositivos/recentes", methods=["GET"])
@api_auth_required
def api_dispositivos_recentes():
    return {"ok": True, "dados": VEICULOS_SERVICE.listar_recentes()}, 200


@bp.route("/api/pois", methods=["GET"])
@api_auth_required
def api_pois():
    """Busca paginada na base de POIs. Substitui a renderização dos ~17 mil
    POIs direto no HTML da página inicial (que gerava ~10 MB por acesso)."""
    termo = normalizar_busca(request.args.get("q", ""))
    try:
        limite = max(1, min(int(request.args.get("limite", 200)), 1000))
        deslocamento = max(0, int(request.args.get("deslocamento", 0)))
    except ValueError:
        return {"ok": False, "erro": "Parâmetros de paginação inválidos."}, 400

    pois = get_saved_pois()
    if termo:
        pois = [
            p for p in pois
            if termo in normalizar_busca(f"{p.get('nome', '')} {p.get('cidade', '')} {p.get('tipo', '')}")
        ]

    campos = ("id", "nome", "tipo", "cidade", "estado", "latitude", "longitude", "raio_metros")
    pagina = [{k: p.get(k) for k in campos} for p in pois[deslocamento:deslocamento + limite]]
    return {"ok": True, "total": len(pois), "dados": pagina}, 200


@bp.route("/api/veiculos", methods=["GET"])
@api_auth_required
def api_veiculos():
    return {"ok": True, "dados": VEICULOS_SERVICE.listar_veiculos()}, 200
