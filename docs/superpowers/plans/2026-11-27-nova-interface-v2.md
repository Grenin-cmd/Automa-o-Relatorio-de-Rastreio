# Nova interface + Mensagem v2 — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrar a Mensagem do dia à Análise de rastreio (edição por placa, recorte 21:00, lista fixa de locais, Excel de 4 colunas) e trocar a interface de todas as telas pelo layout aprovado (proposta D), sem perder funcionalidades.

**Architecture:** `mensagem_saidas/` ganha `unidades.py` (lista fixa + nomes/tipos derivados da SS) e `regras.py` passa a devolver linhas por placa, situações, números e pontos sem POI (sem "Conferir"). As telas herdam de `templates/base.html` (barra lateral). A Análise de rastreio vira abas por GET (`?aba=`), com upload por POST.

**Tech Stack:** Python 3.12, Flask/Jinja, pandas, SQLite, openpyxl, pytest, Playwright (verificação).

**Spec:** `docs/superpowers/specs/2026-11-27-nova-interface-e-mensagem-v2-design.md` (e v1 `2026-11-27-mensagem-saidas-design.md` para §3, §5, §6)

## Global Constraints

- Paleta: #0f172a, #1e293b, #334155, #64748b, #94a3b8, #e2e8f0, #f1f5f9, #f8fafc; roxo #7c3aed/#6d28d9/#f5f3ff/#ddd6fe; âmbar #b45309/#fef3c7; vermelho #b91c1c/#fef2f2. Fonte Plus Jakarta Sans; JetBrains Mono nas placas. Sem ícone de caminhão, sem emoji.
- Sem aba "Ao vivo" e sem botão "Copiar mensagem".
- Recorte: descartar registros com `data_hora < (data_mensagem - 1 dia) 21:00`.
- Excel do aprendiz: exatamente as colunas `Nome sugerido, Latitude, Longitude, Link Google Maps`.
- Gabaritos de 26/11 e 27/11 continuam passando (±2 min).
- Todas as funcionalidades atuais permanecem (spec v2 §4, tabela).

## Review Focus

1. Planilha que não é da SS (formato genérico antigo) → abas antigas funcionam, sem Mensagem do dia (Task 4).
2. Nome de POI da SS com acentos/siglas (`P.S. AERODROMO MG 260 CLAUDIO`, `CD Mart Minas`) → caixa de título preserva siglas (Task 1).
3. Edição de uma placa e depois envio de nova planilha → edições antigas não vazam para a nova (Task 4).
4. Usuário sem permissão de cadastro → item "Usuários" não aparece e a rota redireciona (Task 3).
5. Base de POIs com ~17 mil itens → tela de POIs carrega rápido (busca via `/api/pois`, nada renderizado em massa) (Task 3).

---

### Task 1: Lista fixa de locais e nomes da SS

**Files:** Create `mensagem_saidas/unidades.py`; Modify `mensagem_saidas/locais.py`, `banco.py` (remover tabela/CRUD/carga de locais), `tests/test_mensagem_*.py` (trocar `banco.listar_locais()` por `unidades.LOCAIS`); Delete `tests/test_mensagem_locais.py` parte de CRUD; Test `tests/test_mensagem_unidades.py`

**Interfaces:**
- Produces: `unidades.LOCAIS: list[Local]` (as 11 entradas da carga v1, ids fixos `"u:<n>"`); `formatar_nome_ss(nome: str) -> str`; `tipo_por_nome(nome: str) -> str`; `local_da_ss(poi_ss: str) -> Local` (id `"ss:<NOME NORMALIZADO>"`, gênero "o", raio `RAIO_PADRAO_M`).
- `resolver_local(lat, lon, poi_ss, poi_ss_dist_m, locais)` mantém a assinatura; depois das regras v1, se `poi_ss` e `poi_ss_dist_m <= RAIO_PADRAO_M` → `local_da_ss(poi_ss)`.

