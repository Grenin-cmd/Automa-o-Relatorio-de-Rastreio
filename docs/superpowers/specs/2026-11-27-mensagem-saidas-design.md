# Mensagem de saídas das carretas — design

Data: 27/11/2026 · Situação: aguardando aprovação

## 1. Por que existe

Todo dia de manhã o responsável monta, a partir da exportação da SS Telemática,
uma mensagem para o grupo de WhatsApp da logística dizendo **de onde e a que horas
cada carreta saiu**, e as chegadas/saídas relevantes da viagem. Hoje o sistema gera
um texto parecido, mas erra ou omite casos (saída da véspera, CD a 208 m, chegada
recente, "Não informado" tratado como local), então tudo é conferido à mão.

**Objetivo:** gerar essa mensagem em segundos, idêntica à que o responsável escreveria,
deixando para ele apenas uma lista curta de exceções para decidir.

**Sucesso:** para os dias de gabarito (26/11 e 27/11) a mensagem gerada bate com a
mensagem manual, com tolerância de ±2 min nos horários.

### Fora do escopo (não-objetivos)
- Enviar a mensagem ao WhatsApp automaticamente (o usuário copia e cola).
- Cadastrar POIs na plataforma da SS (não há API; o cadastro é manual, feito por um aprendiz).
- Alterar o relatório/resumo existentes (`analise.py`, `analisador_rastreio.py`).
- Usar IA para escrever a mensagem.

### Seria um fracasso mesmo "funcionando" (anti-objetivos)
- Um nome de local errado ir para o grupo (pior que um ponto pendente).
- Uma saída da Matriz sumir sem aviso.
- A mesma planilha gerar mensagens diferentes em execuções diferentes.

## 2. Abordagens consideradas

| | Abordagem | Decisão |
|---|---|---|
| A | Módulo novo dedicado (detector de paradas próprio + cadastro de locais importantes + regras determinísticas + tela própria + testes de gabarito) | **Escolhida.** Previsível, não mexe nos relatórios atuais, testável contra o gabarito. |
| B | Adaptar o relatório existente | Rejeitada: lógica atrelada a raio fixo de 200 m, regras de "residência" e IA; risco de quebrar o relatório atual. |
| C | IA escrevendo a mensagem a partir das regras | Rejeitada: não é confiável (horários/nomes inventados, texto variável). |

## 3. Entradas

Exportações CSV da SS (`cp1252`, separador `;`). Dois formatos conhecidos:

| Formato | Colunas |
|---|---|
| **Histórico** (`Relatório Histórico …csv`) | Placa; Grupo; Data (`dd/mm/aa HH:MM:SS`); Hora; Endereço; Velocidade (`"34 km/h"`); Ignição; Evento; POI; Distância |
| **Histórico completo** (`Relatório histórico completo …csv`) | Placa; Data; Categoria; Descrição; Local; Velocidade (número); Evento; POI; POI - Distância; Latitude / Longitude (`"-20.17 / -44.37"`); Link Google |

Ambos são convertidos para um formato interno único por registro:
`placa, data_hora, velocidade_kmh, ignicao (opcional), evento, poi_ss, poi_ss_dist_m, endereco, cidade, uf, lat (opcional), lon (opcional)`.

- `poi_ss` igual a `"Não informado"` (ou vazio) → sem POI.
- `cidade`/`uf` extraídos do endereço (`… - Cidade - Estado - Brasil`), UF por sigla.
- Formato desconhecido → erro claro listando as colunas lidas.

**Período recomendado de exportação:** das 18:00 do dia anterior até a hora atual
(a SS permite). O sistema funciona com qualquer período.

**Data da mensagem:** a data do registro mais recente do arquivo. Horários antes das
00:00 dessa data recebem o sufixo `de ontem`.

## 4. Cadastro de locais importantes (novo)

Tabela SQLite `locais_importantes`, editável em **Configurações**:

| Campo | Exemplo |
|---|---|
| `nome_exibicao` (texto exato da mensagem, inclui cidade/rodovia quando o usuário inclui) | `Posto Caxuxa na BR-262 em Luz MG`, `Matriz`, `CD de Contagem` |
| `genero` (`o`/`a`) → do/no, da/na | `o` |
| `tipo` | `MATRIZ`, `CD`, `POSTO`, `RESTAURANTE`, `CLIENTE`, `OUTRO` |
| `aliases_ss` (nomes de POI da SS que correspondem a este local) | `POSTO CAXUXA LUZ BR-262 EM LUZ`, `RESTAURANTE CAXUXA` |
| `latitude`, `longitude` (opcionais) | `-23.10011`, `-46.60962` |
| `raio_m` (padrão 250) | `250` |
| `cadastrado_na_ss` (sim/não) | `não` |

Carga inicial (a partir das mensagens de gabarito):

