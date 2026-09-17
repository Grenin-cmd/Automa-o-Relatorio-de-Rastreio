"""
SCHEMA UNIVERSAL DE RASTREAMENTO
================================

Define a estrutura padrão interna do sistema, independente da fonte de dados.
Qualquer empresa de rastreio precisa ser convertida para este formato.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
import uuid


@dataclass
class EventoRastreamento:
    """Evento atômico de rastreamento - formato universal"""
    
    # Identificadores
    evento_id: str  # UUID único para cada evento
    placa: str  # Identificação do veículo (obrigatório)
    
    # Timestamp
    data_hora: datetime  # Data e hora do evento (obrigatório)
    
    # Localização
    latitude: Optional[float] = None  # Pode vir de coordenadas ou ser extraído de endereço
    longitude: Optional[float] = None
    endereco: Optional[str] = None  # Pode ser um endereço em texto ou coordenadas
    
    # Movimento
    velocidade_kmh: Optional[float] = None  # (obrigatório)
    
    # Origem dos dados
    fonte: str = "GENERICA"  # SS_TELEMATICA, VIVO, TIM, RASTREADOR_XYZ, etc
    metadata: Optional[Dict[str, Any]] = None  # Campos adicionais da fonte original
    
    def __post_init__(self):
        """Valida dados obrigatórios após inicialização"""
        if not self.placa or not self.placa.strip():
            raise ValueError("Placa é obrigatória")
        if not self.data_hora:
            raise ValueError("Data/Hora é obrigatória")
        if self.velocidade_kmh is None:
            raise ValueError("Velocidade é obrigatória")
        
        # Normaliza placa
        self.placa = self.placa.strip().upper()
        
        # Gera ID único se não tiver
        if not self.evento_id:
            self.evento_id = str(uuid.uuid4())
        
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário"""
        data = asdict(self)
        data['data_hora'] = self.data_hora.isoformat() if self.data_hora else None
        return data
    
    def tem_localizacao_valida(self) -> bool:
        """Verifica se tem coordenadas ou endereço"""
        tem_coords = self.latitude is not None and self.longitude is not None
        tem_endereco = self.endereco is not None and len(self.endereco.strip()) > 0
        return tem_coords or tem_endereco
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EventoRastreamento:
        """Cria evento a partir de dicionário"""
        if isinstance(data.get('data_hora'), str):
            data['data_hora'] = datetime.fromisoformat(data['data_hora'])
        
        # Remove campos extras
        campos_validos = {f.name for f in cls.__dataclass_fields__.values()}
        data_limpa = {k: v for k, v in data.items() if k in campos_validos}
        
        return cls(**data_limpa)


@dataclass
class ConfiguracaoFonteRastreio:
    """
    Define como mapear dados de uma fonte específica para EventoRastreamento.
    Cada empresa/provedor de rastreio precisa de uma configuração.
    """
    
    nome_fonte: str  # Ex: "SS_TELEMATICA", "VIVO_TRACKER", "TIM_CONNECT"
    descricao: Optional[str] = None
    
    # Mapeamento de colunas: chave = coluna no CSV, valor = campo em EventoRastreamento
    mapa_colunas: Optional[Dict[str, str]] = None
    
    # Aliases: diferentes nomes para a mesma coluna (ex: ["placa", "plate", "vehicle_id"])
    aliases_colunas: Optional[Dict[str, List[str]]] = None
    
    # Regras de validação customizadas por fonte
    validacoes: Optional[Dict[str, Callable[[Any], Any]]] = None
    
    # Transformações customizadas (ex: converter formato de data, unidade de velocidade)
    transformacoes: Optional[Dict[str, Callable[[Any], Any]]] = None
    
    # Exemplo de mapeamento esperado:
    # {
    #     "placa": ["Placa", "plate", "vehicle_id"],
    #     "data_hora": ["Timestamp", "data_hora", "datetime"],
    #     "velocidade_kmh": ["Velocidade", "speed_kmh", "vel_kmh"],
    #     "endereco": ["Localização", "Endereco", "address"],
    #     "latitude": ["Lat", "Latitude"],
    #     "longitude": ["Lon", "Longitude"]
    # }
    
    def __post_init__(self):
        if self.mapa_colunas is None:
            self.mapa_colunas = {}
        if self.aliases_colunas is None:
            self.aliases_colunas = {}
        if self.validacoes is None:
            self.validacoes = {}
        if self.transformacoes is None:
            self.transformacoes = {}
    
    def validar(self) -> bool:
        """Verifica se a configuração tem os campos obrigatórios mapeados"""
        campos_obrigatorios = {"placa", "data_hora", "velocidade_kmh"}
        campos_mapeados = set(self.mapa_colunas.keys())
        return campos_obrigatorios.issubset(campos_mapeados)


