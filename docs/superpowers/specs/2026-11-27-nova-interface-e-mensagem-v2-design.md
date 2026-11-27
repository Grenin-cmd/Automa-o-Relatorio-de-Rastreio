# Nova interface + Mensagem de saídas v2 — design

Data: 27/11/2026 · Situação: aguardando aprovação
Substitui, onde diverge, `2026-11-27-mensagem-saidas-design.md` (v1).
Desenho aprovado: proposta D em https://claude.ai/artifact/GiSKwwbWKkATYGyyWzhFYv#artboard-OpcaoD

## 1. Por que mudar

Feedback do usuário após testar a v1:
- a mensagem não precisa de tela/botão próprio — é a mesma coisa que a Análise de rastreio;
- a tela "Locais importantes" é desnecessária;
- o limite que importa é **21:00 do dia anterior**, não 18:00;
- o Excel do aprendiz deve ter só o necessário;
- a lista "Conferir" não é o que ele quer: quer **clicar na placa e editar a linha**;
- a interface está confusa e feia — quer algo **clean e moderno**, com a **paleta atual** do sistema,
  **sem perder nenhuma funcionalidade**.

As alterações pendentes do Codespaces serão integradas depois; a interface ainda pode mudar.

## 2. Mensagem do dia (dentro da Análise de rastreio)

- Ao enviar a planilha na Análise de rastreio, a aba **Mensagem do dia** abre por padrão.
  Ela substitui o antigo "Resumo geral" (mesma finalidade). A tela `/mensagem_saidas`
  deixa de existir (redireciona para `/`).
- **Planilhas aceitas:** os dois formatos da SS (v1 §3). Outras planilhas (formato genérico) continuam
  servindo às abas antigas; a Mensagem do dia aparece só quando a planilha é da SS.
- **Período:** registros antes das **21:00 do dia anterior** à data da mensagem são descartados.
  Se a planilha começa depois das 21:00 do dia anterior, um aviso discreto informa que saídas
  anteriores podem faltar.
- **Regras de detecção e texto:** as da v1 (§5, §6), validadas pelos testes de gabarito, com:
  - **Nome e tipo dos locais (opção B):** uma lista fixa no código (`mensagem_saidas/unidades.py`),
    sem tela, com os locais das mensagens de gabarito (Matriz, CDs Cecoti, CD Supermercados BH,
    CD Supermercado BH, Fontini, CEMA, Cemil, Posto Caxuxa, Restaurante Ponto do Peixe, Posto Dom Pedro).
    Fora da lista: **nome do POI da SS**, em caixa de título (`POSTO JALÉ BR-262 EM ARAÚJOS` →
    `Posto Jalé BR-262 em Araújos`; siglas como BR-262, MG, CD mantidas), tipo deduzido do nome
    (POSTO/AUTO POSTO/P.S. → posto; RESTAURANTE/CHURRASCARIA/LANCHONETE → restaurante;
    começa com "CD " → CD; contém MATRIZ → Matriz; senão outro), artigo do/no.
  - Ponto sem POI: `Saída de {Cidade} {UF} as HH:MM.` (como v1) e entra no Excel do aprendiz.
- **Edição por placa:** cada placa é uma linha clicável; ao clicar abre um campo de texto com
  **Salvar** e **Voltar ao original**. A edição vale para a planilha carregada (fica na sessão);
  **Copiar mensagem** e **Word** usam o texto editado.
- **Situação** por placa (etiqueta): `Saiu HH:MM`, `Parado`, `No {tipo} HH:MM` (chegada em andamento).
- **Números no topo:** veículos, já saíram, parados no local, pontos sem POI.
- **Removido:** lista "Conferir", cadastro/tela de locais importantes, aceitar/ignorar, item
  "em movimento no início".

## 3. Excel para o aprendiz

Colunas: **Nome sugerido, Latitude, Longitude, Link Google Maps** — nada mais.
Linhas: paradas sem POI identificado com 30 min ou mais (origem inclusive), só as que têm coordenadas
(formato "histórico completo"). Nome sugerido: OpenStreetMap (v1 §7), vazio se não houver.

## 4. Nova interface (todas as telas)

Base comum (`templates/base.html`), seguindo a proposta D:
- **Barra lateral escura** (#0f172a) com logo "AF"; grupos **Operação** (Análise de rastreio,
  Auditoria de roteiro) e **Cadastros** (Base de POIs, Regras de IA, Usuários — este só para quem
  pode cadastrar usuários). Rodapé: avatar + nome + "Meu perfil" e botão Sair.
- **Paleta atual:** ardósia #0f172a/#1e293b/#64748b/#e2e8f0/#f1f5f9/#f8fafc; roxo #7c3aed
  (ação principal, item ativo, edição); âmbar #b45309/#fef3c7 (atenção); vermelho #b91c1c (erro).
  Fonte Plus Jakarta Sans; JetBrains Mono nas placas. Cantos 12–18 px, bordas suaves, sem ícone de caminhão.
- Na barra lateral estreita (celular) o menu vira uma faixa no topo.

Telas e onde cada funcionalidade atual vai parar (nada é removido):

| Hoje | Na nova interface |
|---|---|
| Análise: upload, placa, raio, relatório, resumo geral, linha do tempo, paradas não cadastradas, veículos ativos, Word, posições no mapa | **Análise de rastreio**: topo com planilha + "Nova planilha"; números; abas **Mensagem do dia · Relatório por placa · Linha do tempo · Paradas sem POI · Ao vivo**; raio e escolha da placa nas abas que usam |
| Modal de POIs (importar, listar, buscar, excluir) e seção em Configurações | **Base de POIs** (tela própria) |
| Modal de regras de IA e seção em Configurações | **Regras de IA** (tela própria) |
| Usuários em Configurações | **Usuários** (tela própria) |
| Trocar senha (link solto) | **Meu perfil** (dados do usuário + trocar senha) |
| Auditoria de roteiro | **Auditoria de roteiro** com o novo visual, mesmas funções |
| Login | novo visual, mesmas funções |

`/configuracoes` passa a redirecionar para Base de POIs (links antigos continuam funcionando).

## 5. Testes

- Gabaritos de 26/11 e 27/11 continuam valendo (texto com a lista fixa; ±2 min).
- Recorte das 21:00; caixa de título e tipo deduzido de nomes da SS; edição por placa
  (salvar, voltar ao original, cópia usa o editado); Excel com 4 colunas.
- Cada tela nova responde (login exigido, CSRF) e mantém as ações atuais (importar/excluir POIs,
  regras, usuários, troca de senha, auditoria, Word).
- Verificação no navegador das telas principais.

## 6. Fora do escopo

Integração das alterações do Codespaces (quando disponíveis); envio automático ao WhatsApp;
cadastro automático na SS.
