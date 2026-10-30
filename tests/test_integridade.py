# robo-fechamento/tests/test_integridade.py
"""Etapa 1: saldos recalculados e verificações de integridade."""

from datetime import date, timedelta
from decimal import Decimal

from fechamento.integridade import ZERO, somar, verificar_integridade
from fechamento.ledger import Periodo, ler_contas, ler_lancamentos_ate, ler_lancamentos_do_dia
from tests.conftest import ULTIMO_DIA


def _dados(engine, dia=ULTIMO_DIA):
    p = Periodo.do_dia(dia)
    return ler_contas(engine, p.fim_utc), ler_lancamentos_do_dia(engine, p), ler_lancamentos_ate(engine, p.fim_utc)


def test_somar_mantem_decimal_exato():
    # Em float, 0.1 + 0.2 - 0.3 != 0; em Decimal fecha exato.
    assert somar([Decimal("0.10"), Decimal("0.20"), Decimal("-0.30")]) == ZERO


def test_ledger_limpa_e_integra(ledger_limpa):
    res = verificar_integridade(*_dados(ledger_limpa))
    assert res.integra
    assert res.soma_global == ZERO and res.soma_dia == ZERO
    assert res.total_creditos_dia == res.total_debitos_dia
    assert somar(res.saldos["saldo_final"]) == ZERO  # partidas dobradas: saldos somam zero


def test_tesouraria_negativa_e_espelho_dos_clientes(ledger_limpa):
    res = verificar_integridade(*_dados(ledger_limpa))
    tes = res.saldos[res.saldos["tipo"] == "INTERNA"]["saldo_final"].iloc[0]
    clientes = somar(res.saldos[res.saldos["tipo"] == "CLIENTE"]["saldo_final"])
    assert tes == -clientes and tes < ZERO


def test_ledger_suja_falha_somas(ledger_suja):
    res = verificar_integridade(*_dados(ledger_suja))
    assert not res.integra
    assert res.soma_global == Decimal("150.00")  # a perna órfã de 150,00


def test_continuidade_detecta_saldo_anterior_divergente(ledger_limpa):
    contas, dia, acum = _dados(ledger_limpa)
    anterior = verificar_integridade(*_dados(ledger_limpa, ULTIMO_DIA - timedelta(days=1)))
    saldos = dict(zip(anterior.saldos["conta_id"], anterior.saldos["saldo_final"]))
    assert verificar_integridade(contas, dia, acum, saldos).integra
    cid = next(iter(saldos))
    saldos[cid] += Decimal("0.01")  # um centavo de diferença já reprova
    res = verificar_integridade(contas, dia, acum, saldos)
    assert not res.integra
    assert not res.saldos.set_index("conta_id").loc[cid, "confere"]


def test_dia_vazio_e_integro(ledger_limpa):
    res = verificar_integridade(*_dados(ledger_limpa, date(2026, 10, 20)))
    assert res.integra and res.qtd_lancamentos_dia == 0
