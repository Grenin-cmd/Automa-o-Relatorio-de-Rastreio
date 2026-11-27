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

    def test_regra_substitua_troca_pelo_novo_texto(self):
        agente = AgenteRefinamento()
        resultado = agente._aplicar_regras_local(
            "Chegou no CD Matriz às 10:00.", ["Substitua 'CD Matriz' por 'Centro de Distribuição'."]
        )
        self.assertEqual(resultado, "Chegou no Centro de Distribuição às 10:00.")

    def test_regra_substitua_sem_novo_texto_nao_apaga(self):
        agente = AgenteRefinamento()
        texto = "Chegou no CD Matriz às 10:00."
        self.assertEqual(agente._aplicar_regras_local(texto, ["Troque 'CD Matriz'."]), texto)

    def test_regra_sem_aspas_nao_e_colada_no_relatorio(self):
        # Antes, "Inclua ..." sem aspas colava o texto da própria regra no relatório.
        agente = AgenteRefinamento()
        texto = "Chegou no CD às 10:00."
        self.assertEqual(agente._aplicar_regras_local(texto, ["Inclua o horário de saída quando houver."]), texto)


if __name__ == "__main__":
    unittest.main()
