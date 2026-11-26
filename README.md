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

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes usam um banco temporário e não alteram o `poi_store.db`. O GitHub
Actions roda a suíte a cada push (`.github/workflows/testes.yml`); o executável
Windows é gerado manualmente pelo workflow `Compilar Executavel Windows`.
