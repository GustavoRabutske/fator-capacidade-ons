# Monitor de Geração Renovável

Pipeline de ingestão e API REST para o **fator de capacidade horário** das usinas eólicas e solares
do Sistema Interligado Nacional, a partir dos dados abertos do
[ONS](https://dados.ons.org.br/dataset/fator-capacidade-2).

O fator de capacidade é a razão entre o que a usina gerou e o que ela poderia ter gerado à potência
nominal. É a métrica que permite comparar um parque de 500 MW com um de 30 MW, ou o vento do
Nordeste com o sol do Sudeste, na mesma escala.

**O que o projeto entrega:**

- ETL idempotente dos 12 arquivos mensais de 2025 — 1,94 milhão de medições horárias, 235 usinas
- API REST documentada em `/docs` com três endpoints de consulta
- Um relatório de análise que quantifica a complementaridade entre eólica e solar
- 32 testes cobrindo as regras de limpeza do ETL, a camada de serviço e os endpoints

## Como rodar

Requer Python 3.10+. Nada além de `pip install` — o banco padrão é SQLite, criado no primeiro uso.

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python -m energia.etl --ano 2025    # baixa ~44 MB e carrega o ano (~2 min)
uvicorn energia.api:app --reload    # http://127.0.0.1:8000/docs
```

O ETL guarda os arquivos baixados em `dados/` e pula o download se já existirem. Para carregar só
alguns meses: `python -m energia.etl --ano 2025 --meses 1 2 3`. Para ignorar o cache e rebaixar
tudo — o ONS reprocessa arquivos já publicados: `--refazer-download`.

Por padrão o ETL usa os arquivos Parquet publicados pelo ONS (~3,6 MB/mês contra ~40 MB do CSV,
mesmo conteúdo). `--formato csv` troca a fonte; o leitor decide pela extensão.

### Análise

```bash
python -m energia.analise
```

Imprime o relatório e salva `relatorios/perfil_horario.md` e `relatorios/perfil_horario.csv`.

### PostgreSQL (opcional)

```bash
pip install psycopg2-binary
set ENERGIA_URL_BANCO=postgresql+psycopg2://usuario:senha@localhost/energia
```

As consultas usam apenas construções que o SQLAlchemy compila igual nos dois bancos
(`date()`, `extract()`), então o mesmo código roda sem alteração.

### Variáveis de ambiente

Todas opcionais — os defaults funcionam sem nenhuma configuração.

| variável | default | o que faz |
| :--- | :--- | :--- |
| `ENERGIA_URL_BANCO` | `sqlite:///energia.db` na raiz | qualquer URL que o SQLAlchemy aceite |
| `ENERGIA_DIRETORIO_DADOS` | `dados/` | onde o ETL guarda os arquivos baixados |
| `ENERGIA_DIRETORIO_RELATORIOS` | `relatorios/` | onde a análise grava a saída |
| `ENERGIA_ANO` | `2025` | ano assumido pelo ETL quando `--ano` é omitido |

## Modelo de dados

```
subsistema (4)              usina (235)                      medicao_horaria (1,94 M)
──────────────              ─────────────────                ────────────────────────────
id       PK  'NE'           id_ons        PK  'CJU_BAABL'    id                        PK
nome         'Nordeste'     nome              'Conj. Abil I' usina_id                  FK
                       ┌──< subsistema_id FK ───────────────< instante          TIMESTAMP
                       │    fonte             EOLICA|SOLAR    geracao_programada_mw  NULL
                       │    modalidade                        geracao_verificada_mw
                       │    uf, localizacao                   capacidade_instalada_mw
                       │    latitude, longitude               fator_capacidade
                       │    cod_ponto_conexao                 UNIQUE (usina_id, instante)
```

Três decisões que valem explicar:

**A capacidade instalada fica na medição, não na usina.** Ela muda ao longo do ano conforme os
parques são ampliados — a solar do Nordeste sai de 8.459 MW em janeiro para 9.326 MW em junho de
2025, com 42 usinas virando 44. Guardá-la na dimensão produziria fator de capacidade errado no
retroativo.

**A chave da usina é o `id_ons`, não um id sintético.** É estável entre os arquivos mensais e é a
única coluna realmente única: em 2025 há 228 nomes distintos para 235 usinas, e em quatro dessas
colisões o mesmo nome cobre uma usina eólica *e* uma solar (Conj. Tacaratu 2, Conj. Serra do Mato 2,
Conj. São Basílio 2, Conj. Serra da Babilônia 2). Como chave natural, ela também torna a carga
idempotente sem exigir um lookup a cada linha.

**UF é coluna, não tabela.** São 11 valores e o nome do estado é derivável da sigla; normalizar
seria burocracia sem ganho de consulta.

### Limpeza aplicada na ingestão

O ETL reporta o que descartou a cada mês. Sobre 2025 as regras removeram 1.723 de 1.943.736 linhas
(0,09%):

| regra | motivo |
| :--- | :--- |
| campo obrigatório vazio | 720 linhas em abril sem geração verificada |
| fator fora de `[0, 1.5]` | sobregeração leve é real em parque eólico; acima disso é inconsistência da fonte |
| capacidade não positiva | divisão sem sentido |
| duplicata `(usina, instante)` | mantém o registro mais recente |

Geração programada ausente vira `NULL`, não zero — 28.776 medições de 2025 (1,5%) não têm
programação, e tratá-las como zero distorceria qualquer comparação entre programado e verificado.

## Arquitetura

Quatro camadas com dependência em sentido único: `api` → `servicos` → `repositorio` → `modelos`.

O **repositório** só monta consultas SQLAlchemy e não conhece HTTP; o **serviço** valida parâmetros,
resolve janelas de tempo e levanta exceções de domínio (`ParametroInvalido`, `DadosIndisponiveis`)
que a API traduz em 422 e 404. Isso mantém a regra de negócio testável sem subir servidor — os
testes de serviço rodam direto contra uma sessão em memória — e permite que o script de análise
reaproveite as mesmas consultas agregadas da API sem passar por ela.

O ETL é intencionalmente separado dos demais: ele escreve, todo o resto só lê.

Uma regra que vive na camada de serviço e não no banco nem no router: **toda agregação de fator de
capacidade é `soma(geração) / soma(capacidade)`, nunca a média dos fatores individuais.** Usinas
têm portes muito diferentes e a média simples daria o mesmo peso a um parque de 500 MW e a um de
30 MW. Existe um teste dedicado a isso em `tests/test_servicos.py`.

## API

Documentação interativa em `/docs`. Os instantes estão no horário de Brasília sem fuso explícito,
como na fonte.

### `GET /saude`

Diz se a API está de pé e, principalmente, **a que período a base carregada corresponde** — é por
aqui que se descobre o que `/geracao/ultima-medicao` vai devolver.

```bash
curl "http://127.0.0.1:8000/saude"
```

```json
{
  "status": "ok",
  "periodo_carregado": { "inicio": "2025-01-01T00:00:00", "fim": "2025-12-31T23:00:00" },
  "subsistemas": ["N", "NE", "S", "SE"]
}
```

### `GET /geracao/ultima-medicao`

Fator de capacidade na hora mais recente **presente no banco**, por subsistema e fonte. Aceita
`?fonte=EOLICA|SOLAR`. Não é tempo real — veja [Limitações conhecidas](#limitações-conhecidas).

```bash
curl "http://127.0.0.1:8000/geracao/ultima-medicao?fonte=EOLICA"
```

```json
[
  {
    "subsistema": "NE",
    "nome_subsistema": "Nordeste",
    "fonte": "EOLICA",
    "instante": "2025-12-31T23:00:00",
    "fator_capacidade": 0.335,
    "geracao_verificada_mw": 10478.863,
    "capacidade_instalada_mw": 31281.595,
    "usinas": 140
  }
]
```

### `GET /geracao/historico`

Série filtrável por período, subsistema e fonte. `granularidade` aceita `dia` (padrão) ou `hora`.

```bash
curl "http://127.0.0.1:8000/geracao/historico?inicio=2025-01-01&fim=2025-12-31&subsistema=NE&fonte=SOLAR"
```

```json
{
  "granularidade": "dia",
  "total_pontos": 365,
  "pontos": [
    {
      "instante": "2025-01-01T00:00:00",
      "subsistema": "NE",
      "fonte": "SOLAR",
      "fator_capacidade": 0.1434,
      "geracao_media_mw": 1213.326,
      "capacidade_instalada_mw": 8459.393,
      "usinas": 42
    }
  ]
}
```

A série horária é limitada a 31 dias por requisição — um ano em base horária são ~2 milhões de
linhas agregadas e nenhum cliente consome isso de uma vez. Pedidos maiores recebem 422 com a
orientação de usar `granularidade=dia`.

### `GET /geracao/comparativo`

Eólica contra solar por subsistema no período, com a hora de pico de cada fonte.

```bash
curl "http://127.0.0.1:8000/geracao/comparativo?inicio=2025-07-01&fim=2025-09-30"
```

```json
[
  {
    "subsistema": "NE",
    "nome_subsistema": "Nordeste",
    "eolica": {
      "fator_capacidade": 0.4681,
      "geracao_media_mw": 14396.244,
      "capacidade_instalada_mw": 30757.759,
      "usinas": 146,
      "hora_pico": 23,
      "fator_no_pico": 0.6235
    },
    "solar": { "fator_capacidade": 0.1832, "hora_pico": 14, "...": "..." },
    "diferenca_fator": 0.2849
  }
]
```

## Achados da análise

Fator de capacidade médio do SIN em cada hora do dia, sobre 2025 completo — gerado por
`python -m energia.analise`:

| hora | eólica | solar |
| ---: | :--- | :--- |
| 00h | `0.503` ████████████ | `0.000`  |
| 01h | `0.500` ████████████ | `0.000`  |
| 02h | `0.495` ████████████ | `0.000`  |
| 03h | `0.490` ████████████ | `0.000`  |
| 04h | `0.483` ████████████ | `0.001`  |
| 05h | `0.472` ███████████ | `0.009`  |
| 06h | `0.422` ██████████ | `0.148` ████ |
| 07h | `0.365` █████████ | `0.349` ████████ |
| 08h | `0.320` ████████ | `0.425` ██████████ |
| 09h | `0.268` ██████ | `0.449` ███████████ |
| 10h | `0.228` █████ | `0.465` ███████████ |
| 11h | `0.205` █████ | `0.489` ████████████ |
| 12h | `0.189` █████ | `0.499` ████████████ |
| 13h | `0.198` █████ | `0.541` █████████████ |
| 14h | `0.228` █████ | `0.561` █████████████ |
| 15h | `0.269` ██████ | `0.530` █████████████ |
| 16h | `0.325` ████████ | `0.355` █████████ |
| 17h | `0.378` █████████ | `0.082` ██ |
| 18h | `0.416` ██████████ | `0.005`  |
| 19h | `0.450` ███████████ | `0.001`  |
| 20h | `0.470` ███████████ | `0.000`  |
| 21h | `0.484` ████████████ | `0.000`  |
| 22h | `0.494` ████████████ | `0.000`  |
| 23h | `0.501` ████████████ | `0.000`  |

**1. As fontes se complementam quase perfeitamente ao longo do dia.** A correlação entre as curvas
horárias de eólica e solar é de **−0,96**. A solar concentra toda a produção em 12 horas (06h–17h),
com pico de 56,1% às 14h; a eólica gera nas 24 horas, tem seu vale justamente às 12h (18,9%) e
supera a solar em 15 das 24 horas, com pico de 50,3% à meia-noite.

**2. A carteira somada é muito mais estável que qualquer uma das fontes.** Ao longo do dia a eólica
varia 31 pontos percentuais e a solar 56 p.p. Somadas pela capacidade instalada, a curva do conjunto
oscila apenas **9 p.p.** (27,2% a 36,0%) — o mesmo parque instalado entrega geração muito mais
previsível por combinar as duas tecnologias.

O relatório também quebra a hora de pico por subsistema, onde aparece a diferença de regime entre
regiões: no Norte a eólica pica às 23h com 57,4% de fator médio anual, contra 30,2% no Sul.

## Limitações conhecidas

Vale ler antes de citar qualquer número daqui.

**1. Não é tempo real.** O ONS publica esta série em arquivos mensais, com defasagem.
`/geracao/ultima-medicao` devolve a última hora carregada no banco — com o escopo padrão,
`2025-12-31 23:00`. Consulte `/saude` para ver o período efetivamente carregado.

**2. O pico solar no dado cai às 14h, e isso não está explicado.** A janela de luz vai de 06h a
17h, ou seja, centrada em ~11,5h, mas o máximo aparece às 14h — no Nordeste e no Sudeste, no verão
e no inverno. Foi investigado até onde deu:

- está no arquivo bruto do ONS, não no processamento daqui (recalculado com pandas puro, sem passar
  por este ETL)
- não é *curtailment* de meio-dia: o percentil 90 e o percentil 99 também picam às 14h, e uma
  supressão do meio-dia deixaria o topo da distribuição intacto
- não é artefato do denominador: a capacidade instalada somada é constante ao longo do dia
- o [dicionário de dados oficial](https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/fator_capacidade_2_di/DicionarioDados_FatorCapacidade.pdf)
  descreve `din_instante` apenas como `DATETIME YYYY-MM-DD HH:MM:SS`, sem dizer se marca o início ou
  o fim da hora

Enquanto isso não se resolve, leia a coluna "hora de pico" como *hora do registro no ONS*, não como
hora solar.

**3. Horário de Brasília, sem fuso.** Agregar hora-do-dia de subsistemas em longitudes diferentes
mistura meios-dias solares distintos — o meio-dia solar no Rio Grande do Norte é cerca de 45 minutos
antes do de São Paulo.

**4. Geração está em MWmed.** Conforme o dicionário, `val_geracaoverificada` é potência média na
hora, não instantânea.

**5. O dado publicado diverge do dicionário oficial em quatro pontos**, todos encontrados ao
confrontar um com o outro e tratados no ETL:

| o dicionário diz | o dado de 2025 mostra |
| :--- | :--- |
| `val_geracaoprogramada` não permite nulo | 28.776 medições vêm vazias |
| `id_ons` tem 6 posições | varia de 5 a 11 caracteres |
| `nom_localizacao` só existe para o Nordeste | vem preenchida nos quatro subsistemas |
| — | no Parquet, **toda** coluna numérica vem como texto, e texto ausente vem como string vazia em vez de nulo |

A última é a mais traiçoeira: quem lê o arquivo sem converter tipo soma string silenciosamente, sem
erro nenhum. O ETL converte com `pd.to_numeric` e normaliza string vazia para `NULL`.

**6. Fator de capacidade mede energia entregue, não recurso disponível.** Se uma usina for
restringida pelo operador (*constrained-off*), o fator cai sem que o vento ou o sol tenham caído.
Comparações entre usinas herdam essa limitação.

**7. Escopo de 2025.** O ONS publica desde 2009; o recorte de um ano completo é uma escolha de
projeto, não um limite técnico — `--ano` aceita outros valores.

## Testes

```bash
pytest
```

32 testes, sem rede e sem banco em disco.

Os de serviço e API rodam sobre um SQLite em memória com usinas sintéticas de curvas conhecidas —
picos plantados às 21h para a eólica e às 12h para a solar, e duas usinas eólicas de portes
diferentes no mesmo subsistema para provar que a agregação pondera pela capacidade. Cobrem a
agregação ponderada, as duas granularidades da série, os filtros, o caminho de erro de cada
validação (intervalo invertido, janela horária longa demais, subsistema inexistente, base vazia) e o
contrato JSON dos três endpoints.

Os de ETL (`tests/test_etl.py`) alimentam `limpar()` com um DataFrame no formato cru do ONS — tudo
como texto — e verificam cada regra isoladamente: conversão de tipos, string vazia virando `NULL`,
descarte de fator implausível, preservação da sobregeração leve, desempate de duplicata e o
fallback de coordenada.

## Estrutura

```
energia/
  configuracao.py   variáveis de ambiente e constantes
  banco.py          engine, sessão e dependência do FastAPI
  modelos.py        entidades SQLAlchemy
  esquemas.py       contratos Pydantic da API
  repositorio.py    consultas agregadas
  servicos.py       regra de negócio e validações
  api.py            app FastAPI, rotas e tradução de exceções
  etl.py            download, limpeza e carga (CLI)
  analise.py        relatório de perfil horário (CLI)
tests/
```

## Dados

Os dados são públicos, de autoria do ONS, sob
[Creative Commons Atribuição](http://www.opendefinition.org/licenses/cc-by). Este repositório não
redistribui os arquivos originais: o ETL os baixa direto da fonte.
