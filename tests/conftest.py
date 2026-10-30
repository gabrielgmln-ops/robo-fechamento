# robo-fechamento/tests/conftest.py
"""Fixtures: Ledger sintética e banco do robô em SQLite temporário, por teste."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fechamento.config import Config
from fechamento.ledger import criar_engine
from fechamento.sintetico import semear

ULTIMO_DIA = date(2026, 10, 29)


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        ledger_database_url=f"sqlite:///{tmp_path / 'ledger.db'}",
        robo_database_url=f"sqlite:///{tmp_path / 'robo.db'}",
        pasta_arquivo=tmp_path / "arquivo", pasta_logs=tmp_path / "logs",
        limite_valor_atipico=Decimal("50000.00"),
    )


@pytest.fixture
def ledger(config):
    engine = criar_engine(config.ledger_database_url)
    yield engine
    engine.dispose()  # fecha as conexões (no Windows o SQLite segura o arquivo)


@pytest.fixture
def robo(config):
    engine = criar_engine(config.robo_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def ledger_limpa(ledger):
    semear(ledger, ULTIMO_DIA, anomalias=False)
    return ledger


@pytest.fixture
def ledger_suja(ledger):
    semear(ledger, ULTIMO_DIA, anomalias=True)
    return ledger
