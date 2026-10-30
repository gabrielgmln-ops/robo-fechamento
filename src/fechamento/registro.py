# robo-fechamento/src/fechamento/registro.py
"""Banco próprio do robô: histórico de fechamentos e saldos (Etapa 5).

Fica separado da Ledger porque o robô só tem leitura lá. Guarda:
  fechamento_diario  -> um registro por dia (status CONFORME / NAO_CONFORME, totais);
  saldo_fechamento   -> saldo de cada conta no fim do dia, usado como "saldo
                        anterior" no dia seguinte (verificação de continuidade).
Reexecutar o mesmo dia substitui o registro (idempotente).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Column, Date, DateTime, Engine, Integer, MetaData, Numeric, String, Table,
                        delete, insert, select)

meta = MetaData()

fechamento_diario = Table(
    "fechamento_diario", meta,
    Column("dia", Date, primary_key=True),
    Column("status", String(20), nullable=False),  # CONFORME | NAO_CONFORME
    Column("qtd_transacoes", Integer, nullable=False),
    Column("qtd_lancamentos", Integer, nullable=False),
    Column("total_creditos", Numeric(19, 2, asdecimal=True), nullable=False),
    Column("total_debitos", Numeric(19, 2, asdecimal=True), nullable=False),
    Column("alertas_graves", Integer, nullable=False),
    Column("alertas_atencao", Integer, nullable=False),
    Column("arquivo_pdf", String(400)),
    Column("email_enviado", String(5), nullable=False),
    Column("executado_em", DateTime(timezone=True), nullable=False),
)

saldo_fechamento = Table(
    "saldo_fechamento", meta,
    Column("dia", Date, primary_key=True),
    Column("conta_id", String(36), primary_key=True),
    Column("saldo", Numeric(19, 2, asdecimal=True), nullable=False),
)


def preparar(engine: Engine) -> None:
    meta.create_all(engine)


def saldos_do_dia(engine: Engine, dia: date) -> dict[str, Decimal] | None:
    """Saldos gravados no fechamento de `dia`, ou None se esse dia não foi fechado."""
    with engine.connect() as cx:
        existe = cx.execute(select(fechamento_diario.c.dia).where(fechamento_diario.c.dia == dia)).first()
        if existe is None:
            return None
        linhas = cx.execute(select(saldo_fechamento.c.conta_id, saldo_fechamento.c.saldo)
                            .where(saldo_fechamento.c.dia == dia))
        return {cid: Decimal(s).quantize(Decimal("0.01")) for cid, s in linhas}


def gravar(engine: Engine, dia: date, dados: dict, saldos: dict[str, Decimal], executado_em: datetime) -> None:
    with engine.begin() as cx:  # tudo numa transação: ou grava o dia inteiro ou nada
        cx.execute(delete(saldo_fechamento).where(saldo_fechamento.c.dia == dia))
        cx.execute(delete(fechamento_diario).where(fechamento_diario.c.dia == dia))
        cx.execute(insert(fechamento_diario).values(dia=dia, executado_em=executado_em, **dados))
        if saldos:
            cx.execute(insert(saldo_fechamento),
                       [{"dia": dia, "conta_id": c, "saldo": s} for c, s in saldos.items()])


def historico(engine: Engine, limite: int = 30) -> list[dict]:
    with engine.connect() as cx:
        q = select(fechamento_diario).order_by(fechamento_diario.c.dia.desc()).limit(limite)
        return [dict(l._mapping) for l in cx.execute(q)]