| nome_exibicao | gênero | tipo | aliases_ss | raio |
|---|---|---|---|---|
| Matriz | a | MATRIZ | CECOTI MATRIZ, CAMARA FRIA MATRIZ | 250 |
| CD de Contagem | o | CD | CECOTI CD CONTAGEM | 150 |
| CD de Uberlândia | o | CD | CECOTI CD UBERLANDIA | 250 |
| CD Supermercados BH em Contagem MG | o | CD | CD Mart Minas Contagem | 300 |
| CD Supermercado BH em Contagem MG | o | CD | CD SUPERMERCADO BH | 250 |
| Fontini em São Francisco de Paula MG | a | CD | FONTINI AGILMAX SFP | 250 |
| CEMA Central Mineira Atacadista em Ribeirão das Neves | a | CD | CEMA CENTRAL MINEIRA ATACADISTA | 250 |
| Cemil em Patos de Minas MG | a | CLIENTE | CEMIL | 250 |
| Posto Caxuxa na BR-262 em Luz MG | o | POSTO | POSTO CAXUXA LUZ BR-262 EM LUZ, RESTAURANTE CAXUXA | 250 |
| Restaurante Ponto do Peixe em Nova Serrana MG | o | RESTAURANTE | RESTAURANTE PONTO DO PEIXE | 250 |
| Posto Dom Pedro na SP-065 em Atibaia SP | o | POSTO | — (coord. -23.10011, -46.60962) | 300 |

(O raio do CD de Contagem é menor porque, em 26/11, uma parada a 195 m — fora do
pátio — não foi considerada chegada pelo usuário; o do CD Mart Minas é maior porque
as carretas ficam a 208–247 m do ponto da SS.)

## 5. Como uma parada é identificada

1. **Registro parado:** velocidade ≤ 3 km/h.
2. **Parada:** sequência de registros parados.
3. **Unificação de manobras:** duas paradas consecutivas viram uma só quando o
   deslocamento entre elas é curto — com coordenadas, ≤ 1,5 km e ≤ 15 min em movimento;
   sem coordenadas, mesmo `poi_ss` e ≤ 15 min em movimento. **Nunca** se unificam duas
   paradas que caem em locais cadastrados diferentes.
   (Sem coordenadas não se usa o endereço: em 26/11 o RNY saiu do Posto Caxuxa às 03:05 e
   parou 6 min no restaurante ao lado; unificar levaria a saída para 03:12.)
   (Ex.: RVB 27/11 passou a noite a 719 m do "CD CARREFOR" e estacionou no CD Supermercado BH
   às 02:52; o usuário considera que dormiu no CD BH.)
4. **Local da parada**, na ordem:
   1. local do cadastro cujas coordenadas estejam a ≤ `raio_m`;
   2. local do cadastro cujo alias seja o `poi_ss` e `poi_ss_dist_m` ≤ `raio_m`;
   3. sem local (desconhecido) — exibido como `Cidade UF`.
   Numa parada unificada, vale o primeiro trecho que caiu dentro de um local cadastrado
   (é dele o horário de chegada); a saída é sempre a do último trecho.
5. **Horário de chegada:** primeiro registro parado dentro do local.
6. **Horário de saída:** primeiro registro após a parada com velocidade > 3 km/h
   (o veículo volta a andar). Verificado contra os dois gabaritos: todas as saídas ficam
   a ≤ 2 min do horário manual. (Com "≥ 10 km/h" a saída do RNY em 26/11 iria para 03:12.)
7. **Duração da parada:** do horário de chegada ao de saída (não só o trecho com registros parados).
   (Verificado contra o gabarito: todas as saídas ficam a ≤ 2 min do horário manual.)

## 6. Regras da mensagem

Por placa, em ordem cronológica:

