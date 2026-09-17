import unittest

from agente_refinamento import AgenteRefinamento


class AgenteRefinamentoTests(unittest.TestCase):
    def test_refinar_relatorio_aplica_regras_sem_ia(self):
        agente = AgenteRefinamento()
        relatorio = "Relatório de rastreamento\n\nEstá em Matriz desde 10:00 e saiu às 12:00."
        regras = [
            "Remova a frase 'saiu às 12:00'.",
            "Inclua a expressão 'permanência no ponto'.",
        ]

        resultado = agente.refinar_relatorio(relatorio, regras)

        self.assertIn("permanência no ponto", resultado.lower())
        self.assertNotIn("saiu às 12:00", resultado.lower())

    def test_refinar_relatorio_preserva_texto_quando_nao_ha_regras(self):
        agente = AgenteRefinamento()
        relatorio = "Relatório de rastreamento\n\nEstá em CD desde 10:00."

        resultado = agente.refinar_relatorio(relatorio, [])

        self.assertEqual(resultado, relatorio)


if __name__ == "__main__":
    unittest.main()
