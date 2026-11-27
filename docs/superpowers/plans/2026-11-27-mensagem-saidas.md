# Mensagem de Saídas das Carretas — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gerar, a partir da exportação CSV da SS Telemática, a mensagem diária de saídas para o WhatsApp, idêntica à manual, com uma lista "Conferir" de exceções e um relatório Excel de pontos a cadastrar na SS.

**Architecture:** Pacote novo `mensagem_saidas/` sem Flask (leitura → locais → paradas → regras/texto), cadastro `locais_importantes` no SQLite (`banco.py`), blueprint `rotas/mensagem.py` com tela própria. Nada de IA; o texto é determinístico.

**Tech Stack:** Python 3.12, pandas, Flask, SQLite, openpyxl, pytest. Sugestão de nomes via Overpass API (OpenStreetMap) com `urllib` da biblioteca padrão.

**Spec:** `docs/superpowers/specs/2026-11-27-mensagem-saidas-design.md`

## Global Constraints

- Limiares, como constantes nomeadas em `mensagem_saidas/constantes.py`: `VEL_PARADO_KMH = 3` (parado se ≤), `MERGE_DIST_M = 1500`, `MERGE_MOVIMENTO_MIN = 15`, `MIN_POSTO_MIN = 30`, `MIN_CD_MIN = 5`, `MIN_DESCONHECIDO_CONFERIR_MIN = 30`, `RAIO_PADRAO_M = 250`, `RAIO_SUGESTAO_M = 300`, `ORIGEM_CONFIAVEL_MIN = 120`.
- Saída = primeiro registro após a parada com velocidade > 3 km/h. Chegada = primeiro registro parado dentro do local. Duração = chegada→saída.
- Frases exatas: `Saída {do|da} {nome} as HH:MM.`, `Está {no|na} {nome}.`, `Chegada {no|na} {nome} as HH:MM e saiu as HH:MM.`, `Chegada {no|na} {nome} as HH:MM.`, desconhecido: `Saída de {Cidade} {UF} as HH:MM.` / `Está em {Cidade} {UF}.`; antes da data da mensagem: `as HH:MM de ontem`. "as" sem acento.
- Cabeçalho: `*Horário de saída das Carretas DD/MM/AAAA*`, linha em branco, placas em ordem alfabética separadas por linha em branco.
- CSV da SS: `cp1252`, `;`. `POI` igual a `Não informado` ou vazio = sem POI.
- Sem IA. Sugestão de nome nunca entra na mensagem sem aceite do usuário.
- Não alterar `analise.py`, `analisador_rastreio.py` nem o relatório existente.
- Testes nunca acessam a rede (Overpass simulado).

## Review Focus

1. Arquivo da SS com acentos quebrados ou outro encoding (UTF-8 com BOM) → deve ler igual; testar `utf-8-sig` além de `cp1252` (Task 1).
2. Placa com um único registro, ou registros esparsos a cada 2 h com ignição desligada → "Está {no} {local}." sem erro (Task 3; já coberto pelo TZC/GTN de 26/11 com 3 registros).
3. Planilha que vira o mês/ano (registro de 31/12 23:50 e mensagem de 01/01) → "de ontem" pela data, não só pela hora (Task 4).
4. Local do cadastro sem coordenadas e sem alias casando, mas com POI da SS de mesmo nome em outra cidade → não pode casar por nome se `poi_ss_dist_m` > raio (Task 2).
5. Overpass fora do ar/lento → tela abre normalmente, sem sugestão (Task 5).

---

### Task 1: Leitura das exportações da SS + fixtures de gabarito

**Files:**
- Create: `mensagem_saidas/__init__.py`, `mensagem_saidas/constantes.py`, `mensagem_saidas/leitura.py`
- Create: `tests/fixtures/ss/historico_2026-11-26.csv`, `tests/fixtures/ss/historico_completo_2026-11-27.csv`, `tests/fixtures/ss/gabarito_2026-11-26.txt`, `tests/fixtures/ss/gabarito_2026-11-27.txt`
- Test: `tests/test_mensagem_leitura.py`