1. **Origem** = a parada em andamento no início do arquivo, ou a primeira parada
   se o veículo já estava andando (neste caso, vai para "Conferir": "em movimento no início
   da planilha — saída anterior não coberta"). A origem **sempre** entra:
   - saiu → `Saída {do/da} {nome} as HH:MM.`
   - não saiu até o fim do arquivo → `Está {no/na} {nome}.` (sem horário)
2. Depois da origem, entram:
   - **Matriz**: chegadas e saídas;
   - **CD**: chegadas e saídas (paradas ≥ 5 min ou em andamento no fim do arquivo);
   - **Posto/Restaurante**: paradas ≥ 30 min (ex.: Ponto do Peixe 05:28–06:01 entra; Posto Alpa 04:56–05:22 não);
   - **Cliente/Outro cadastrado**: não entram (só como origem).
   - **Desconhecido** ≥ 30 min: não entra na mensagem; vai para "Conferir".
3. Frases:
   - parada concluída → `Chegada {no/na} {nome} as HH:MM e saiu as HH:MM.`
   - parada em andamento no fim do arquivo → `Chegada {no/na} {nome} as HH:MM.`
     (sem duração mínima para Matriz/CD — ex.: HDI chegou ao CD de Uberlândia 4 min antes do fim)
4. Local desconhecido como origem → `Saída de {Cidade} {UF} as HH:MM.` /
   `Está em {Cidade} {UF}.` + item em "Conferir".
5. Horários anteriores à data da mensagem → `as HH:MM de ontem`.
6. Formato final:

```
*Horário de saída das Carretas DD/MM/AAAA*

PLACA: frase. frase.

PLACA: frase.
```
   Placas em ordem alfabética, uma linha em branco entre elas. "as" sem acento, como o usuário escreve.

## 7. Lista "Conferir" e relatório de pontos não cadastrados

Aparece ao lado da mensagem, só para o usuário:
- parada desconhecida ≥ 30 min (origem ou meio da viagem);
- veículo em movimento no início do arquivo cuja primeira parada dura menos de 2 h
  (se dormiu num local, a origem é confiável);
- aviso geral quando a planilha toda começa no próprio dia (ex.: 00:00): saídas da véspera
  não aparecem — exportar a partir das 18:00 do dia anterior;
- veículo sem nenhuma parada (em trânsito o tempo todo).

Para cada parada desconhecida: placa, início/fim/duração, endereço, cidade/UF,
coordenadas, link do Google Maps, POI da SS mais próximo + distância, e uma
**sugestão de nome**. Ações: **[aceitar]** / **[editar e salvar]** (cria o local no cadastro;
a mensagem é regerada) e **[ignorar]**.

**Sugestão de nome:** consulta ao OpenStreetMap (gratuito, sem chave) pelos pontos de
interesse em até 300 m (postos, restaurantes, empresas); só para paradas desconhecidas
≥ 30 min, com cache local e tempo limite curto. Falha ou sem resultado → sem sugestão.
Nunca entra na mensagem sem o usuário aceitar. (Google Places pode ser adicionado
depois, se a qualidade do OpenStreetMap não bastar.)

**Relatório para o aprendiz:** botão que baixa um Excel com os pontos que o usuário
manteve na lista (nome escolhido, tipo, endereço, coordenadas, link do mapa, raio
sugerido) e a coluna "Cadastrado na SS" para ele marcar. Locais aceitos ficam no
cadastro com `cadastrado_na_ss = não` até serem marcados.

## 8. Tela

Novo item no menu: **Mensagem de saídas**.

```
┌ Enviar planilha da SS [arquivo] [Gerar] ──────────────────────────────────────────┐
┌ Mensagem (pronta para copiar) ──────────────┐  ┌ Conferir (2) ──────────────────────┐
│ *Horário de saída das Carretas 27/11/2026*  │  │ ⚠ RVY-6G50 parado 7h36 sem cadastro│
│                                             │  │   Rod. Dom Pedro I, Atibaia SP      │
│ GTN-1H69: Saída da Matriz as 05:43.         │  │   Sugestão: Posto Dom Pedro …       │
│ …                                           │  │   [aceitar] [editar] [ignorar]      │
│                               [📋 Copiar]   │  │ [⬇ Relatório para cadastro na SS]   │
└─────────────────────────────────────────────┘  └─────────────────────────────────────┘
```

## 9. Testes (gabarito)

- `tests/fixtures/ss/` recebe as duas planilhas com as placas trocadas por placas fictícias
  (mapeamento fixo; demais dados mantidos) e as duas mensagens do usuário.
- Teste compara a mensagem gerada com a manual, por placa: mesmo texto após normalizar
  espaços, com horários a ±2 min.
- 26/11 cobre só as placas cujo trecho está dentro do arquivo (que começa às 00:00):
  RVB e RVY (saída "de ontem" fora do arquivo) e HDI (local sem coordenadas e sem POI)
  ficam fora da comparação e devem aparecer na lista "Conferir".
- Testes unitários para leitura dos dois formatos, unificação de manobras, escolha do
  local, horários de chegada/saída e frases.
- A consulta ao OpenStreetMap é simulada nos testes (sem rede).

## 10. Implementação (decisões do construtor)

- Módulos novos: `mensagem_saidas/` (leitura SS, detector de paradas, regras, texto),
  `rotas/mensagem.py`, template `mensagem_saidas.html`, tabela/migração em `banco.py`.
- Reaproveitar `geo.pontos_dentro_de_algum_poi` / `haversine_metros` e `seguranca`.
- Limiares (3 km/h, 1,5 km, 15 min, 30 min, 5 min, raio 250 m) num só lugar,
  como constantes nomeadas.
- Integração das alterações pendentes do Codespaces do usuário quando estiverem
  disponíveis num branch (o módulo novo é isolado para minimizar conflitos).
