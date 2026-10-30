# Robô de Fechamento Diário

Automação de **end-of-day** sobre a [Ledger API](https://github.com/gabrielgmln-ops/Projeto-B-A): ao fim do dia, o robô lê todos os lançamentos, recalcula o saldo de cada conta, verifica a integridade contábil, detecta inconsistências, gera um PDF de fechamento, arquiva por data, envia por e-mail e marca o dia como **CONFORME** ou **NÃO CONFORME**.

> Apenas dados sintéticos. Dinheiro sempre em `Decimal`. Segredos só por variável de ambiente.

## Fluxo

```
Ledger (PostgreSQL, só SELECT)
  └─ Etapa 0  leitura dos lançamentos do dia e do acumulado
  └─ Etapa 1  saldos por conta + integridade (somas = 0, continuidade)
  └─ Etapa 2  inconsistências (órfão, negativo, divergências, atípico)
  └─ Etapa 3  PDF (ReportLab)
  └─ Etapa 4  arquivo dados/arquivo/AAAA/MM/fechamento-AAAA-MM-DD.pdf + e-mail
  └─ Etapa 5  histórico no banco do robô + status + log JSON; agendamento APScheduler
```

## Verificações

| Código | Severidade | O que significa |
|---|---|---|
| `SOMA_GLOBAL_DIFERENTE_DE_ZERO` | GRAVE | Partidas dobradas quebradas: a soma com sinal de todos os lançamentos não dá zero |
| `LANCAMENTO_ORFAO` | GRAVE | Transação sem contrapartida (só débito ou só crédito, ou pernas que não se anulam) |
| `TRANSACAO_INEXISTENTE` | GRAVE | Lançamento aponta para transação que não existe |
| `VALOR_DIVERGENTE_DA_TRANSACAO` | GRAVE | Valor do lançamento diferente do valor da transação |
| `SALDO_NEGATIVO_INDEVIDO` | GRAVE | Conta de CLIENTE ficou negativa em algum momento do dia (a Tesouraria pode) |
| `SALDO_DIVERGENTE` | GRAVE | Saldo do fechamento anterior + movimento do dia ≠ saldo recalculado (histórico alterado) |
| `VALOR_ATIPICO` | ATENÇÃO | Movimento acima de `LIMITE_VALOR_ATIPICO` |

Basta um alerta GRAVE, ou uma verificação de integridade que falhe, para o dia sair **NÃO CONFORME**. Nesse caso, `fechar` termina com código de saída 2 e o log sai em nível `ERROR`.

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
copy .env.example .env

python -m fechamento semear --dia 2026-10-29      # Ledger sintética: 3 dias, anomalias no último
python -m fechamento ler --dia 2026-10-29         # Etapa 0: só lê e resume
python -m fechamento fechar --dia 2026-10-27 --sem-email
python -m fechamento fechar --dia 2026-10-28 --sem-email
python -m fechamento fechar --dia 2026-10-29      # NÃO CONFORME (5 graves, 1 atenção)
python -m fechamento historico
python -m fechamento agendar                      # roda no CRON_FECHAMENTO (padrão 23h30)
```

Contra PostgreSQL: `docker compose up -d` e `LEDGER_DATABASE_URL=postgresql+psycopg://ledger:sintetica@127.0.0.1:5434/ledger`.
Na Ledger real, aponte para o banco dela com um usuário **somente leitura**: o robô nunca escreve lá.

## Testes

```bash
pytest --cov
```

São 36 testes, com cobertura de 98%. Cada anomalia plantada é detectada, e um dia limpo não gera nenhum alerta. A suíte também cobre a adulteração de um lançamento antigo (pega pela continuidade), a idempotência ao reexecutar, o envio de e-mail com SMTP simulado, o agendador sobrevivendo a erro e a CLI.

## Decisões

- **ReportLab em vez de WeasyPrint**: é Python puro. O WeasyPrint exige GTK/Pango no Windows.
- **Banco próprio do robô** (`fechamento_diario`, `saldo_fechamento`): a Ledger é só leitura, e o saldo gravado de D-1 é o que permite pegar alteração retroativa.
- **Dia contábil no fuso de São Paulo**, consultado como intervalo UTC `[início, fim)`.
- **Somas em `Decimal` puro** (`sum(..., Decimal("0.00"))`), sem deixar o pandas converter para float.