**Interfaces:**
- Produces: `ler_exportacao_ss(origem: str | bytes) -> pd.DataFrame` com colunas, nesta ordem: `placa:str, data_hora:datetime64, velocidade_kmh:float, ignicao:bool|None, evento:str, poi_ss:str|None, poi_ss_dist_m:float|None, endereco:str, cidade:str, uf:str, lat:float|None, lon:float|None`, ordenado por `placa, data_hora`. `extrair_cidade_uf(endereco: str) -> tuple[str, str]`. Exceção `FormatoSSDesconhecido(ValueError)` com as colunas lidas na mensagem.

- [ ] **Step 1: Criar as fixtures anonimizadas.** Copiar os dois CSVs enviados pelo usuário (`/root/.claude/uploads/.../18206af4-Relat_rio_Hist_rio_2026-11-26_7h17m46s.csv` e `.../667d821d-Relat_rio_hist_rio_completo_2026-11-27_7h16m5s.csv`) mantendo `cp1252`, trocando só as placas pelo mapa fixo (preserva a ordem alfabética): GTN-1H69→PLA-0A01, HDI-7874→PLA-0A02, RNY-4F94→PLA-0A03, RNZ-1J62→PLA-0A04, RVB-3E31→PLA-0A05, RVY-6G50→PLA-0A06, TZC-0F17→PLA-0A07, UVR-4D34→PLA-0A08. Gabaritos (UTF-8), exatamente:

`gabarito_2026-11-27.txt`:
```
*Horário de saída das Carretas 27/11/2026*

PLA-0A01: Saída da Matriz as 05:43.

PLA-0A02: Saída da Matriz as 22:55 de ontem. Chegada no CD de Uberlândia as 06:41.

PLA-0A03: Saída do Posto Caxuxa na BR-262 em Luz MG as 04:21. Chegada no Restaurante Ponto do Peixe em Nova Serrana MG as 05:28 e saiu as 06:01.

PLA-0A04: Está no CD Supermercados BH em Contagem MG.

PLA-0A05: Saída do CD Supermercado BH em Contagem MG as 05:51.

PLA-0A06: Saída do Posto Dom Pedro na SP-065 em Atibaia SP as 06:25.

PLA-0A07: Está no CD Supermercados BH em Contagem MG.

PLA-0A08: Saída da Matriz as 21:47 de ontem. Chegada no CD de Contagem as 00:07 e saiu as 01:24. Chegada na Matriz as 03:29.
```
`gabarito_2026-11-26.txt` (só as placas comparáveis; ver spec §9):
```
*Horário de saída das Carretas 26/11/2026*

PLA-0A01: Está na Cemil em Patos de Minas MG.

PLA-0A03: Saída do Posto Caxuxa na BR-262 em Luz MG as 03:05.

PLA-0A04: Saída da Matriz as 03:08. Chegada no CD Supermercados BH em Contagem MG as 05:20.

PLA-0A07: Está no CD Supermercados BH em Contagem MG.

PLA-0A08: Saída da Matriz as 03:55. Chegada na CEMA Central Mineira Atacadista em Ribeirão das Neves as 06:21.
```
Verificar: `grep -c "GTN-1H69\|HDI-7874\|RVB-3E31" tests/fixtures/ss/*.csv` → `0` em ambos.

- [ ] **Step 2: Escrever os testes**

```python
FIX = Path(__file__).parent / "fixtures" / "ss"

def test_le_formato_historico():
    df = ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv"))
    assert list(df.columns) == ["placa","data_hora","velocidade_kmh","ignicao","evento","poi_ss","poi_ss_dist_m","endereco","cidade","uf","lat","lon"]
    assert len(df) == 1765 and df["lat"].isna().all()
    r = df[df.placa == "PLA-0A01"].iloc[0]
    assert r.data_hora == pd.Timestamp("2026-11-26 01:54:13") and r.velocidade_kmh == 0 and r.ignicao is False
    assert (r.poi_ss, r.poi_ss_dist_m, r.cidade, r.uf) == ("CEMIL", 85.0, "Patos de Minas", "MG")

def test_le_formato_historico_completo():
    df = ler_exportacao_ss(str(FIX / "historico_completo_2026-11-27.csv"))
    assert len(df) == 1871 and df["lat"].notna().all()
    r = df[df.placa == "PLA-0A06"].iloc[0]
    assert r.poi_ss is None                      # "Não informado"
    assert (round(r.lat, 5), round(r.lon, 5)) == (-23.10011, -46.60962)
    assert (r.cidade, r.uf) == ("Atibaia", "SP") and r.ignicao is None

def test_aceita_utf8_com_bom(tmp_path):
    origem = (FIX / "historico_2026-11-26.csv").read_bytes().decode("cp1252")
    f = tmp_path / "x.csv"; f.write_bytes(origem.encode("utf-8-sig"))
    assert ler_exportacao_ss(str(f)).iloc[0].cidade == ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv")).iloc[0].cidade

def test_formato_desconhecido(tmp_path):
    f = tmp_path / "x.csv"; f.write_text("a;b\n1;2\n", encoding="cp1252")
    with pytest.raises(FormatoSSDesconhecido, match="a"): ler_exportacao_ss(str(f))

def test_extrair_cidade_uf():
    assert extrair_cidade_uf("Rodovia Dom Pedro I, Jardim Colonial - Atibaia - São Paulo - Brasil") == ("Atibaia", "SP")
    assert extrair_cidade_uf("Riacho de areia - Minas Gerais - Brasil") == ("Riacho de areia", "MG")
    assert extrair_cidade_uf("") == ("", "")
```

