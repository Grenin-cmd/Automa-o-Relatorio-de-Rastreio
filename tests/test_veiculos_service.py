import unittest

from veiculos_service import VeiculosService


class VeiculosServiceTests(unittest.TestCase):
    def test_registra_dispositivo_e_veiculo(self):
        service = VeiculosService()

        payload = {
            "deviceId": "DEV-101",
            "imei": "356000000000101",
            "placa": "ABC1234",
            "lat": -19.90,
            "lon": -43.90,
            "speed": 25,
            "ignition": True,
            "battery": 75,
            "ts": "2026-09-11T10:00:00-03:00",
        }

        veiculo = service.registrar_ou_atualizar(payload)

        self.assertEqual(veiculo["veiculo_id"], "ABC1234")
        self.assertEqual(veiculo["dispositivo_id"], "DEV-101")
        self.assertAlmostEqual(veiculo["ultima_posicao"]["latitude"], -19.90)
        self.assertAlmostEqual(veiculo["ultima_posicao"]["longitude"], -43.90)

    def test_lista_veiculos_com_ultima_posicao(self):
        service = VeiculosService()
        service.registrar_ou_atualizar({
            "deviceId": "DEV-202",
            "placa": "XYZ9876",
            "lat": -20.10,
            "lon": -44.10,
            "speed": 60,
            "ts": "2026-09-11T12:00:00-03:00",
        })

        lista = service.listar_veiculos()

        self.assertTrue(any(v["veiculo_id"] == "XYZ9876" for v in lista))
        self.assertTrue(any(v["ultima_posicao"]["latitude"] == -20.10 for v in lista))


if __name__ == "__main__":
    unittest.main()
