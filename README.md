# Automa-o-Relatorio-de-Rastreio

Aplicação web em Python (Flask) para analisar o rastreamento de veículos a partir
de planilhas CSV/Excel e gerar relatórios de entradas e saídas em POIs (clientes,
postos, matriz etc.), paradas não cadastradas, linha do tempo da viagem,
resumo geral por placa (com exportação para Word) e auditoria de roteiro
(planejado × executado por GPS). Opcionalmente, os textos são refinados por IA.

## Instalação

```bash
python -m pip install -r requirements.txt
```

Copie `.env.example` para `.env` e ajuste o que precisar (todas as variáveis são
opcionais).

## Executar

```bash
python app.py
```

O navegador abre automaticamente em `http://127.0.0.1:5000/`.

Por padrão o servidor só aceita conexões **desta máquina**. Para liberar o acesso
a outros computadores da rede, defina `HOST=0.0.0.0` no `.env`.

## Primeiro acesso

Quando o banco não tem nenhum usuário, um administrador é criado automaticamente:

- nome: valor de `ADMIN_INICIAL_USUARIO` (padrão `admin`);
- senha: valor de `ADMIN_INICIAL_SENHA` ou, se vazio, uma senha aleatória exibida
  no console e salva em `senha_inicial_admin.txt` (o arquivo é apagado quando a
  senha é trocada).

No primeiro login a troca de senha é obrigatória. Em **Configurações**, perfis
autorizados podem cadastrar usuários, liberar a permissão de cadastro, desativar
acessos e gerar senhas temporárias.

## Variáveis de ambiente

| Variável | Para que serve |
|---|---|
| `FLASK_SECRET_KEY` | Assina o cookie de sessão. Se vazia, é gerada e salva em `.secret_key`. |
| `ADMIN_INICIAL_USUARIO` / `ADMIN_INICIAL_SENHA` | Primeiro administrador (veja acima). |
| `HOST` / `PORT` | Endereço e porta do servidor (padrão `127.0.0.1:5000`). |
| `API_TOKEN` | Token das rotas `/api/*` (`Authorization: Bearer <token>` ou `X-API-Key`). Sem ele, as APIs exigem usuário logado. |
| `RASTREIO_DATA_DIR` | Pasta do banco `poi_store.db` e da chave secreta (padrão: pasta do programa). |
| `OPENROUTER_API_KEY` / `GEMINI_API_KEY` | Chaves dos provedores de IA (opcionais). Sem elas o sistema tenta o Ollama local e, por fim, aplica as regras sem IA. |
| `GEMINI_TIMEOUT_MS` | Tempo máximo de cada chamada de IA (padrão 15000). |

## Formato das planilhas

A planilha de rastreamento deve ter colunas de data/hora, velocidade e posição,
com nomes como `timestamp`/`data_hora`/`data`, `velocidade_kmh`/`velocidade`,
`latitude`/`lat` e `longitude`/`lon` (ou um link do Google Maps), além de `placa`.

- O arquivo carregado fica associado à sessão, então dá para trocar a placa e
  reexecutar a análise sem reenviar o arquivo.
- A auditoria de roteiro não exige informar uma placa; quando necessário, ela usa
  todos os registros compatíveis.

## Mensagem de saídas (WhatsApp)

Gera a mensagem diária "*Horário de saída das Carretas*" a partir da planilha da SS
Telemática, sem IA: a mesma planilha sempre gera o mesmo texto.

1. Na SS, exporte o **Relatório histórico completo** a partir das **18:00 do dia anterior**
   até agora (CSV). O formato "Relatório Histórico" também é aceito, mas não traz
   coordenadas.
2. No sistema, abra **Mensagem de saídas**, envie o arquivo e clique em **Gerar mensagem**.
3. Clique em **📋 Copiar** e cole no grupo.

Regras usadas:
- O local onde a carreta passou a noite sempre aparece ("Saída do/da …" ou "Está no/na …").
- Matriz e CDs: chegadas e saídas. Postos e restaurantes: só paradas de 30 min ou mais.
- Manobras curtas no pátio contam como uma parada só.
- Horário de saída = primeiro registro em que o veículo volta a andar (> 3 km/h).
- Horários antes da meia-noite levam "de ontem".

**Conferir:** o que o sistema não sabe classificar (parada longa em ponto sem cadastro,
veículo que já estava andando no início da planilha) fica numa lista ao lado da mensagem,
fora do texto. Para pontos sem cadastro há uma sugestão de nome do OpenStreetMap (precisa
de internet); ao **Cadastrar**, o local passa a ser reconhecido automaticamente.
O link **Relatório de pontos sem cadastro** baixa um Excel para cadastrar esses pontos na SS.

**Locais importantes** (menu lateral): nome que aparece na mensagem, artigo (do/da),
tipo (Matriz, CD, Posto…), nomes do POI na SS e raio. Já vem com os locais usados nas
mensagens de novembro/2026.

## Estrutura do código

| Arquivo | Responsabilidade |
|---|---|
| `app.py` | Cria o app Flask, registra as rotas, CSRF e inicia o servidor |
| `config.py` | Carrega o `.env` e define os diretórios |
| `banco.py` | SQLite: tabelas, migrações, usuário inicial, POIs e regras |
| `seguranca.py` | CSRF, limite de login, senhas e token de API |
| `utils.py` / `geo.py` | Normalização de texto e números; distâncias |
| `arquivos.py` | Leitura de CSV/Excel e uploads temporários |
| `analise.py` | Paradas não cadastradas, linha do tempo, resumo geral e Word |
| `analisador_rastreio.py` | Motor de detecção de entradas/saídas em POIs |
| `auditoria_roteiro.py` | Auditoria planejado × executado |
| `leitor_universal.py` | Leitura de arquivos de diferentes fornecedores de rastreio |
| `agente_refinamento.py` | Refinamento de textos por IA (com regras aplicadas sem IA como reserva) |
| `mensagem_saidas/` | Mensagem de saídas: leitura da SS, paradas, regras, sugestão de nomes e Excel |
| `rotas/` | Blueprints: `auth`, `analise`, `configuracoes`, `auditoria`, `api`, `mensagem` |

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes usam um banco temporário e não alteram o `poi_store.db`. O GitHub
Actions roda a suíte a cada push (`.github/workflows/testes.yml`); o executável
Windows é gerado manualmente pelo workflow `Compilar Executavel Windows`.