- [ ] **Step 3: Rodar e ver falhar** — `python -m pytest tests/test_mensagem_leitura.py -q` → FAIL (`ModuleNotFoundError: mensagem_saidas`).
- [ ] **Step 4: Implementar** `leitura.py` e `constantes.py`. Detectar o formato pelas colunas (`Hora`+`Distância` vs `POI - Distância`+`Latitude / Longitude`); encoding: tentar `utf-8-sig` e depois `cp1252`; datas `%d/%m/%y %H:%M:%S`; velocidade = primeiro número do texto; ignição `Ligado/Desligado`; UF pelo nome do estado (reaproveitar `_UFS_POR_NOME` de `analisador_rastreio.py` via import).
- [ ] **Step 5: Rodar e ver passar** — mesmo comando → `5 passed`.
- [ ] **Step 6: Commit** — `git add mensagem_saidas tests/fixtures/ss tests/test_mensagem_leitura.py && git commit -m "feat(mensagem): leitura das exportacoes da SS e fixtures de gabarito"`

---

### Task 2: Cadastro de locais importantes

**Files:**
- Create: `mensagem_saidas/locais.py`
- Modify: `banco.py` (tabela, carga inicial em `init_db`, CRUD)
- Test: `tests/test_mensagem_locais.py`

**Interfaces:**
- Consumes: constantes da Task 1.
- Produces: `@dataclass(frozen=True) Local(id: str, nome_exibicao: str, genero: str, tipo: str, aliases_ss: tuple[str, ...], latitude: float | None, longitude: float | None, raio_m: float, cadastrado_na_ss: bool)` com propriedades `art_de` ("do"/"da") e `art_em` ("no"/"na"). `TIPOS = ("MATRIZ","CD","POSTO","RESTAURANTE","CLIENTE","OUTRO")`. `resolver_local(lat: float | None, lon: float | None, poi_ss: str | None, poi_ss_dist_m: float | None, locais: list[Local]) -> Local | None`.
  Em `banco.py`: `listar_locais() -> list[Local]`, `salvar_local(dados: dict, local_id: str | None = None) -> str`, `excluir_local(local_id: str) -> None`, `marcar_cadastrado_na_ss(local_id: str, valor: bool) -> None`.

- [ ] **Step 1: Escrever os testes**

