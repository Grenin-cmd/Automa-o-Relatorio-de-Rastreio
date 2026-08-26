from __future__ import annotations

import os
import sys
import time
from typing import Any
from dotenv import load_dotenv

# Localiza a pasta onde o .exe está rodando no Windows
def _carregar_variaveis_ambiente() -> None:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    caminho_env = os.path.join(base_dir, ".env")
    caminho_env_txt = os.path.join(base_dir, ".env.txt")

    if os.path.exists(caminho_env):
        load_dotenv(dotenv_path=caminho_env, override=True)
    elif os.path.exists(caminho_env_txt):
        load_dotenv(dotenv_path=caminho_env_txt, override=True)
    else:
        load_dotenv(override=True)

_carregar_variaveis_ambiente()

try:
    from google import genai
except ImportError:
    genai = None


class AgenteRefinamento:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = None
        self._inicializar_cliente()

    def _inicializar_cliente(self) -> None:
        if not self.api_key:
            _carregar_variaveis_ambiente()
            self.api_key = os.getenv("GEMINI_API_KEY")

        if genai and self.api_key and not self.client:
            try:
                self.client = genai.Client(api_key=self.api_key)
                print("[IA STATUS] Google Gemini conectado com sucesso.")
            except Exception as e:
                print(f"[IA STATUS] Erro ao instanciar Gemini: {e}")
        elif not self.api_key:
            print("[IA STATUS] AVISO: GEMINI_API_KEY nao encontrada no .env")

    def refinar_relatorio(self, relatorio_bruto: str, regras: list[dict[str, Any]]) -> str:
        if not relatorio_bruto or relatorio_bruto == "Nenhum evento detectado.":
            return relatorio_bruto

        if not self.client:
            self._inicializar_cliente()

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

        modelos_disponiveis = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
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