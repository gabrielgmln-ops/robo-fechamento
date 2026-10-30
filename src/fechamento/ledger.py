# robo-fechamento/src/fechamento/ledger.py
"""Leitura dos lançamentos da Ledger API direto do banco (Etapa 0).

O schema espelha as migrações V1/V3 da Ledger (conta, transacao, lancamento).
O robô só faz SELECT: nunca escreve no banco da Ledger.

Datas: tudo é gravado e consultado em UTC. O "dia contábil" é definido no fuso
configurado (America/Sao_Paulo) e convertido para um intervalo UTC [início, fim).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import (Column, DateTime, Engine, ForeignKey, Integer, MetaData, Numeric,
                        String, Table, create_engine, select)

log = logging.getLogger(__name__)

metadata = MetaData()

# Mesmas colunas da Ledger (V1). Uuid vira String(36) para funcionar também no SQLite.
conta = Table(
    "conta", metadata,
    Column("id", String(36), primary_key=True),
    Column("titular", String(120), nullable=False),
    Column("tipo", String(20), nullable=False),  # CLIENTE | INTERNA
    Column("criada_em", DateTime(timezone=True), nullable=False),
)
transacao = Table(
    "transacao", metadata,
    Column("id", String(36), primary_key=True),
    Column("tipo", String(20), nullable=False),  # TRANSFERENCIA | DEPOSITO
    Column("conta_origem_id", String(36), nullable=False),
    Column("conta_destino_id", String(36), nullable=False),
    Column("valor", Numeric(19, 2, asdecimal=True), nullable=False),
    Column("descricao", String(140)),
    Column("criada_em", DateTime(timezone=True), nullable=False),
)
lancamento = Table(
    "lancamento", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Sem FK aqui de propósito: o robô precisa conseguir ENXERGAR lançamento órfão
    # mesmo num banco sintético sem as restrições da Ledger real.
    Column("transacao_id", String(36), nullable=False),
    Column("conta_id", String(36), ForeignKey("conta.id"), nullable=False),
    Column("tipo", String(10), nullable=False),  # DEBITO | CREDITO
    Column("valor", Numeric(19, 2, asdecimal=True), nullable=False),
    Column("criado_em", DateTime(timezone=True), nullable=False),
)

COLUNAS_LANCAMENTO = ["id", "transacao_id", "conta_id", "tipo", "valor", "criado_em",
                      "titular", "tipo_conta", "valor_transacao"]


@dataclass(frozen=True)
class Periodo:
    """Dia contábil no fuso local, com o intervalo equivalente em UTC."""
    dia: date
    inicio_utc: datetime
    fim_utc: datetime  # exclusivo

    @classmethod
    def do_dia(cls, dia: date, fuso: str = "America/Sao_Paulo") -> "Periodo":
        tz = ZoneInfo(fuso)
        inicio = datetime.combine(dia, time.min, tzinfo=tz)
        fim = datetime.combine(dia + timedelta(days=1), time.min, tzinfo=tz)
        return cls(dia, inicio.astimezone(timezone.utc), fim.astimezone(timezone.utc))


def criar_engine(url: str) -> Engine:
    # pool_pre_ping evita usar conexão morta quando o robô fica horas parado.
    return create_engine(url, pool_pre_ping=True, future=True)


def _utc(valor: datetime) -> datetime:
    """SQLite devolve datetime sem fuso; tudo é gravado em UTC, então assume UTC."""
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc)


def _consulta_lancamentos(fim_utc: datetime, inicio_utc: datetime | None = None):
    # LEFT JOIN em transacao: lançamento sem transação aparece com valor_transacao nulo.
    q = (
        select(
            lancamento.c.id, lancamento.c.transacao_id, lancamento.c.conta_id,
            lancamento.c.tipo, lancamento.c.valor, lancamento.c.criado_em,
            conta.c.titular, conta.c.tipo.label("tipo_conta"),
            transacao.c.valor.label("valor_transacao"),
        )
        .select_from(
            lancamento.join(conta, lancamento.c.conta_id == conta.c.id)
            .outerjoin(transacao, lancamento.c.transacao_id == transacao.c.id)
        )
        .where(lancamento.c.criado_em < fim_utc)
        .order_by(lancamento.c.id)
    )
    if inicio_utc is not None:
        q = q.where(lancamento.c.criado_em >= inicio_utc)
    return q


def _para_dataframe(linhas) -> pd.DataFrame:
    df = pd.DataFrame([dict(l._mapping) for l in linhas], columns=COLUNAS_LANCAMENTO)
    if df.empty:
        return df
    # Na Ledger real (PostgreSQL) os ids chegam como uuid.UUID; padroniza em texto.
    df["transacao_id"] = df["transacao_id"].map(str)
    df["conta_id"] = df["conta_id"].map(str)
    # Garante Decimal (nunca float) e datas com fuso UTC.
    df["valor"] = df["valor"].map(lambda v: Decimal(v).quantize(Decimal("0.01")))
    df["valor_transacao"] = df["valor_transacao"].map(
        lambda v: None if v is None or pd.isna(v) else Decimal(v).quantize(Decimal("0.01")))
    df["criado_em"] = df["criado_em"].map(_utc)
    # Valor com sinal: CREDITO soma, DEBITO subtrai (convenção da Ledger).
    df["valor_sinal"] = [v if t == "CREDITO" else -v for v, t in zip(df["valor"], df["tipo"])]
    return df


def ler_lancamentos_do_dia(engine: Engine, periodo: Periodo) -> pd.DataFrame:
    """Lançamentos criados dentro do dia contábil."""
    with engine.connect() as cx:
        df = _para_dataframe(cx.execute(_consulta_lancamentos(periodo.fim_utc, periodo.inicio_utc)))
    log.info("lancamentos_do_dia_lidos", extra={"dia": periodo.dia.isoformat(), "quantidade": len(df)})
    return df


def ler_lancamentos_ate(engine: Engine, fim_utc: datetime) -> pd.DataFrame:
    """Todos os lançamentos até o fim do dia: base para o saldo de fechamento."""
    with engine.connect() as cx:
        df = _para_dataframe(cx.execute(_consulta_lancamentos(fim_utc)))
    log.info("lancamentos_acumulados_lidos", extra={"quantidade": len(df)})
    return df


def ler_contas(engine: Engine, fim_utc: datetime) -> pd.DataFrame:
    """Contas existentes até o fim do dia (inclusive as sem movimento)."""
    q = select(conta.c.id, conta.c.titular, conta.c.tipo).where(conta.c.criada_em < fim_utc).order_by(conta.c.titular)
    with engine.connect() as cx:
        df = pd.DataFrame([dict(l._mapping) for l in cx.execute(q)], columns=["id", "titular", "tipo"])
    df["id"] = df["id"].map(str)  # uuid.UUID no PostgreSQL -> texto
    return df
