# robo-fechamento/tests/test_inconsistencias.py
"""Etapa 2: cada anomalia plantada é encontrada; dia limpo não gera alerta."""

from decimal import Decimal

import pytest

from fechamento.inconsistencias import Severidade, detectar_inconsistencias, ha_grave
from fechamento.integridade import verificar_integridade
from fechamento.ledger import Periodo, ler_contas, ler_lancamentos_ate, ler_lancamentos_do_dia
from tests.conftest import ULTIMO_DIA


def _alertas(engine, limite=Decimal("50000.00")):
    p = Periodo.do_dia(ULTIMO_DIA)
    contas = ler_contas(engine, p.fim_utc)
    dia, acum = ler_lancamentos_do_dia(engine, p), ler_lancamentos_ate(engine, p.fim_utc)
    return detectar_inconsistencias(verificar_integridade(contas, dia, acum), dia, acum, p.inicio_utc, limite)


def test_dia_limpo_sem_alertas(ledger_limpa):
    assert _alertas(ledger_limpa) == []


@pytest.mark.parametrize("codigo, conta, valor", [
    ("LANCAMENTO_ORFAO", "Ana Sintética", Decimal("150.00")),
    ("TRANSACAO_INEXISTENTE", "Bruno Fictício, Carla Exemplo", Decimal("75.50")),
    ("SALDO_NEGATIVO_INDEVIDO", "Diego Teste", Decimal("-320.00")),
    ("VALOR_DIVERGENTE_DA_TRANSACAO", "Elisa Modelo, Fábio Simulado", Decimal("130.00")),
    ("SOMA_GLOBAL_DIFERENTE_DE_ZERO", "", Decimal("150.00")),
])
def test_anomalias_graves_detectadas(ledger_suja, codigo, conta, valor):
    achados = [a for a in _alertas(ledger_suja) if a.codigo == codigo]
    assert len(achados) == 1
    a = achados[0]
    assert a.severidade == Severidade.GRAVE and a.conta == conta and a.valor == valor


def test_valor_atipico_e_so_atencao(ledger_suja):
    atipicos = [a for a in _alertas(ledger_suja) if a.codigo == "VALOR_ATIPICO"]
    assert [a.severidade for a in atipicos] == [Severidade.ATENCAO]
    assert atipicos[0].valor == Decimal("82000.00")


def test_limite_atipico_configuravel(ledger_suja):
    assert not [a for a in _alertas(ledger_suja, Decimal("100000.00")) if a.codigo == "VALOR_ATIPICO"]


def test_graves_vem_primeiro(ledger_suja):
    alertas = _alertas(ledger_suja)
    sev = [a.severidade for a in alertas]
    assert sev == sorted(sev, key=lambda s: s != Severidade.GRAVE)
    assert ha_grave(alertas)
