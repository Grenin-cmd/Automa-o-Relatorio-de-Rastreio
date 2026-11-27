import unittest

import pandas as pd

import analise
import app
from rotas import comum


class AppImportTests(unittest.TestCase):
    def test_app_importa_sem_erro(self):
        self.assertIsNotNone(app.app)
        self.assertIsNotNone(comum.VEICULOS_SERVICE)

    def test_obter_posicoes_placas_aceita_lat_lon_reais(self):
        df = pd.DataFrame({
            "Placa": ["ABC1234", "ABC1234"],
            "Latitude": ["-23.5505", "-23.5600"],
            "Longitude": ["-46.6333", "-46.6400"],
        })

        self.assertEqual(analise.obter_posicoes_placas(df)["ABC1234"], (-23.56, -46.64))


if __name__ == "__main__":
    unittest.main()