```python
def _l(**kw):
    base = dict(id="x", nome_exibicao="Matriz", genero="a", tipo="MATRIZ", aliases_ss=("CECOTI MATRIZ",), latitude=None, longitude=None, raio_m=250, cadastrado_na_ss=False)
    return Local(**{**base, **kw})

def test_artigos():
    assert (_l().art_de, _l().art_em) == ("da", "na")
    assert (_l(genero="o").art_de, _l(genero="o").art_em) == ("do", "no")

def test_resolve_por_coordenada_antes_do_alias():
    dom = _l(id="d", nome_exibicao="Posto Dom Pedro na SP-065 em Atibaia SP", genero="o", tipo="POSTO", aliases_ss=(), latitude=-23.10011, longitude=-46.60962, raio_m=300)
    assert resolver_local(-23.1010, -46.6096, None, None, [_l(), dom]) is dom

def test_resolve_por_alias_dentro_do_raio_ignorando_caixa_e_acento():
    assert resolver_local(None, None, "cecoti matriz", 120, [_l()]).nome_exibicao == "Matriz"

def test_alias_fora_do_raio_nao_casa():
    assert resolver_local(None, None, "CECOTI MATRIZ", 251, [_l()]) is None

def test_carga_inicial_tem_os_11_locais_do_gabarito():
    nomes = {l.nome_exibicao for l in banco.listar_locais()}
    assert {"Matriz", "CD de Contagem", "CD Supermercados BH em Contagem MG", "Posto Dom Pedro na SP-065 em Atibaia SP"} <= nomes
    assert len(nomes) >= 11
    cd = next(l for l in banco.listar_locais() if l.nome_exibicao == "CD de Contagem")
    assert cd.raio_m == 150 and cd.aliases_ss == ("CECOTI CD CONTAGEM",)

def test_crud_local():
    lid = banco.salvar_local({"nome_exibicao": "Posto Teste em X MG", "genero": "o", "tipo": "POSTO", "aliases_ss": ["POSTO T"], "latitude": -20.0, "longitude": -44.0, "raio_m": 200})
    banco.marcar_cadastrado_na_ss(lid, True)
    l = next(l for l in banco.listar_locais() if l.id == lid)
    assert l.cadastrado_na_ss and l.aliases_ss == ("POSTO T",)
    banco.excluir_local(lid)
    assert all(l.id != lid for l in banco.listar_locais())
```

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_mensagem_locais.py -q` → FAIL.
- [ ] **Step 3: Implementar.** Tabela `locais_importantes(id TEXT PK, nome_exibicao TEXT NOT NULL, genero TEXT NOT NULL CHECK(genero IN ('o','a')), tipo TEXT NOT NULL, aliases_ss TEXT NOT NULL DEFAULT '' /* separados por '|' */, latitude REAL, longitude REAL, raio_m REAL NOT NULL DEFAULT 250, cadastrado_na_ss INTEGER NOT NULL DEFAULT 0, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`. Carga inicial = tabela do spec §4, inserida só quando a tabela está vazia (o usuário pode editar/excluir depois). Comparação de alias: maiúsculas, sem acento, espaços colapsados. Coordenadas: usar `geo.haversine_metros`; havendo vários, o mais próximo.
- [ ] **Step 4: Rodar e ver passar** — `6 passed`; `python -m pytest -q` sem regressões.
- [ ] **Step 5: Commit** — `git commit -m "feat(mensagem): cadastro de locais importantes"`

---

### Task 3: Detector de paradas

**Files:**
- Create: `mensagem_saidas/paradas.py`
- Test: `tests/test_mensagem_paradas.py`

**Interfaces:**
- Consumes: `ler_exportacao_ss`, `Local`, `resolver_local`.
- Produces: `@dataclass Parada(placa: str, inicio: datetime, fim: datetime, chegada: datetime, saida: datetime | None, local: Local | None, cidade: str, uf: str, endereco: str, lat: float | None, lon: float | None, poi_ss: str | None, poi_ss_dist_m: float | None, em_andamento_no_inicio: bool)` com `duracao_min -> float` (chegada→saída, ou chegada→`fim` se em andamento) e `em_andamento -> bool` (`saida is None`). `detectar_paradas(registros: pd.DataFrame, locais: list[Local]) -> list[Parada]` (registros de uma placa). `veio_em_movimento(registros) -> bool` (primeiro registro com velocidade > 3).

Algoritmo (spec §5): registro parado = `velocidade_kmh <= 3`; parada = sequência de parados; `saida` = primeiro registro seguinte com velocidade > 3 (None se não houver); resolver o local de cada registro parado; unificar paradas consecutivas quando o movimento entre elas dura ≤ 15 min E (com coordenadas: deslocamento ≤ 1500 m; sem coordenadas: mesmo `poi_ss` normalizado) E não caem em dois locais cadastrados diferentes. Numa parada unificada, `local`/`chegada` vêm do primeiro registro parado que caiu num local cadastrado (senão, do primeiro registro); `saida` é a do último trecho. `em_andamento_no_inicio` = a parada começa no primeiro registro da placa.

- [ ] **Step 1: Escrever os testes** (cadastro = `banco.listar_locais()` da carga inicial)

```python
def _paradas(arquivo, placa):
    df = ler_exportacao_ss(str(FIX / arquivo))
    return detectar_paradas(df[df.placa == placa], banco.listar_locais())

def hm(dt): return dt.strftime("%H:%M")

def test_manobras_na_matriz_viram_uma_parada():          # HDI 27/11: 21:00–22:55 com saídas curtas no pátio
    p = _paradas("historico_completo_2026-11-27.csv", "PLA-0A02")[0]
    assert p.local.nome_exibicao == "Matriz" and hm(p.saida) == "22:56"

def test_noite_fora_do_cd_unifica_com_cd_e_usa_o_cd():   # RVB 27/11: 719 m do CD Carrefour → CD Supermercado BH
    p = _paradas("historico_completo_2026-11-27.csv", "PLA-0A05")[0]
    assert p.local.nome_exibicao == "CD Supermercado BH em Contagem MG" and hm(p.saida) == "05:51" and p.em_andamento_no_inicio

def test_sem_coordenadas_nao_unifica_pois_diferentes():   # RNY 26/11: Posto Caxuxa e restaurante ao lado
    ps = _paradas("historico_2026-11-26.csv", "PLA-0A03")
    assert ps[0].local.nome_exibicao.startswith("Posto Caxuxa") and hm(ps[0].saida) == "03:03"

def test_cd_mart_minas_a_208_m_e_reconhecido_e_em_andamento():
    p = _paradas("historico_completo_2026-11-27.csv", "PLA-0A04")[-1]
    assert p.local.nome_exibicao == "CD Supermercados BH em Contagem MG" and p.em_andamento

def test_chegada_recente_em_cd_conta():                   # HDI 27/11 chegou 06:41, arquivo termina 06:45
    p = _paradas("historico_completo_2026-11-27.csv", "PLA-0A02")[-1]
    assert p.local.nome_exibicao == "CD de Uberlândia" and hm(p.chegada) == "06:41" and p.em_andamento

def test_parada_fora_do_raio_do_cd_contagem_nao_e_chegada():  # RVB 26/11: 195 m às 00:47 fica fora (raio 150)
    ps = [p for p in _paradas("historico_2026-11-26.csv", "PLA-0A05") if p.local and p.local.nome_exibicao == "CD de Contagem"]
    assert hm(ps[0].chegada) == "01:07"

def test_registros_esparsos_com_ignicao_desligada():      # GTN 26/11: 3 registros em 4 h
    ps = _paradas("historico_2026-11-26.csv", "PLA-0A01")
    assert len(ps) == 1 and ps[0].em_andamento and ps[0].local.nome_exibicao.startswith("Cemil")
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar `detectar_paradas` e `veio_em_movimento`.**
- [ ] **Step 4: Rodar e ver passar** — `7 passed`.
- [ ] **Step 5: Commit** — `git commit -m "feat(mensagem): detector de paradas com unificacao de manobras"`

---

### Task 4: Regras e texto da mensagem + lista Conferir (gabarito)

**Files:**
- Create: `mensagem_saidas/regras.py`
- Test: `tests/test_mensagem_regras.py`

**Interfaces:**
- Consumes: `ler_exportacao_ss`, `detectar_paradas`, `veio_em_movimento`, `Local`.
- Produces: `@dataclass ItemConferir(placa: str, motivo: str, parada: Parada | None, chave: str)` — `motivo` ∈ `{"local_desconhecido", "em_movimento_no_inicio", "sem_paradas"}`; `chave` estável (`f"{placa}|{motivo}|{inicio:%Y%m%d%H%M}"`) para ignorar/aceitar. `@dataclass ResultadoMensagem(texto: str, conferir: list[ItemConferir], data_mensagem: date, aviso_periodo: str | None)` — `aviso_periodo` preenchido quando o registro mais antigo do arquivo já é da data da mensagem: `"A planilha começa em DD/MM às HH:MM: saídas da véspera não aparecem. Exporte a partir das 18:00 do dia anterior."`. `montar_mensagem(df: pd.DataFrame, locais: list[Local], ignorar: set[str] = frozenset()) -> ResultadoMensagem`.

Regras (spec §6): data da mensagem = data do registro mais recente; origem = primeira parada (item `em_movimento_no_inicio` só se `veio_em_movimento` **e** a origem durar < `ORIGEM_CONFIAVEL_MIN`; ex.: RNY 27/11 andou 21:01–21:15 e dormiu no posto → sem item); origem sempre entra; depois dela, Matriz (qualquer duração), CD (≥ 5 min ou em andamento), Posto/Restaurante (≥ 30 min); Cliente/Outro não entram; desconhecida ≥ 30 min → só Conferir. Origem desconhecida → frase com `Cidade UF` + item Conferir. Placa sem paradas → `PLACA: Em trânsito.` + item `sem_paradas`. "de ontem" quando `horario.date() < data_mensagem` (compara data, não hora).

- [ ] **Step 1: Escrever os testes**

```python
def _gab(nome):
    blocos = (FIX / nome).read_text(encoding="utf-8").strip().split("\n\n")
    return blocos[0], {b.split(":", 1)[0]: b for b in blocos[1:]}

def _minutos(frase):  # ["05:43", ...] → minutos
    return [int(h) * 60 + int(m) for h, m in re.findall(r"(\d{2}):(\d{2})", frase)]

def _confere(gerada, esperada):
    norm = lambda s: re.sub(r"\d{2}:\d{2}", "HH:MM", " ".join(s.split()))
    assert norm(gerada) == norm(esperada), (gerada, esperada)
    assert all(abs(a - b) <= 2 for a, b in zip(_minutos(gerada), _minutos(esperada))), (gerada, esperada)

@pytest.mark.parametrize("arquivo,gabarito", [
    ("historico_completo_2026-11-27.csv", "gabarito_2026-11-27.txt"),
    ("historico_2026-11-26.csv", "gabarito_2026-11-26.txt"),
])
def test_bate_com_gabarito(arquivo, gabarito):
    res = montar_mensagem(ler_exportacao_ss(str(FIX / arquivo)), banco.listar_locais())
    cab, esperadas = _gab(gabarito)
    blocos = res.texto.split("\n\n")
    assert blocos[0] == cab
    geradas = {b.split(":", 1)[0]: b for b in blocos[1:]}
    assert list(geradas) == sorted(geradas)
    for placa, esperada in esperadas.items():
        _confere(geradas[placa], esperada)

def test_conferir_27_11_vazio():
    res = montar_mensagem(ler_exportacao_ss(str(FIX / "historico_completo_2026-11-27.csv")), banco.listar_locais())
    assert res.conferir == [] and res.aviso_periodo is None

def test_aviso_quando_planilha_comeca_a_meia_noite():
    res = montar_mensagem(ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv")), banco.listar_locais())
    assert "18:00" in res.aviso_periodo

def test_conferir_26_11():
    res = montar_mensagem(ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv")), banco.listar_locais())
    motivos = {(i.placa, i.motivo) for i in res.conferir}
    assert ("PLA-0A02", "local_desconhecido") in motivos            # "Riacho de areia"
    assert ("PLA-0A06", "local_desconhecido") in motivos            # 4 h em Carmópolis de Minas
    assert ("PLA-0A03", "em_movimento_no_inicio") in motivos
    assert "Carmópolis" not in res.texto                            # desconhecida no meio da viagem não entra

def test_ignorar_remove_item():
    df = ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv"))
    chave = montar_mensagem(df, banco.listar_locais()).conferir[0].chave
    assert chave not in {i.chave for i in montar_mensagem(df, banco.listar_locais(), {chave}).conferir}

def test_de_ontem_na_virada_do_ano():
    df = pd.DataFrame({"placa": ["PLA-9Z99"] * 3, "data_hora": pd.to_datetime(["2026-12-31 23:00", "2026-12-31 23:50", "2027-01-01 01:00"]),
                       "velocidade_kmh": [0, 40, 50], "ignicao": [None] * 3, "evento": [""] * 3, "poi_ss": ["CECOTI MATRIZ", None, None],
                       "poi_ss_dist_m": [10, None, None], "endereco": [""] * 3, "cidade": ["Cláudio"] * 3, "uf": ["MG"] * 3, "lat": [None] * 3, "lon": [None] * 3})
    res = montar_mensagem(df, banco.listar_locais())
    assert res.texto.startswith("*Horário de saída das Carretas 01/01/2027*")
    assert "PLA-9Z99: Saída da Matriz as 23:50 de ontem." in res.texto
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar `montar_mensagem`.** Se algum gabarito não bater, ajustar o detector/regras — **não** o gabarito nem a tolerância; se uma regra do spec impedir o acerto, parar e reportar.
- [ ] **Step 4: Rodar e ver passar** — `7 passed`.
- [ ] **Step 5: Commit** — `git commit -m "feat(mensagem): regras, texto e lista Conferir validados contra o gabarito"`

---

### Task 5: Sugestão de nome (OpenStreetMap) e relatório Excel para cadastro na SS

**Files:**
- Create: `mensagem_saidas/sugestao.py`, `mensagem_saidas/relatorio.py`
- Test: `tests/test_mensagem_sugestao_relatorio.py`

**Interfaces:**
- Consumes: `ItemConferir`, `Parada`.
- Produces: `sugerir_nome(lat: float, lon: float, *, buscar: Callable[[str], bytes] | None = None, timeout_s: float = 4.0) -> str | None` — consulta Overpass (`https://overpass-api.de/api/interpreter`) por nós/vias com `amenity~fuel|restaurant|fast_food|cafe` ou `shop`/`office`/`industrial` com `name` num raio de 300 m; devolve o nome do mais próximo (preferindo `amenity=fuel`); cache em memória por `(round(lat,4), round(lon,4))`; qualquer exceção/timeout → `None`. `buscar` injeta o transporte (testes). User-Agent genérico `Automacao-Relatorio-Rastreio/1.0`.
  `gerar_excel_pontos(itens: list[ItemConferir], sugestoes: dict[str, str | None]) -> bytes` — colunas: `Placa, Início, Fim, Duração (min), Nome sugerido, Tipo, Endereço, Cidade, UF, Latitude, Longitude, Link Google Maps, POI SS mais próximo, Distância POI SS (m), Raio sugerido (m), Cadastrado na SS` (última vazia para o aprendiz marcar); só itens `local_desconhecido`.

- [ ] **Step 1: Escrever os testes**

```python
OVERPASS = json.dumps({"elements": [
    {"type": "node", "lat": -23.1003, "lon": -46.6096, "tags": {"name": "Restaurante X"}},
    {"type": "node", "lat": -23.1005, "lon": -46.6097, "tags": {"amenity": "fuel", "name": "Posto Dom Pedro"}}]}).encode()

def test_sugere_posto_mais_proximo():
    assert sugerir_nome(-23.10011, -46.60962, buscar=lambda q: OVERPASS) == "Posto Dom Pedro"

def test_falha_de_rede_retorna_none():
    def quebra(q): raise TimeoutError
    assert sugerir_nome(-1.0, -1.0, buscar=quebra) is None

def test_excel_tem_colunas_e_link():
    res = montar_mensagem(ler_exportacao_ss(str(FIX / "historico_2026-11-26.csv")), banco.listar_locais())
    dados = gerar_excel_pontos(res.conferir, {})
    df = pd.read_excel(io.BytesIO(dados))
    assert list(df.columns)[-1] == "Cadastrado na SS" and "Link Google Maps" in df.columns
    assert set(df["Placa"]) == {"PLA-0A02", "PLA-0A06"}
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `sugestao.py` (urllib, POST `data=` com a query Overpass QL) e `relatorio.py` (pandas → `openpyxl`).
- [ ] **Step 4: Rodar e ver passar** — `3 passed`.
- [ ] **Step 5: Commit** — `git commit -m "feat(mensagem): sugestao de nome via OpenStreetMap e relatorio Excel para cadastro na SS"`

---

### Task 6: Tela "Mensagem de saídas" e cadastro de locais na interface

**Files:**
- Create: `rotas/mensagem.py`, `templates/mensagem_saidas.html`, `templates/locais_importantes.html`
- Modify: `app.py` (registrar blueprint), menus laterais de `templates/index.html`, `templates/configuracoes.html`, `templates/auditoria_roteiro.html` (link "Mensagem de saídas"; em Configurações, link "Locais importantes")
- Test: `tests/test_mensagem_rotas.py`

**Interfaces:**
- Consumes: `ler_exportacao_ss`, `montar_mensagem`, `sugerir_nome`, `gerar_excel_pontos`, CRUD de `banco`, `rotas.comum.login_required`, `arquivos.salvar_upload`/`remover_temporario`.
- Produces (blueprint `mensagem`):
  - `GET/POST /mensagem_saidas` — upload (`arquivo`) guarda o caminho em `session["mensagem_arquivo_path"]`; renderiza `aviso_periodo` (se houver) + texto + botão Copiar (JS `navigator.clipboard`) + lista Conferir com sugestão (só para `local_desconhecido`, chamando `sugerir_nome` quando há coordenadas) e formulário de aceite pré-preenchido (nome, gênero, tipo, raio 250, lat/lon, alias = `poi_ss` se houver).
  - `POST /mensagem_saidas/aceitar` — cria o local com `salvar_local` e redireciona para `/mensagem_saidas` (mensagem regerada com o arquivo da sessão).
  - `POST /mensagem_saidas/ignorar` — adiciona `chave` a `session["mensagem_ignorados"]`.
  - `GET /mensagem_saidas/relatorio.xlsx` — `gerar_excel_pontos` dos itens não ignorados.
  - `GET/POST /locais_importantes` — listar, criar, editar, excluir, marcar "cadastrado na SS".
  Todas com `login_required`; formulários com `{{ csrf_input() }}`.

- [ ] **Step 1: Escrever os testes** (cliente logado com usuário criado como em `tests/test_seguranca.py`; `sugestao.sugerir_nome` substituído por `lambda *a, **k: "Posto Sugerido"` via `monkeypatch`)

```python
def test_gera_mensagem_pelo_upload(client_logado):
    r = _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_completo_2026-11-27.csv")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "*Horário de saída das Carretas 27/11/2026*" in html
    assert "PLA-0A05: Saída do CD Supermercado BH em Contagem MG as 05:5" in html

def test_aceitar_cria_local_e_regera(client_logado):
    _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_2026-11-26.csv")
    _post(client_logado, "/mensagem_saidas/aceitar", nome_exibicao="Posto Padre Libério em Papagaios MG", genero="o", tipo="POSTO", raio_m="250", aliases_ss="", latitude="", longitude="")
    assert any(l.nome_exibicao == "Posto Padre Libério em Papagaios MG" for l in banco.listar_locais())

def test_relatorio_xlsx(client_logado):
    _post(client_logado, "/mensagem_saidas", arquivo=FIX / "historico_2026-11-26.csv")
    r = client_logado.get("/mensagem_saidas/relatorio.xlsx")
    assert r.status_code == 200 and r.mimetype.endswith("spreadsheetml.sheet")

def test_exige_login():
    assert app.app.test_client().get("/mensagem_saidas").status_code == 302

def test_planilha_invalida_mostra_erro(client_logado, tmp_path):
    f = tmp_path / "x.csv"; f.write_text("a;b\n1;2\n", encoding="cp1252")
    assert "não reconhecido" in _post(client_logado, "/mensagem_saidas", arquivo=f).get_data(as_text=True).lower()
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** rotas e templates (seguir o visual de `templates/configuracoes.html`; layout do spec §8).
- [ ] **Step 4: Rodar e ver passar** — `5 passed`; `python -m pytest -q` e `ruff check --select F,E9 .` limpos.
- [ ] **Step 5: Verificar no navegador** com Playwright (servidor com `RASTREIO_DATA_DIR` temporário): enviar a fixture de 27/11, conferir o texto, clicar Copiar sem erro de JS, abrir Locais importantes. Screenshot para o usuário.
- [ ] **Step 6: Commit** — `git commit -m "feat(mensagem): tela de mensagem de saidas e cadastro de locais"`

---

### Task 7: Documentação e entrega

**Files:**
- Modify: `README.md` (seção "Mensagem de saídas": como exportar da SS — histórico completo a partir das 18:00 da véspera —, usar a tela, lista Conferir, relatório para o aprendiz; tabela de módulos com `mensagem_saidas/` e `rotas/mensagem.py`)

- [ ] **Step 1:** Atualizar o README.
- [ ] **Step 2:** `python -m pytest -q` → todos passando; `ruff check --select F,E9 .` → limpo.
- [ ] **Step 3:** Rodar a mensagem com os dois arquivos **originais** do usuário (placas reais) e mostrar o resultado lado a lado com as mensagens dele.
- [ ] **Step 4: Commit e push** — `git commit -m "docs: mensagem de saidas"` e `git push origin claude/epic-brahmagupta-mkwy8c`; atualizar a descrição do PR #1.