# CONFIGURAÇÕES PRÉ-DEFINIDAS

CONFIG_SS_TELEMATICA = ConfiguracaoFonteRastreio(
    nome_fonte="SS_TELEMATICA",
    descricao="Rastreamento SS Telemática",
    aliases_colunas={
        "placa": ["Placa", "plate", "vehicle"],
        "data_hora": ["Timestamp", "Data/Hora", "datetime", "data_hora"],
        "velocidade_kmh": ["Velocidade", "speed_kmh", "vel_kmh", "velocidade"],
        "endereco": ["Localização", "Endereco", "address", "location"],
        "latitude": ["Latitude", "Lat", "lat"],
        "longitude": ["Longitude", "Lon", "lon"],
    }
)

CONFIG_GENERICA = ConfiguracaoFonteRastreio(
    nome_fonte="GENERICA",
    descricao="Configuração genérica com detecção automática",
    aliases_colunas={
        "placa": ["placa", "plate", "vehicle", "veiculo", "id_veiculo"],
        "data_hora": ["data_hora", "timestamp", "datetime", "data", "hora", "date_time"],
        "velocidade_kmh": ["velocidade", "speed_kmh", "vel_kmh", "speed", "velocidade_kmh"],
        "endereco": ["endereco", "address", "localizacao", "location", "local"],
        "latitude": ["latitude", "lat", "latitude_coord"],
        "longitude": ["longitude", "lon", "longitude_coord"],
    }
)

CONFIG_VIVO = ConfiguracaoFonteRastreio(
    nome_fonte="VIVO_TRACKER",
    descricao="Sistema Vivo Rastreador",
    aliases_colunas={
        "placa": ["placa_veiculo", "placa", "vehicle_id"],
        "data_hora": ["data_evento", "timestamp", "datetime"],
        "velocidade_kmh": ["vel_kmh", "speed"],
        "endereco": ["endereco_evento", "address"],
        "latitude": ["latitude"],
        "longitude": ["longitude"],
    }
)

CONFIG_TIM = ConfiguracaoFonteRastreio(
    nome_fonte="TIM_CONNECT",
    descricao="Sistema TIM Connect",
    aliases_colunas={
        "placa": ["id_veiculo", "placa"],
        "data_hora": ["data_posicao", "timestamp"],
        "velocidade_kmh": ["velocidade"],
        "endereco": ["endereco_aproximado", "endereco"],
        "latitude": ["lat"],
        "longitude": ["lon"],
    }
)

# Registro de todas as configurações disponíveis
CONFIGURACOES_DISPONIVEIS = {
    "SS_TELEMATICA": CONFIG_SS_TELEMATICA,
    "VIVO": CONFIG_VIVO,
    "TIM": CONFIG_TIM,
    "GENERICA": CONFIG_GENERICA,
}


def obter_configuracao(nome: str) -> ConfiguracaoFonteRastreio:
    """Obtém configuração por nome"""
    config = CONFIGURACOES_DISPONIVEIS.get(nome.upper())
    if not config:
        print(f"[AVISO] Configuração '{nome}' não encontrada. Usando GENERICA")
        return CONFIG_GENERICA
    return config


def listar_fontes_disponiveis() -> List[str]:
    """Lista todas as fontes de rastreio disponíveis"""
    return list(CONFIGURACOES_DISPONIVEIS.keys())