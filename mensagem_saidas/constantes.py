"""Limiares das regras da mensagem de saídas (ver spec 2026-11-27)."""

VEL_PARADO_KMH = 3                   # registro parado se velocidade <= este valor
MERGE_DIST_M = 1500                  # manobra: deslocamento máximo entre paradas unificadas
MERGE_MOVIMENTO_MIN = 15             # manobra: tempo máximo em movimento entre paradas unificadas
MIN_POSTO_MIN = 30                   # postos/restaurantes só entram com parada >= isto
MIN_CD_MIN = 5                       # CDs entram com parada >= isto (ou em andamento)
MIN_DESCONHECIDO_CONFERIR_MIN = 30   # parada sem cadastro >= isto vai para "Conferir"
RAIO_PADRAO_M = 250                  # raio padrão de um local importante
RAIO_SUGESTAO_M = 300                # raio de busca de nomes no OpenStreetMap
ORIGEM_CONFIAVEL_MIN = 120           # origem com essa duração dispensa "em movimento no início"
