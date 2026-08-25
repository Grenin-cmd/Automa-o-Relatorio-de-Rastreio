import unittest
from datetime import datetime, timedelta

import pandas as pd

from analisador_rastreio import RastreamentoAnalyzer


class RastreamentoAnalyzerTests(unittest.TestCase):
    def test_detecta_chegada_e_saida_em_ponto_de_interesse(self):
        analyzer = RastreamentoAnalyzer(
            pois=[{"nome": "Cliente A", "tipo": "cliente", "latitude": -23.5505, "longitude": -46.6333, "raio_metros": 300, "tempo_parado_seg": 120, "velocidade_maxima_kmh": 10}],
            velocidade_limite_kmh=10,
            tempo_parado_seg=120,
        )

        timestamps = [
            datetime(2026, 7, 9, 10, 0, 0),
            datetime(2026, 7, 9, 10, 1, 0),
            datetime(2026, 7, 9, 10, 2, 0),
            datetime(2026, 7, 9, 10, 3, 0),
            datetime(2026, 7, 9, 10, 4, 0),
        ]
        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "latitude": [-23.5505, -23.5505, -23.5505, -23.5505, -23.5505],
                "longitude": [-46.6333, -46.6333, -46.6333, -46.6333, -46.6333],
                "velocidade_kmh": [40, 5, 4, 4, 60],
            }
        )

        events = analyzer.detect_events(df)

        self.assertGreaterEqual(len(events), 2)
        self.assertIn("entrada", [event["tipo"] for event in events])
        self.assertIn("saida", [event["tipo"] for event in events])

    def test_gerar_relatorio_plataforma_csv(self):
        analyzer = RastreamentoAnalyzer(pois=[], velocidade_limite_kmh=10, tempo_parado_seg=120)
        df = pd.DataFrame(
            {
                "Data": ["2026-07-09 10:00:00", "2026-07-09 10:05:00", "2026-07-09 10:10:00", "2026-07-09 10:15:00", "2026-07-09 10:25:00"],
                "POI": ["CD", "CD", "CD", "CD", "Matriz"],
                "POI - Distância": [150, 150, 150, 150, 250],
                "Velocidade": [0, 0, 0, 0, 60],
            }
        )
        report = analyzer.gerar_relatorio(df)
        self.assertIn("Relatório de rastreamento", report)
        self.assertIn("Chegou no CD às", report)
        self.assertIn("saiu às", report)

    def test_nao_registra_parada_curta(self):
        analyzer = RastreamentoAnalyzer(pois=[], velocidade_limite_kmh=10, tempo_parado_seg=120)
        df = pd.DataFrame(
            {
                "Data": ["2026-07-09 10:00:00", "2026-07-09 10:05:00", "2026-07-09 10:08:00", "2026-07-09 10:10:00"],
                "POI": ["CD", "CD", "CD", "Matriz"],
                "POI - Distância": [150, 150, 150, 250],
                "Velocidade": [0, 0, 0, 60],
            }
        )
        report = analyzer.gerar_relatorio(df)
        self.assertEqual(report, "Nenhum evento relevante detectado.")

    def test_está_na_matriz_quando_nao_houve_saida(self):
        analyzer = RastreamentoAnalyzer(pois=[], velocidade_limite_kmh=10, tempo_parado_seg=120)
        df = pd.DataFrame(
            {
                "Data": ["2026-07-09 10:00:00", "2026-07-09 10:02:00", "2026-07-09 10:04:00"],
                "POI": ["Matriz", "Matriz", "Matriz"],
                "POI - Distância": [150, 150, 150],
                "Velocidade": [0, 0, 0],
            }
        )
        report = analyzer.gerar_relatorio(df)
        self.assertIn("Está na matriz", report)

    def test_trata_camara_fria_como_matriz(self):
        analyzer = RastreamentoAnalyzer(pois=[], velocidade_limite_kmh=10, tempo_parado_seg=120)
        df = pd.DataFrame(
            {
                "Data": ["2026-07-09 10:00:00", "2026-07-09 10:10:00"],
                "POI": ["Camara Fria", "Camara Fria"],
                "POI - Distância": [150, 150],
                "Velocidade": [0, 0],
            }
        )
        report = analyzer.gerar_relatorio(df)
        self.assertIn("Está na matriz", report)

    def test_nao_detecta_evento_quando_o_veiculo_passa_rapido(self):
        analyzer = RastreamentoAnalyzer(
            pois=[{"nome": "Posto X", "tipo": "posto", "latitude": -23.5505, "longitude": -46.6333, "raio_metros": 300, "tempo_parado_seg": 120, "velocidade_maxima_kmh": 10}],
            velocidade_limite_kmh=10,
            tempo_parado_seg=120,
        )

        df = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 7, 9, 10, 0, 0), datetime(2026, 7, 9, 10, 0, 30)],
                "latitude": [-23.5505, -23.5505],
                "longitude": [-46.6333, -46.6333],
                "velocidade_kmh": [50, 55],
            }
        )

        events = analyzer.detect_events(df)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
