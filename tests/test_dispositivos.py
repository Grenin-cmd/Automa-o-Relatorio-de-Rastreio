import unittest
from datetime import datetime

from dispositivos_service import normalizar_payload_dispositivo


class DispositivosServiceTests(unittest.TestCase):
    def test_normalizar_payload_dispositivo(self):
        payload = {
            "deviceId": "DEV-001",
            "imei": "356000000000001",
            "lat": -19.92,
            "lon": -43.95,
            "speed": 43.5,
            "ignition": True,
            "battery": 82,
            "ts": "2026-09-11T10:15:00-03:00",
        }

        normalizado = normalizar_payload_dispositivo(payload)

        self.assertEqual(normalizado["dispositivo_id"], "DEV-001")
        self.assertEqual(normalizado["imei"], "356000000000001")
        self.assertAlmostEqual(normalizado["latitude"], -19.92)
        self.assertAlmostEqual(normalizado["longitude"], -43.95)
        self.assertAlmostEqual(normalizado["velocidade_kmh"], 43.5)
        self.assertTrue(normalizado["ignicao"])
        self.assertEqual(normalizado["bateria_pct"], 82)
        self.assertIsNotNone(normalizado["data_hora"])

    def test_normalizar_payload_dispositivo_aceita_variacoes(self):
        payload = {
            "id": "DEV-002",
            "latitude": "-20.12",
            "longitude": "-44.12",
            "velocidade_kmh": "55",
            "timestamp": "2026-09-11 11:00:00",
            "bateria": "92%",
        }

        normalizado = normalizar_payload_dispositivo(payload)

        self.assertEqual(normalizado["dispositivo_id"], "DEV-002")
        self.assertEqual(normalizado["bateria_pct"], 92)
        self.assertAlmostEqual(normalizado["velocidade_kmh"], 55.0)


if __name__ == "__main__":
    unittest.main()
