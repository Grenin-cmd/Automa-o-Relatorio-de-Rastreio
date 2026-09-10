"""
LEITOR UNIVERSAL DE RASTREAMENTO
=================================

Converte dados de qualquer fonte/empresa para o formato interno (EventoRastreamento).
Detecta automaticamente as colunas e adapta-se a variações de formato.
"""

from __future__ import annotations
import pandas as pd
import unicodedata
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from schema_universal import (
    EventoRastreamento,
    ConfiguracaoFonteRastreio,
    obter_configuracao,
    CONFIG_GENERICA,
)


class DetectorColuna:
    """Detecta automaticamente colunas de um DataFrame"""
    
    @staticmethod
    def normalizar_nome(nome: str) -> str:
        """Normaliza nome de coluna para comparação"""
        nome = str(nome).strip().lower()
        nome = unicodedata.normalize("NFKD", nome)
        nome = "".join(ch for ch in nome if not unicodedata.combining(ch))
        nome = re.sub(r"[^a-z0-9_]", "", nome)
        return nome
    
    @staticmethod
    def encontrar_coluna(
        df: pd.DataFrame,
        aliases: List[str],
        obrigatorio: bool = False
    ) -> Optional[str]:
        """
        Encontra uma coluna no DataFrame usando lista de aliases.
        
        Args:
            df: DataFrame para buscar
            aliases: Lista de nomes possíveis para a coluna
            obrigatorio: Se True, lança exceção se não encontrar
        
        Returns:
            Nome real da coluna ou None
        """
        colunas_norm = {
            DetectorColuna.normalizar_nome(col): col for col in df.columns
        }
        
        for alias in aliases:
            alias_norm = DetectorColuna.normalizar_nome(alias)
            if alias_norm in colunas_norm:
                return colunas_norm[alias_norm]
        
        if obrigatorio:
            raise ValueError(
                f"Coluna não encontrada. Esperava uma de: {aliases}\n"
                f"Colunas disponíveis: {list(df.columns)}"
            )
        return None


class TransformadorDados:
    """Transforma dados brutos para tipos esperados"""
    
    @staticmethod
    def converter_data_hora(valor: Any) -> Optional[datetime]:
        """Converte diferentes formatos de data para datetime"""
        if valor is None or pd.isna(valor):
            return None
        
        if isinstance(valor, datetime):
            return valor
        
        texto = str(valor).strip()
        
        # Lista de formatos a tentar
        formatos = [
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y",
            "%Y-%m-%d",
        ]
        
        for fmt in formatos:
            try:
                return datetime.strptime(texto, fmt)
            except ValueError:
                continue
        
        # Última tentativa: deixar pandas interpretar
        try:
            return pd.to_datetime(texto, dayfirst=True)
        except Exception:
            return None
    
    @staticmethod
    def converter_velocidade(valor: Any) -> Optional[float]:
        """Converte diferentes formatos de velocidade para float (km/h)"""
        if valor is None or pd.isna(valor):
            return None
        
        try:
            # Extrai número da string se necessário
            texto = str(valor).strip()
            match = re.search(r"(-?\d+(?:[.,]\d+)?)", texto)
            if match:
                numero_texto = match.group(1).replace(",", ".")
                return float(numero_texto)
            return float(texto)
        except (ValueError, AttributeError):
            return None
    
    @staticmethod
    def converter_coordenada(valor: Any) -> Optional[float]:
        """Converte diferentes formatos de latitude/longitude para float"""
        if valor is None or pd.isna(valor):
            return None
        
        try:
            texto = str(valor).strip()
            # Remove espaços e normaliza pontos/vírgulas
            texto = texto.replace(" ", "").replace(",", ".")
            # Extrai número
            match = re.search(r"(-?\d+(?:\.\d+)?)", texto)
            if match:
                return float(match.group(1))
            return float(texto)
        except (ValueError, AttributeError):
            return None
    
    @staticmethod
    def normalizar_placa(valor: Any) -> Optional[str]:
        """Normaliza placa para formato padrão"""
        if valor is None or pd.isna(valor):
            return None
        
        placa = str(valor).strip().upper()
        # Remove caracteres especiais comuns
        placa = re.sub(r"[^A-Z0-9-]", "", placa)
        return placa if placa else None