- [ ] Testes: `formatar_nome_ss("POSTO JALÉ BR-262 EM ARAÚJOS") == "Posto Jalé BR-262 em Araújos"`; `formatar_nome_ss("P.S. AERODROMO MG 260 CLAUDIO") == "P.S. Aerodromo MG 260 Claudio"`; `formatar_nome_ss("CD Mart Minas Contagem") == "CD Mart Minas Contagem"`; `tipo_por_nome` → POSTO para "AUTO POSTO X"/"P.S. X", RESTAURANTE para "CHURRASCARIA X", CD para "CD X", MATRIZ para "CECOTI MATRIZ", OUTRO para "PAES E CIA MIL"; `resolver_local(None,None,"POSTO JALÉ BR-262 EM ARAÚJOS",59,LOCAIS).nome_exibicao == "Posto Jalé BR-262 em Araújos"`; a 251 m → None.
- [ ] RED → implementar → GREEN; suíte inteira verde (gabaritos inclusos, agora com `unidades.LOCAIS`).
- [ ] Commit `feat(mensagem): lista fixa de locais e nomes derivados da SS`.

### Task 2: Regras v2 (recorte 21:00, linhas por placa, situações, pontos sem POI) e Excel de 4 colunas

**Files:** Modify `mensagem_saidas/regras.py`, `mensagem_saidas/relatorio.py`; Tests `tests/test_mensagem_regras.py`, `tests/test_mensagem_sugestao_relatorio.py`, `tests/test_mensagem_revisao.py`

**Interfaces:**
- Produces: `@dataclass ResultadoMensagem(data_mensagem: date | None, linhas: dict[str, str], situacoes: dict[str, str], pontos_sem_poi: list[Parada], aviso_periodo: str | None, totais: dict[str, int])` com propriedade `texto` (= `montar_texto(self.data_mensagem, self.linhas)`); `totais` chaves `veiculos, sairam, parados, sem_poi`. `montar_mensagem(df, locais) -> ResultadoMensagem`. `montar_texto(data: date, linhas: dict[str, str], edicoes: dict[str, str] | None = None) -> str` (edições substituem o texto após `"PLACA: "`). `gerar_excel_pontos(pontos: list[Parada], sugestoes: dict[str, str | None]) -> bytes` (chave da sugestão: `f"{lat:.5f},{lon:.5f}"`), só paradas com coordenadas, sem repetir coordenada arredondada a 4 casas.
- Situação: origem não saiu → `Parado`; última parada relevante em andamento (Matriz/CD) → `No CD HH:MM`/`Na Matriz HH:MM`; senão `Saiu HH:MM` (saída da origem).
- Aviso: se `min(data_hora) > (data_mensagem - 1 dia) 21:00` → `"A planilha começa em DD/MM às HH:MM; saídas antes disso podem faltar (o ideal é a partir das 21:00 do dia anterior)."`.

- [ ] Testes: gabaritos (comparar `res.linhas[placa]` com o gabarito sem o prefixo); recorte (registro às 20:59 do dia anterior ignorado, 21:00 mantido); `montar_texto` com edição; situações de 27/11 (`GTN-1H69`→`Saiu 05:41`, `RNZ`→`Parado`, `HDI`→`No CD 06:41`, `UVR`→`Na Matriz 03:29`); totais de 27/11 `{veiculos:8, sairam:6, parados:2, sem_poi:0}`; Excel com exatamente as 4 colunas e linhas de 26/11 = 0 (sem coordenadas), de 27/11 sem lista fixa > 0.
- [ ] RED → implementar → GREEN; suíte verde.
- [ ] Commit `feat(mensagem): regras v2 e Excel de 4 colunas`.

### Task 3: Layout base e telas de cadastro/perfil

**Files:** Create `templates/base.html`, `templates/pois.html`, `templates/regras.html`, `templates/usuarios.html`, `templates/perfil.html`; Rewrite `templates/login.html`, `templates/trocar_senha.html` (vira redirect para perfil); Modify `rotas/configuracoes.py` (rotas `/pois`, `/regras`, `/usuarios`; `/configuracoes` GET → `/pois`, POST mantém ações e redireciona para `/usuarios`), `rotas/auth.py` (`/perfil`; `/trocar_senha` GET → perfil, POST igual), `rotas/analise.py` (import de POIs redireciona para `/pois`); Delete `templates/configuracoes.html`, `templates/locais_importantes.html`, `templates/mensagem_saidas.html`; Test `tests/test_interface.py`

