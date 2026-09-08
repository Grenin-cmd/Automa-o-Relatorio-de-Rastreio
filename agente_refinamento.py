from __future__ import annotations

from telemetry import track_event  # <-- Adicione aqui, na linha 3!
import hashlib
import json
import os
import sys
import threading
from typing import Any
from dotenv import load_dotenv

# Verifica se a biblioteca universal da OpenAI está instalada
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Timeout (ms) configurável
_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "15000"))
_TIMEOUT_SEC = _TIMEOUT_MS / 1000.0

# Cache simples em memória
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

def _extrair_texto_regra(regra: Any) -> str:
    """Extrai a string de descrição de uma regra."""
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
    def __init__(self) -> None:
        _carregar_env()
        # Lê as chaves do seu arquivo .env
        self.google_key = os.getenv("GEMINI_API_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")

        if not OpenAI:
            print("[IA STATUS] AVISO: Biblioteca 'openai' não encontrada. Instale com: pip install openai")

    def _chamar_ia_com_fallback(self, prompt: str, system_instruction: str | None = None, temperatura: float = 0.2) -> str | None:
        """
        Executa a cascata de IA: OpenRouter -> Google API -> Ollama Local.
        Garante que o sistema sempre retornará uma resposta se houver alguma opção disponível.
        """
        if not OpenAI:
            return None

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        # ---------------------------------------------------------
        # TENTATIVA 1: OpenRouter (Modelos Gratuitos)
        # ---------------------------------------------------------
        if self.openrouter_key:
            try:
                print("--> [IA] Tentando OpenRouter (gemini-2.0-flash-exp:free)...")
                client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=str(self.openrouter_key))
                resposta = client.chat.completions.create(
                    model="google/gemini-2.0-flash-exp:free",
                    messages=messages,
                    temperature=temperatura,
                    timeout=_TIMEOUT_SEC
                )
                if resposta.choices:
                    print("--> [IA SUCESSO] Resposta gerada via OpenRouter!")
                    return (resposta.choices[0].message.content or "").strip()
            except Exception as e:
                print(f"[IA FALHA OpenRouter]: {e}")

        # ---------------------------------------------------------
       # ---------------------------------------------------------
        # TENTATIVA 2: Google Gemini (API Direta compatível com OpenAI)
        # ---------------------------------------------------------
        if self.google_key:
            try:
                print("--> [IA] Tentando Google Gemini Direto (gemini-1.5-flash)...")
                client = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key=str(self.google_key))
                resposta = client.chat.completions.create(
                    model="gemini-1.5-flash",
                    messages=messages,
                    temperature=temperatura,
                    timeout=_TIMEOUT_SEC
                )
                if resposta.choices:
                    print("--> [IA SUCESSO] Resposta gerada via Google Gemini!")
                    track_event("geracao_ia_sucesso", {"provedor": "google_gemini"}) # ADICIONE ESTA LINHA
                    return (resposta.choices[0].message.content or "").strip()
            except Exception as e:
                print(f"[IA FALHA Google Gemini]: {e}")

        # ---------------------------------------------------------
        # TENTATIVA 3: Ollama Local (Totalmente Offline e Sem Limites)
        # ---------------------------------------------------------
        try:
            print("--> [IA] Tentando Ollama Local (llama3.2)...")
            client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
            resposta = client.chat.completions.create(
                model="llama3.2",
                messages=messages,
                temperature=temperatura,
                timeout=max(20.0, _TIMEOUT_SEC) 
            )
            if resposta.choices:
                print("--> [IA SUCESSO] Resposta gerada offline via Ollama!")
                return (resposta.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"[IA FALHA Ollama Local]: Servidor não está rodando ou modelo não encontrado. ({e})")

        # Se todas falharem, retorna None para ativar o Fallback Gracioso (Plano B) na interface
        track_event("falha_cascata_ia_critica", {"motivo": "todas_tentativas_falharam"}) # ADICIONE ESTA LINHA
        return None
    def refinar_relatorio(self, relatorio_bruto: str, regras: list[Any]) -> str:
        """Aplica as regras de negócio no relatório bruto usando a cascata de IAs."""
        if not relatorio_bruto or relatorio_bruto.strip() in ["", "Nenhum evento detectado."]:
            return relatorio_bruto

        if not regras:
            return relatorio_bruto

        linhas_regras: list[str] = []
        for idx, r in enumerate(regras, 1):
            texto_regra = _extrair_texto_regra(r)
            if texto_regra:
                linhas_regras.append(f"{idx}. {texto_regra}")

        if not linhas_regras:
            return relatorio_bruto

        regras_formatadas = "\n".join(linhas_regras)

        # Verifica cache
        cache_key = hashlib.sha256((relatorio_bruto + "||" + regras_formatadas).encode("utf-8")).hexdigest()
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

        resultado_ia = self._chamar_ia_com_fallback(
            prompt=prompt_conteudo, 
            system_instruction=system_instruction, 
            temperatura=0.1
        )

        if resultado_ia:
            self._salvar_no_cache(cache_key, resultado_ia)
            return resultado_ia

        # Se todas as IAs falharam, devolve o texto original para o sistema não quebrar
        return relatorio_bruto

    @staticmethod
    def _salvar_no_cache(cache_key: str, resultado: str) -> None:
        with _REFINAMENTO_CACHE_LOCK:
            if len(_REFINAMENTO_CACHE) >= _REFINAMENTO_CACHE_MAX_ITENS:
                _REFINAMENTO_CACHE.pop(next(iter(_REFINAMENTO_CACHE)))
            _REFINAMENTO_CACHE[cache_key] = resultado

    def gerar_resumo_auditoria(self, estatisticas: dict[str, Any]) -> str | None:
        """Gera um parágrafo executivo para a Auditoria de Roteiro usando a cascata."""
        amostra_pendentes = estatisticas.get("clientes_nao_executados", [])[:10]
        payload = {
            "total_planejado": estatisticas.get("total_planejado", 0),
            "total_executado": estatisticas.get("total_executado", 0),
            "total_nao_executado": estatisticas.get("total_nao_executado", 0),
            "total_sem_geolocalizacao": estatisticas.get("total_sem_geolocalizacao", 0),
            "percentual_execucao": estatisticas.get("percentual_execucao", 0),
            "amostra_clientes_pendentes": amostra_pendentes,
        }

        prompt = f"""Você é um analista de operações logísticas. Com base nos dados agregados
de uma auditoria de roteiro (entregas planejadas x executadas, cruzadas por
proximidade GPS), escreva um parágrafo executivo curto (máximo 4 frases,
sem markdown, em português) resumindo o desempenho da rota e destacando
riscos ou pontos de atenção.

DADOS AGREGADOS (JSON):
{json.dumps(payload, ensure_ascii=False)}"""

        # Como é um resumo criativo, usamos temperatura 0.2 sem instruction de sistema
        return self._chamar_ia_com_fallback(prompt=prompt, temperatura=0.2)


agente_ia = AgenteRefinamento()