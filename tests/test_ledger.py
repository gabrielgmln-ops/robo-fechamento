# robo-fechamento/tests/test_ledger.py
"""Etapa 0: leitura dos lançamentos e recorte do dia contábil."""

from datetime import date, datetime, timezone
from decimal import Decimal

from fechamento.ledger import Periodo, ler_contas, ler_lancamentos_ate, ler_lancamentos_do_dia
from tests.conftest import ULTIMO_DIA


def test_periodo_converte_dia_local_para_utc():
    p = Periodo.do_dia(date(2026, 10, 29))
    # São Paulo é UTC-3: 00h local = 03h UTC
    assert p.inicio_utc == datetime(2026, 10, 29, 3, tzinfo=timezone.utc)
    assert p.fim_utc == datetime(2026, 10, 30, 3, tzinfo=timezone.utc)


def test_le_lancamentos_do_dia_em_decimal_com_sinal(ledger_limpa):
    p = Periodo.do_dia(ULTIMO_DIA)
    df = ler_lancamentos_do_dia(ledger_limpa, p)
    assert len(df) > 0
    assert all(isinstance(v, Decimal) for v in df["valor"])
    for valor, tipo, sinal in zip(df["valor"], df["tipo"], df["valor_sinal"]):
        assert sinal == (valor if tipo == "CREDITO" else -valor)
    assert all(p.inicio_utc <= q < p.fim_utc for q in df["criado_em"])


def test_acumulado_inclui_dias_anteriores(ledger_limpa):
    p = Periodo.do_dia(ULTIMO_DIA)
    assert len(ler_lancamentos_ate(ledger_limpa, p.fim_utc)) > len(ler_lancamentos_do_dia(ledger_limpa, p))


def test_dia_sem_movimento_devolve_vazio(ledger_limpa):
    assert ler_lancamentos_do_dia(ledger_limpa, Periodo.do_dia(date(2026, 1, 1))).empty


def test_le_contas_incluindo_tesouraria(ledger_limpa):
    contas = ler_contas(ledger_limpa, Periodo.do_dia(ULTIMO_DIA).fim_utc)
    assert len(contas) == 7
    assert (contas["tipo"] == "INTERNA").sum() == 1