**Interfaces:**
- `base.html` blocos: `title`, `conteudo`; variável `ativo` (`analise|auditoria|pois|regras|usuarios|perfil`) marca o menu; mostra flashes; "Usuários" só se `usuario_atual.pode_cadastrar_usuarios`.
- Rotas: `GET /pois` (busca via `/api/pois` em JS, importar planilha → POST `/` `action=import_pois`, excluir selecionados → POST `/excluir_pois`); `GET /regras` (adicionar → `/adicionar_regra_feedback`, excluir → `/excluir_regras`); `GET/POST /usuarios` (ações do antigo `/configuracoes`); `GET /perfil` (nome, permissão, formulário de troca → POST `/trocar_senha`).

- [ ] Testes: cada GET (`/pois`, `/regras`, `/usuarios`, `/perfil`) 200 logado e 302 deslogado; `/configuracoes` → 302 para `/pois`; usuário sem permissão: `/usuarios` → 302 e menu sem "Usuários"; troca de senha pelo perfil funciona (reaproveitar `test_troca_de_senha` apontando para `/perfil`); `/pois` não contém nomes de POIs no HTML; excluir regra/POI e importar POIs redirecionam para as telas novas.
- [ ] RED → implementar → GREEN; suíte verde (ajustar testes antigos que dependiam de `configuracoes.html`).
- [ ] Commit `feat(ui): layout base e telas de POIs, regras, usuarios e perfil`.

### Task 4: Análise de rastreio com abas e Mensagem do dia; Auditoria no novo visual

**Files:** Rewrite `templates/index.html` (→ `templates/analise.html`), `rotas/analise.py`; Modify `rotas/mensagem.py` (só `POST /mensagem/editar`, `GET /mensagem/excel`, `GET /mensagem_saidas` → `/`); Rewrite `templates/auditoria_roteiro.html` herdando de `base.html`; Tests `tests/test_analise_interface.py`, `tests/test_app_import.py`, `tests/test_mensagem_rotas.py`

**Interfaces:**
- `GET /?aba=mensagem|relatorio|linha|paradas&placa=&raio=`; `POST /` com `arquivo` salva o upload (limpa `session["mensagem_edicoes"]`) e redireciona para `/?aba=mensagem` (ou `relatorio` se não for SS); `POST /` com `action=import_pois` como hoje.
- Mensagem: lista de placas (placa, situação, linha, link 📍→ não: link "mapa" para a última posição via `obter_posicoes_placas`), clique abre `<details>`/formulário com textarea → `POST /mensagem/editar` (`placa`, `texto`, `acao=salvar|restaurar`); bloco final com o texto completo (com edições) em `<textarea readonly>`; botões **Word** (`/download_word`, usa o texto editado) e **Excel p/ cadastro na SS** (`/mensagem/excel`).
- Números no topo (`totais`); aviso de período; raio e placa só nas abas que usam.
- Relatório por placa (gerar_relatorio + IA), Linha do tempo, Paradas sem POI: mesma lógica de hoje, calculada só na aba aberta.

- [ ] Testes: upload da fixture de 27/11 → 302 para `?aba=mensagem`; GET mostra as 8 placas e `Saiu 05:41`; sem texto "Copiar mensagem" nem "Ao vivo"; editar placa altera o bloco final e o Word; restaurar volta ao original; nova planilha zera edições; `?aba=relatorio&placa=...` e `?aba=linha` e `?aba=paradas` respondem 200; planilha genérica (`test_rastreio.csv`) abre em relatório sem erro; auditoria GET 200 com o novo layout.
- [ ] RED → implementar → GREEN; suíte e ruff verdes.
- [ ] Verificar no navegador (Playwright): login, análise com a fixture, editar uma placa, abas, POIs, perfil; screenshots.
- [ ] Commit `feat(ui): analise de rastreio com abas e mensagem do dia`.

### Task 5: Entrega

- [ ] README (seção "Mensagem do dia" e estrutura de telas); suíte + ruff verdes.
- [ ] Gerar a mensagem com a planilha original de 27/11 e comparar com a do usuário.
- [ ] Commit, push, disparar o workflow `build_exe.yml` no branch e acompanhar até o artefato.
