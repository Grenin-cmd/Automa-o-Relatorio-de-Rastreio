# Automa-o-Relatorio-de-Rastreio

Este repositório contém um protótipo de agente em Python para analisar rastreamento de carretas a partir de um arquivo Excel e gerar um relatório de entradas e saídas em POIs como clientes, postos de gasolina, acostamentos e outros pontos importantes.

## Como usar

1. Instale as dependências:
   ```bash
   python -m pip install -r requirements.txt
   ```
2. Rode a interface web:
   ```bash
   python app.py
   ```
3. Abra o navegador no endereço mostrado no terminal, por exemplo:
   ```text
   http://127.0.0.1:5000/
   ```
4. Use o botão para selecionar seu arquivo CSV ou Excel e clique em "Executar análise".

O arquivo Excel deve conter colunas com nomes como `timestamp`, `latitude`, `longitude` e `velocidade_kmh` (ou variações compatíveis como `data_hora`, `lat`, `lon` e `speed_kmh`).

Observações:
- O arquivo carregado fica mantido na sessão do navegador, então você pode trocar a placa e reexecutar a análise sem precisar reenviar o arquivo.
- Linhas sem informação de POI/local são destacadas em uma tabela separada para facilitar a limpeza dos dados.

Exemplo de arquivo de dependências:
```txt
pandas
openpyxl
```