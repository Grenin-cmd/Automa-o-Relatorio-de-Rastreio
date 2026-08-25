from __future__ import annotations

import os
import time
from typing import Any
from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
except ImportError:
    genai = None


class AgenteRefinamento:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = None
        if genai and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
                print("[IA STATUS] Cliente Google Gemini conectado com sucesso.")
            except Exception as e:
                print(f"[IA STATUS] Erro ao instanciar Gemini: {e}")

    def refinar_relatorio(self, relatorio_bruto: str, regras: list[dict[str, Any]]) -> str:
        if not relatorio_bruto or relatorio_bruto == "Nenhum evento detectado.":
            return relatorio_bruto

        if not self.client or not regras:
            return relatorio_bruto

        linhas_regras = [f"{idx}. {r.get('descricao')}" for idx, r in enumerate(regras, 1) if r.get("descricao")]
        regras_formatadas = "\n".join(linhas_regras)

        system_instruction = (
            "Você é um auditor de relatórios de rastreamento veicular. "
            "Sua única tarefa é reescrever o texto fornecido aplicando rigorosamente todas as regras de negócio listadas."
        )

        prompt_conteudo = f"""REGRAS OBRIGATÓRIAS (APLIQUE TODAS):
{regras_formatadas}

TEXTO ORIGINAL:
{relatorio_bruto}

INSTRUÇÕES:
- Aplique todas as regras acima (ex: negrito, alterações de termos, placas específicas, pontuação final).
- Retorne apenas o texto refinado final."""

        # Modelos ativos sugeridos pelo Google
        modelos_disponiveis = [
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
        ]

        for nome_modelo in modelos_disponiveis:
            try:
                response = self.client.models.generate_content(
                    model=nome_modelo,
                    contents=prompt_conteudo,
                    config={
                        "system_instruction": system_instruction,
                        "temperature": 0.1,
                    },
                )
                if response and hasattr(response, "text") and response.text:
                    return response.text.strip()
            except Exception as e:
                print(f"[FALHA NO MODELO {nome_modelo}]: {e}")
                continue

        return relatorio_bruto


agente_ia = AgenteRefinamento()