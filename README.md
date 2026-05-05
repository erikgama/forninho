# Forninho

[![CI](https://github.com/erikgama/forninho/actions/workflows/ci.yml/badge.svg)](https://github.com/erikgama/forninho/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![Release: v0.1.2](https://img.shields.io/badge/release-v0.1.2-blue.svg)](https://github.com/erikgama/forninho/releases/tag/v0.1.2)

<p align="center">
  <img src="docs/assets/forninho-banner.png" alt="Banner do Forninho" width="900">
</p>

Forninho é uma CLI de warm-up de banco para MySQL e Oracle HeatWave.

Depois de uma migração, um banco novo pode começar com caches frios e
estatísticas incompletas para o otimizador. O Forninho executa consultas reais
da aplicação a partir de um arquivo `.sql`, com concorrência controlada, para
ajudar a aquecer o buffer pool e revelar consultas lentas ou frágeis antes de
apontar o tráfego de produção para o novo banco.

## Recursos

- Carrega consultas de arquivos `.sql` com um separador que respeita comentários
  e strings.
- Filtra comandos DDL e troca de schema, como `CREATE`, `DROP`, `ALTER` e `USE`.
- Deduplica consultas parecidas normalizando literais.
- Executa nos modos `sequential`, `parallel` ou `two-phase`.
- Pré-aquece o pool de conexões de acordo com `--threads`, com retry e reuso.
- Gera relatórios em CSV ou JSON.
- Mantém senhas do banco fora da saída do terminal, logs e relatórios.
- Trata `Ctrl+C` com encerramento controlado e exibe resultados parciais.

## Requisitos

- Python 3.11+
- Banco compatível com MySQL

Para bancos de tamanho próximo ao de produção, comece com conjuntos de consultas
de baixo impacto e valide o relatório gerado antes de aumentar a concorrência.

## Início rápido

Crie um ambiente virtual e instale o Forninho em modo editável:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Inspecione as consultas sem conectar no banco:

```bash
forninho run \
  --host my-db.example.com \
  --user admin \
  --database airportdb \
  --sql ./forninho_airportdb_light.sql \
  --dry-run
```

Execute um warm-up sequencial pequeno:

```bash
export DB_PASSWORD='your-password'

forninho run \
  --host my-db.example.com \
  --user admin \
  --database airportdb \
  --sql ./forninho_airportdb_light.sql \
  --mode sequential \
  --iterations 1 \
  --threads 1 \
  --timeout 500 \
  --connect-timeout 10 \
  --connect-retries 8 \
  --output ./reports/forninho_light.csv
```

Execute o warm-up padrão em duas fases:

```bash
export DB_PASSWORD='your-password'

forninho run \
  --host my-db.example.com \
  --user admin \
  --database airportdb \
  --sql ./queries.sql \
  --iterations 3 \
  --threads 4
```

Gere um relatório JSON:

```bash
export DB_PASSWORD='your-password'

forninho run \
  --host my-db.example.com \
  --user admin \
  --database airportdb \
  --sql ./queries.sql \
  --iterations 5 \
  --threads 8 \
  --output ./reports/forninho_report.json \
  --format json
```

Durante o desenvolvimento, também é possível executar o projeto como script:

```bash
python3 forninho.py --help
```

## Opções da CLI

| Flag | Descrição | Padrão |
| --- | --- | --- |
| `--host` | Host do banco | obrigatório |
| `--port` | Porta do banco | `3306` |
| `--user` | Usuário do banco | obrigatório |
| `--password` | Senha. Prefira usar `DB_PASSWORD` | `DB_PASSWORD` |
| `--database` | Banco alvo | obrigatório |
| `--sql` | Arquivo `.sql` com consultas | obrigatório |
| `--mode` | `sequential`, `parallel` ou `two-phase` | `two-phase` |
| `--iterations` | Iterações por consulta | `3` |
| `--threads` | Threads simultâneas na fase concorrente | `4` |
| `--delay-ms` | Intervalo entre execuções, em milissegundos | `0` |
| `--ignore-errors` | Continua depois de erros em consultas | `true` |
| `--timeout` | Timeout por consulta, em segundos | `30` |
| `--connect-timeout` | Timeout para abrir conexão com o banco, em segundos | `10` |
| `--connect-retries` | Tentativas para abrir conexão com o banco | `8` |
| `--connect-retry-delay` | Intervalo entre tentativas de conexão, em segundos | `2.0` |
| `--gate-error-pct` | Aborta a fase 2 se a taxa de erro solo exceder este valor | `50.0` |
| `--gate-slowest-ratio` | Aborta a fase 2 se o p95 solo se aproximar do timeout | `0.9` |
| `--force` | Ignora o critério e executa a fase concorrente | `false` |
| `--output` | Caminho do relatório | automático |
| `--format` | `csv` ou `json` | `csv` |
| `--dry-run` | Lista as consultas executáveis sem rodá-las | `false` |

## Como o carregamento funciona

Consultas vindas de um arquivo `.sql` usam `weight=1`; por isso, cada consulta
única é executada `iterations` vezes em cada fase selecionada.

Durante o carregamento, consultas duplicadas são agrupadas depois da
normalização dos literais. Isso evita executar repetidamente o mesmo padrão de
consulta quando apenas os valores literais mudam.

O separador SQL entende:

- Strings com aspas simples.
- Strings com aspas duplas.
- Identificadores entre crases.
- Comentários de linha com `--` ou `#`.
- Comentários de bloco com `/* ... */`.

O carregador ignora:

- Comandos vazios.
- Comandos DDL: `CREATE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`,
  `RENAME`.
- Comandos de troca de schema: `USE`.

## Relatórios e logs

Se nenhum caminho de saída for informado, o Forninho grava um relatório como:

```text
./forninho_report_YYYYMMDD_HHMMSS.csv
```

Os logs de execução são gravados em:

```text
~/.forninho/logs/YYYYMMDD_HHMMSS.log
```

O repositório ignora relatórios gerados por padrão. Use `./reports/` para
execuções locais ou informe um caminho fora do repositório ao testar contra
bancos privados.

## Segurança

- Prefira `DB_PASSWORD` em vez de `--password` para evitar segredo no histórico
  do shell.
- Não versione arquivos `.env` nem relatórios locais de bancos privados.
- A CLI não imprime senhas do banco em logs, relatórios ou saída do terminal.
- Revise qualquer arquivo `.sql` antes de executá-lo contra um banco importante.

## Desenvolvimento

Instale localmente:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Rode os testes:

```bash
python3 -m unittest discover -s tests
```

Rode uma checagem de sintaxe:

```bash
python3 -m compileall forninho.py core tests
```

## Estrutura do projeto

```text
forninho/
├── .github/workflows/ci.yml       # CI do GitHub Actions
├── docs/assets/forninho-banner.png # Asset visual do README
├── forninho.py                    # Ponto de entrada da CLI
├── core/
│   ├── connection.py              # ConnectionManager e configuração do pool
│   ├── engine.py                  # WarmupEngine
│   ├── metrics.py                 # MetricsCollector e exportadores
│   └── query_loader.py            # Carregamento SQL e deduplicação
├── tests/                         # Testes de regressão com unittest
├── forninho_airportdb.sql         # Conjunto completo de consultas Airport DB
├── forninho_airportdb_light.sql   # Conjunto menor de consultas Airport DB
├── pyproject.toml
├── requirements.txt
└── README.md
```
