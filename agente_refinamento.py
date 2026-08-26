from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from typing import Any
from dotenv import load_dotenv

# Timeout (ms) por tentativa de chamada ao Gemini. Sem isso, um modelo com alta
# demanda pode deixar a requisição HTTP do Flask pendurada por minutos (observado
# em testes: 503 retornado apenas após ~200s) antes de tentar o próximo fallback.
_GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "15000"))

# Cache simples em memória do resultado do refinamento, para evitar chamar a IA
# novamente quando o mesmo relatório bruto + o mesmo conjunto de regras já foram
# processados (ex: usuário atualiza a página ou repete a mesma ação). Isso evita
# bloquear o ciclo de resposta HTTP com uma chamada de rede redundante.
_REFINAMENTO_CACHE: dict[str, str] = {}
_REFINAMENTO_CACHE_LOCK = threading.Lock()
_REFINAMENTO_CACHE_MAX_ITENS = 64

def _carregar_env() -> None:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    env_file = os.path.join(base_dir, ".env")
    env_txt = os.path.join(base_dir, ".env.txt")

    if os.path.exists(env_file):
        load_dotenv(dotenv_path=env_file, override=True)
    elif os.path.exists(env_txt):
        load_dotenv(dotenv_path=env_txt, override=True)
    else:
        load_dotenv(override=True)

_carregar_env()

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None


def _extrair_texto_regra(regra: Any) -> str:
    """Extrai a string de descrição de uma regra, que pode chegar como:
    - str simples: "Sempre citar a placa"
    - str contendo JSON: '{"descricao": "Sempre citar a placa"}'
    - dict: {"descricao": "..."} (ou chaves alternativas "regra"/"texto")
    """
    if isinstance(regra, dict):
        valor = regra.get("descricao") or regra.get("regra") or regra.get("texto")
        if valor:
            return str(valor).strip()
        return str(regra).strip()

    if isinstance(regra, str):
        texto = regra.strip()
        if texto.startswith("{") and texto.endswith("}"):
            try:
                parsed = json.loads(texto)
                if isinstance(parsed, dict):
                    valor = parsed.get("descricao") or parsed.get("regra") or parsed.get("texto")
                    if valor:
                        return str(valor).strip()
            except (json.JSONDecodeError, TypeError):
                pass
        return texto

    return str(regra).strip()


class AgenteRefinamento:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = None
        self._conectar()

    def _conectar(self) -> None:
        if not self.api_key:
            _carregar_env()
            self.api_key = os.getenv("GEMINI_API_KEY")

        if genai and self.api_key and not self.client:
            try:
                # Define um timeout por requisição HTTP ao Gemini para que um modelo
                # "hanging" (alta demanda) não bloqueie o ciclo de resposta do Flask
                # por minutos; a chamada falha rápido e o fallback tenta o próximo modelo.
                http_options = genai_types.HttpOptions(timeout=_GEMINI_TIMEOUT_MS) if genai_types else None
                self.client = genai.Client(api_key=self.api_key, http_options=http_options)
                print("[IA STATUS] Google Gemini conectado com sucesso.")
            except Exception as e:
                print(f"[IA STATUS] Erro ao instanciar Gemini: {e}")

    def refinar_relatorio(self, relatorio_bruto: str, regras: list[Any]) -> str:
        if not relatorio_bruto or relatorio_bruto.strip() in ["", "Nenhum evento detectado."]:
            return relatorio_bruto

        if not self.client:
            self._conectar()

        if not self.client or not regras:
            print(f"[IA AVISO] Refinamento ignorado: client={bool(self.client)}, regras={len(regras) if regras else 0}")
            return relatorio_bruto

        linhas_regras: list[str] = []
        for idx, r in enumerate(regras, 1):
            texto_regra = _extrair_texto_regra(r)
            if texto_regra:
                linhas_regras.append(f"{idx}. {texto_regra}")

        if not linhas_regras:
            return relatorio_bruto

        regras_formatadas = "\n".join(linhas_regras)

        # Evita chamar a IA de novo para o mesmo texto bruto + mesmo conjunto de
        # regras (ex: recarregamento de página, nova aba com os mesmos dados).
        cache_key = hashlib.sha256(
            (relatorio_bruto + "||" + regras_formatadas).encode("utf-8")
        ).hexdigest()
        with _REFINAMENTO_CACHE_LOCK:
            cached = _REFINAMENTO_CACHE.get(cache_key)
        if cached is not None:
            print("--> [IA CACHE] Resultado reaproveitado do cache em memória.")
            return cached
        system_instruction = (
            "Você é um auditor e formatador de relatórios de rastreamento veicular. "
            "Sua única tarefa é reescrever o texto fornecido aplicando rigorosamente todas as regras de negócio listadas."
        )

        prompt_conteudo = f"""REGRAS OBRIGATÓRIAS (APLIQUE TODAS):
{regras_formatadas}

TEXTO ORIGINAL:
{relatorio_bruto}

INSTRUÇÕES:
- Aplique todas as regras acima com rigor.
- Retorne apenas o texto final refinado e formatado."""

        # Lista de modelos em ordem de preferência. A Google descontinua IDs de modelo
        # com o tempo (ex: gemini-2.5-flash/pro e gemini-2.0-flash retornam 404 para
        # contas novas). Priorizamos o modelo estável mais atual disponível na API e
        # mantemos aliases "-latest" e nomes antigos como fallback para contas onde
        # eles ainda funcionem.
        modelos = [
            "gemini-3.6-flash",
            "gemini-flash-latest",
            "gemini-pro-latest",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
        ]

        for modelo in modelos:
            try:
                print(f"--> [IA] Tentando refinamento com {modelo}...")
                response = self.client.models.generate_content(
                    model=modelo,
                    contents=prompt_conteudo,
                    config={
                        "system_instruction": system_instruction,
                        "temperature": 0.1,
                    },
                )
                if response and hasattr(response, "text") and response.text:
                    print(f"--> [IA SUCESSO] Relatório refinado usando {modelo}!")
                    resultado = response.text.strip()
                    self._salvar_no_cache(cache_key, resultado)
                    return resultado
            except Exception as e:
                print(f"[IA FALHA {modelo}]: {e}")
                continue

        return relatorio_bruto

    @staticmethod
    def _salvar_no_cache(cache_key: str, resultado: str) -> None:
        with _REFINAMENTO_CACHE_LOCK:
            if len(_REFINAMENTO_CACHE) >= _REFINAMENTO_CACHE_MAX_ITENS:
                # Remove a entrada mais antiga (FIFO simples) para não crescer
                # indefinidamente a memória do processo.
                _REFINAMENTO_CACHE.pop(next(iter(_REFINAMENTO_CACHE)))
            _REFINAMENTO_CACHE[cache_key] = resultado


agente_ia = AgenteRefinamento()