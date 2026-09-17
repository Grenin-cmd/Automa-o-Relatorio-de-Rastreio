import unittest

import app


class AppImportTests(unittest.TestCase):
    def test_app_importa_sem_erro(self):
        self.assertIsNotNone(app.app)
        self.assertTrue(hasattr(app, "_VEICULOS_SERVICE"))

    def test_resumo_renderiza_botao_google_maps_com_coordenadas(self):
        with app.app.test_request_context("/"):
            html = app.render_template(
                "index.html",
                report=None,
                placa_escolhida="ABC1234",
                raio_suspeita=200,
                paradas_suspeitas=[],
                timeline_eventos=[],
                placas=["ABC1234"],
                file_name="teste.csv",
                resumo_geral="ABC1234: teste de resumo",
                posicoes_placas={"ABC1234": (-23.5505, -46.6333)},
                docx_available=False,
            )

        self.assertIn("📍", html)
        self.assertIn("https://www.google.com/maps/search/?api=1&amp;query=-23.5505,-46.6333", html)

    def test_obter_posicoes_placas_aceita_lat_lon_reais(self):
        df = app.pd.DataFrame({
            "Placa": ["ABC1234", "ABC1234"],
            "Latitude": ["-23.5505", "-23.5600"],
            "Longitude": ["-46.6333", "-46.6400"],
        })

        self.assertEqual(app._obter_posicoes_placas(df)["ABC1234"], (-23.56, -46.64))


if __name__ == "__main__":
    unittest.main()
