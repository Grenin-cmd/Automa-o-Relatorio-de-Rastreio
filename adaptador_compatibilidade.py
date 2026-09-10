"""
ADAPTADOR DE COMPATIBILIDADE
============================

Integra o novo leitor universal com o sistema existente (analisador_rastreio).
Permite usar ambos os sistemas em paralelo durante a transição.
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
import pandas as pd
from schema_universal import EventoRastreamento
from leitor_universal import LeitorRastreamento, obter_configuracao


class AdaptadorParaRastreamento:
    """Adapta EventoRastreamento para formato esperado por RastreamentoAnalyzer"""
    
    @staticmethod
    def evento_para_dict(evento: EventoRastreamento) -> Dict[str, Any]:
        """
        Converte EventoRastreamento para dicionário compatível com RastreamentoAnalyzer
        """
        return {
            "placa": evento.placa,
            "timestamp": evento.data_hora,
            "data_hora": evento.data_hora,
            "velocidade": evento.velocidade_kmh,
            "velocidade_kmh": evento.velocidade_kmh,
            "latitude": evento.latitude,
            "longitude": evento.longitude,
            "endereco": evento.endereco,
            "localizacao": evento.endereco,
            "fonte": evento.fonte,
            "evento_id": evento.evento_id,
        }
    
    @staticmethod
    def eventos_para_dataframe(eventos: List[EventoRastreamento]) -> pd.DataFrame:
        """
        Converte lista de eventos para DataFrame compatível com sistema antigo
        """
        dados = [AdaptadorParaRastreamento.evento_para_dict(e) for e in eventos]
        df = pd.DataFrame(dados)
        
        # Garante que as colunas esperadas existem
        colunas_essenciais = ["placa", "timestamp", "velocidade_kmh", "latitude", "longitude"]
        for col in colunas_essenciais:
            if col not in df.columns:
                df[col] = None
        
        return df
    
    @staticmethod
    def validar_compatibilidade(df: pd.DataFrame) -> Dict[str, Any]:
        """Verifica se DataFrame é compatível com ambos os sistemas"""
        
        # Colunas obrigatórias do novo sistema
        colunas_novo = {"placa", "timestamp", "velocidade_kmh"}
        
        # Colunas do sistema antigo
        colunas_antigo = {"Placa", "Timestamp", "Velocidade", "Latitude", "Longitude"}
        
        # Normaliza nomes de coluna para verificação
        colunas_presentes = {str(c).lower().strip() for c in df.columns}
        
        resultado = {
            "compativel_novo": all(c in colunas_presentes for c in colunas_novo),
            "compativel_antigo": len(colunas_antigo & set(df.columns)) >= 4,
            "colunas_encontradas": list(df.columns),
            "colunas_faltando": []
        }
        
        if not resultado["compativel_novo"] and not resultado["compativel_antigo"]:
            resultado["colunas_faltando"] = list(colunas_novo - colunas_presentes)
        
        return resultado


class GerenciadorFontes:
    """Gerencia múltiplas fontes de rastreamento simultaneamente"""
    
    def __init__(self):
        self.leitores: Dict[str, LeitorRastreamento] = {}
        self.eventos_por_fonte: Dict[str, List[EventoRastreamento]] = {}
    
    def registrar_fonte(self, nome: str, configuracao: Optional[Any] = None):
        """Registra uma nova fonte de rastreamento"""
        config = configuracao or obter_configuracao(nome)
        self.leitores[nome] = LeitorRastreamento(config)
        self.eventos_por_fonte[nome] = []
        print(f"[OK] Fonte '{nome}' registrada")
    
    def processar_arquivo(self, nome_fonte: str, caminho: str) -> Dict[str, Any]:
        """Processa um arquivo de uma fonte registrada"""
        
        if nome_fonte not in self.leitores:
            self.registrar_fonte(nome_fonte)
        
        leitor = self.leitores[nome_fonte]
        
        try:
            df = leitor.ler_arquivo(caminho)
            eventos = leitor.converter_para_eventos(df, nome_fonte)
            stats = leitor.validar_dados(eventos)
            
            self.eventos_por_fonte[nome_fonte] = eventos
            
            return {
                "sucesso": True,
                "eventos": eventos,
                "estatisticas": stats,
                "mensagem": f"Processados {len(eventos)} eventos de {nome_fonte}"
            }
        
        except Exception as e:
            return {
                "sucesso": False,
                "eventos": [],
                "estatisticas": {},
                "mensagem": f"Erro ao processar arquivo: {str(e)}"
            }
    
    def obter_todos_eventos(self, ordem_cronologica: bool = True) -> List[EventoRastreamento]:
        """Retorna eventos de todas as fontes"""
        todos = []
        for eventos in self.eventos_por_fonte.values():
            todos.extend(eventos)
        
        if ordem_cronologica:
            todos.sort(key=lambda e: e.data_hora)
        
        return todos
    
    def obter_eventos_por_placa(self, placa: str) -> List[EventoRastreamento]:
        """Retorna eventos de uma placa específica"""
        todos = self.obter_todos_eventos()
        placa_norm = placa.strip().upper()
        return [e for e in todos if e.placa == placa_norm]
    
    def exportar_para_dataframe(self) -> pd.DataFrame:
        """Exporta todos os eventos para DataFrame único"""
        eventos = self.obter_todos_eventos(ordem_cronologica=True)
        return AdaptadorParaRastreamento.eventos_para_dataframe(eventos)
    
    def gerar_relatorio_fontes(self) -> Dict[str, Any]:
        """Gera relatório sobre todas as fontes processadas"""
        relatorio = {
            "total_fontes": len(self.leitores),
            "fontes": {}
        }
        
        for nome_fonte, eventos in self.eventos_por_fonte.items():
            if eventos:
                relatorio["fontes"][nome_fonte] = {
                    "total_eventos": len(eventos),
                    "placas_unicas": len(set(e.placa for e in eventos)),
                    "periodo": {
                        "inicio": min(e.data_hora for e in eventos),
                        "fim": max(e.data_hora for e in eventos),
                    },
                    "fonte": eventos[0].fonte if eventos else None
                }
        
        return relatorio


class MigradorDados:
    """Facilita a migração de dados do sistema antigo para o novo"""
    
    @staticmethod
    def migrar_de_dataframe(
        df: pd.DataFrame,
        nome_fonte: str = "GENERICA"
    ) -> List[EventoRastreamento]:
        """Migra DataFrame antigo para novo formato"""
        
        leitor = LeitorRastreamento(obter_configuracao(nome_fonte))
        df_normalizado = leitor._normalizar_colunas(df)
        eventos = leitor.converter_para_eventos(df_normalizado, nome_fonte)
        
        return eventos
    
    @staticmethod
    def comparar_formatos(df_antigo: pd.DataFrame, df_novo: pd.DataFrame) -> Dict[str, Any]:
        """Compara estrutura de dois formatos"""
        
        return {
            "colunas_antigas": list(df_antigo.columns),
            "colunas_novas": list(df_novo.columns),
            "linhas_antigas": len(df_antigo),
            "linhas_novas": len(df_novo),
            "compatibilidade": AdaptadorParaRastreamento.validar_compatibilidade(df_antigo)
        }


# Exemplo de uso

def exemplo_uso():
    """Exemplo de como usar o novo sistema"""
    
    print("=" * 60)
    print("EXEMPLO: Sistema Genérico de Rastreamento")
    print("=" * 60)
    
    # 1. Criar gerenciador de fontes
    gerenciador = GerenciadorFontes()
    
    # 2. Registrar múltiplas fontes
    gerenciador.registrar_fonte("SS_TELEMATICA")
    gerenciador.registrar_fonte("VIVO")
    gerenciador.registrar_fonte("GENERICA")  # Para dados desconhecidos
    
    # 3. Processar arquivos de diferentes fontes
    # resultado_ss = gerenciador.processar_arquivo("SS_TELEMATICA", "dados_ss.csv")
    # resultado_vivo = gerenciador.processar_arquivo("VIVO", "dados_vivo.csv")
    
    # 4. Obter todos os eventos em ordem cronológica
    # todos_eventos = gerenciador.obter_todos_eventos()
    
    # 5. Buscar eventos de uma placa específica
    # eventos_placa = gerenciador.obter_eventos_por_placa("ABC-1234")
    
    # 6. Exportar para DataFrame (compatível com sistema antigo)
    # df_unificado = gerenciador.exportar_para_dataframe()
    
    # 7. Usar com RastreamentoAnalyzer
    # analyzer = RastreamentoAnalyzer(pois=[...])
    # relatorio = analyzer.gerar_relatorio(df_unificado)
    
    print("\n✅ Sistema pronto para receber dados de múltiplas fontes!")
    print("✅ Compatível com sistema antigo via adaptador!")
    print("✅ Preparado para integração com chip/API!")


if __name__ == "__main__":
    exemplo_uso()