class LeitorRastreamento:
    """Leitor universal que converte dados de qualquer fonte para formato padrão"""
    
    def __init__(self, configuracao: Optional[ConfiguracaoFonteRastreio] = None):
        """
        Inicializa o leitor
        
        Args:
            configuracao: Configuração da fonte. Se None, usa detecção automática.
        """
        self.config = configuracao or CONFIG_GENERICA
        self.detector = DetectorColuna()
        self.transformador = TransformadorDados()
    
    def ler_arquivo(self, caminho: str) -> pd.DataFrame:
        """Lê arquivo CSV ou Excel e retorna DataFrame normalizado"""
        if caminho.endswith(".csv"):
            # Tenta diferentes encodings
            for encoding in ["utf-8", "latin-1", "cp1252"]:
                try:
                    df = pd.read_csv(caminho, encoding=encoding)
                    return self._normalizar_colunas(df)
                except UnicodeDecodeError:
                    continue
            raise ValueError(f"Não foi possível decodificar {caminho}")
        
        elif caminho.endswith((".xlsx", ".xls")):
            df = pd.read_excel(caminho)
            return self._normalizar_colunas(df)
        
        else:
            raise ValueError("Formato não suportado. Use CSV ou Excel.")
    
    def _normalizar_colunas(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza nomes de colunas para detecção"""
        df = df.copy()
        df.columns = [str(col).strip() for col in df.columns]
        return df
    
    def converter_para_eventos(
        self,
        df: pd.DataFrame,
        nome_fonte: str = "GENERICA"
    ) -> List[EventoRastreamento]:
        """
        Converte DataFrame para lista de EventoRastreamento
        
        Args:
            df: DataFrame com dados de rastreamento
            nome_fonte: Identificação da fonte (SS_TELEMATICA, VIVO, etc)
        
        Returns:
            Lista de EventoRastreamento convertidos
        """
        df = self._normalizar_colunas(df)
        
        # Se não temos configuração específica, tenta auto-detectar
        if self.config.nome_fonte == "GENERICA":
            self.config = self._detectar_configuracao(df)
        
        # Encontra as colunas críticas
        col_placa = self.detector.encontrar_coluna(
            df, self.config.aliases_colunas.get("placa", ["placa"]), obrigatorio=True
        )
        col_data_hora = self.detector.encontrar_coluna(
            df, self.config.aliases_colunas.get("data_hora", ["data_hora"]), obrigatorio=True
        )
        col_velocidade = self.detector.encontrar_coluna(
            df, self.config.aliases_colunas.get("velocidade_kmh", ["velocidade"]), obrigatorio=True
        )
        
        # Encontra colunas opcionais
        col_endereco = self.detector.encontrar_coluna(
            df, self.config.aliases_colunas.get("endereco", [])
        )
        col_latitude = self.detector.encontrar_coluna(
            df, self.config.aliases_colunas.get("latitude", [])
        )
        col_longitude = self.detector.encontrar_coluna(
            df, self.config.aliases_colunas.get("longitude", [])
        )
        
        eventos = []
        erros = []
        
        for idx, row in df.iterrows():
            try:
                evento = self._converter_linha(
                    row,
                    col_placa, col_data_hora, col_velocidade,
                    col_endereco, col_latitude, col_longitude,
                    nome_fonte
                )
                if evento:
                    eventos.append(evento)
            except Exception as e:
                erros.append(f"Linha {idx + 2}: {str(e)}")
        
        if erros:
            print(f"[AVISO] {len(erros)} linhas não puderam ser convertidas:")
            for erro in erros[:5]:  # Mostra apenas os 5 primeiros
                print(f"  - {erro}")
            if len(erros) > 5:
                print(f"  ... e mais {len(erros) - 5} erros")
        
        print(f"[OK] {len(eventos)} eventos convertidos com sucesso")
        return eventos
    
    def _converter_linha(
        self,
        row: pd.Series,
        col_placa: str,
        col_data_hora: str,
        col_velocidade: str,
        col_endereco: Optional[str],
        col_latitude: Optional[str],
        col_longitude: Optional[str],
        nome_fonte: str
    ) -> Optional[EventoRastreamento]:
        """Converte uma linha do DataFrame para EventoRastreamento"""
        
        # Extrai campos obrigatórios
        placa = self.transformador.normalizar_placa(row[col_placa])
        if not placa:
            raise ValueError(f"Placa inválida: {row[col_placa]}")
        
        data_hora = self.transformador.converter_data_hora(row[col_data_hora])
        if not data_hora:
            raise ValueError(f"Data/Hora inválida: {row[col_data_hora]}")
        
        velocidade = self.transformador.converter_velocidade(row[col_velocidade])
        if velocidade is None:
            raise ValueError(f"Velocidade inválida: {row[col_velocidade]}")
        
        # Extrai campos opcionais
        endereco = None
        if col_endereco and pd.notna(row[col_endereco]):
            endereco = str(row[col_endereco]).strip()
        
        latitude = None
        if col_latitude and pd.notna(row[col_latitude]):
            latitude = self.transformador.converter_coordenada(row[col_latitude])
        
        longitude = None
        if col_longitude and pd.notna(row[col_longitude]):
            longitude = self.transformador.converter_coordenada(row[col_longitude])
        
        # Cria evento
        evento = EventoRastreamento(
            evento_id="",  # Será gerado automaticamente
            placa=placa,
            data_hora=data_hora,
            velocidade_kmh=velocidade,
            endereco=endereco,
            latitude=latitude,
            longitude=longitude,
            fonte=nome_fonte,
            metadata=row.to_dict()
        )
        
        return evento
    
    def _detectar_configuracao(self, df: pd.DataFrame) -> ConfiguracaoFonteRastreio:
        """Tenta detectar qual fonte os dados vêm baseado nas colunas"""
        colunas_norm = {
            DetectorColuna.normalizar_nome(col) for col in df.columns
        }
        
        # Se encontrar padrão SS Telemática
        if any(alias in colunas_norm for alias in ["ss", "telematica", "ss_telematica"]):
            return obter_configuracao("SS_TELEMATICA")
        
        # Se encontrar padrão Vivo
        if any(alias in colunas_norm for alias in ["vivo", "tracker", "vivo_tracker"]):
            return obter_configuracao("VIVO")
        
        # Se encontrar padrão TIM
        if any(alias in colunas_norm for alias in ["tim", "connect", "tim_connect"]):
            return obter_configuracao("TIM")
        
        # Padrão genérico (mais comum)
        return CONFIG_GENERICA
    
    def validar_dados(self, eventos: List[EventoRastreamento]) -> Dict[str, Any]:
        """Valida e retorna estatísticas dos dados convertidos"""
        stats = {
            "total_eventos": len(eventos),
            "eventos_validos": 0,
            "eventos_sem_localizacao": 0,
            "placas_unicas": set(),
            "data_min": None,
            "data_max": None,
            "avisos": []
        }
        
        for evento in eventos:
            if evento.tem_localizacao_valida():
                stats["eventos_validos"] += 1
            else:
                stats["eventos_sem_localizacao"] += 1
            
            stats["placas_unicas"].add(evento.placa)
            
            if not stats["data_min"] or evento.data_hora < stats["data_min"]:
                stats["data_min"] = evento.data_hora
            if not stats["data_max"] or evento.data_hora > stats["data_max"]:
                stats["data_max"] = evento.data_hora
        
        stats["placas_unicas"] = list(stats["placas_unicas"])
        
        if stats["eventos_sem_localizacao"] > 0:
            pct = (stats["eventos_sem_localizacao"] / stats["total_eventos"]) * 100
            stats["avisos"].append(
                f"{stats['eventos_sem_localizacao']} eventos ({pct:.1f}%) sem localização"
            )
        
        return stats


# Função conveniência
def ler_rastreamento(
    caminho: str,
    nome_fonte: str = "GENERICA"
) -> Tuple[List[EventoRastreamento], Dict[str, Any]]:
    """
    Função simplificada para ler um arquivo de rastreamento
    
    Args:
        caminho: Caminho do arquivo CSV ou Excel
        nome_fonte: Nome da fonte (SS_TELEMATICA, VIVO, TIM, GENERICA)
    
    Returns:
        Tupla (lista_eventos, estatísticas)
    """
    config = obter_configuracao(nome_fonte)
    leitor = LeitorRastreamento(config)
    
    df = leitor.ler_arquivo(caminho)
    eventos = leitor.converter_para_eventos(df, nome_fonte)
    stats = leitor.validar_dados(eventos)
    
    return eventos, stats