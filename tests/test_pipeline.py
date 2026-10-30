# robo-fechamento/tests/test_pipeline.py
"""Etapa 5 e ponta a ponta: status, histórico, continuidade, agendador e CLI."""

import logging
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import update

from fechamento import agendador, registro
from fechamento.__main__ import main
from fechamento.ledger import lancamento
from fechamento.pipeline import CONFORME, NAO_CONFORME, fechar_dia
from tests.conftest import ULTIMO_DIA


def _fechar_tres_dias(config, ledger, robo):
    return [fechar_dia(config, ledger, robo, ULTIMO_DIA - timedelta(days=d), enviar=False) for d in (2, 1, 0)]


def test_dias_limpos_conformes_e_historico(config, ledger_limpa, robo):
    resultados = _fechar_tres_dias(config, ledger_limpa, robo)
    assert [r.status for r in resultados] == [CONFORME] * 3
    assert all(r.pdf.exists() for r in resultados)
    assert [h["status"] for h in registro.historico(robo)] == [CONFORME] * 3
    # O 3º dia foi conferido contra os saldos gravados no 2º (continuidade real).
    assert set(resultados[2].integridade.saldos["origem_anterior"]) == {"fechamento anterior"}


def test_dia_com_anomalias_nao_conforme(config, ledger_suja, robo):
    r = _fechar_tres_dias(config, ledger_suja, robo)[-1]
    assert r.status == NAO_CONFORME and not r.conforme
    h = registro.historico(robo)[0]
    assert h["status"] == NAO_CONFORME and h["alertas_graves"] == 5 and h["alertas_atencao"] == 1


def test_lancamento_antigo_alterado_e_detectado(config, ledger_limpa, robo):
    """Se alguém mexe num lançamento de um dia já fechado, o dia seguinte acusa."""
    fechar_dia(config, ledger_limpa, robo, ULTIMO_DIA - timedelta(days=1), enviar=False)
    with ledger_limpa.begin() as cx:  # adultera o 1º lançamento (de dois dias atrás)
        cx.execute(update(lancamento).where(lancamento.c.id == 1).values(valor=Decimal("999.99")))
    r = fechar_dia(config, ledger_limpa, robo, ULTIMO_DIA, enviar=False)
    assert r.status == NAO_CONFORME
    assert any(a.codigo == "SALDO_DIVERGENTE" for a in r.alertas)


def test_reexecucao_e_idempotente(config, ledger_limpa, robo):
    fechar_dia(config, ledger_limpa, robo, ULTIMO_DIA, enviar=False)
    fechar_dia(config, ledger_limpa, robo, ULTIMO_DIA, enviar=False)
    assert len(registro.historico(robo)) == 1


def test_nao_conforme_loga_em_erro(config, ledger_suja, robo, caplog):
    with caplog.at_level(logging.INFO):
        fechar_dia(config, ledger_suja, robo, ULTIMO_DIA, enviar=False)
    fim = [r for r in caplog.records if r.getMessage() == "fechamento_concluido"][0]
    assert fim.levelno == logging.ERROR and fim.status == NAO_CONFORME


def test_agendador_registra_job_com_cron(config):
    job = agendador.criar_agendador(config).get_job("fechamento_diario")
    assert job is not None and job.max_instances == 1 and job.coalesce


def test_execucao_agendada_sobrevive_a_erro(config, caplog):
    with patch("fechamento.agendador.fechar_dia", side_effect=RuntimeError("banco fora")), \
            caplog.at_level(logging.ERROR):
        agendador.executar_fechamento_agendado(config)  # não pode levantar
    assert any(r.getMessage() == "fechamento_falhou" for r in caplog.records)


def test_cli_semear_fechar_historico(config, monkeypatch, capsys):
    for chave, valor in {"LEDGER_DATABASE_URL": config.ledger_database_url,
                         "ROBO_DATABASE_URL": config.robo_database_url,
                         "PASTA_ARQUIVO": str(config.pasta_arquivo), "PASTA_LOGS": str(config.pasta_logs),
                         "SMTP_USUARIO": "", "SMTP_SENHA": "", "EMAIL_DESTINATARIOS": ""}.items():
        monkeypatch.setenv(chave, valor)
    try:
        assert main(["semear", "--dia", ULTIMO_DIA.isoformat()]) == 0
        assert main(["ler", "--dia", ULTIMO_DIA.isoformat()]) == 0
        assert main(["fechar", "--dia", "2026-10-28", "--sem-email"]) == 0  # CONFORME
        assert main(["fechar", "--dia", ULTIMO_DIA.isoformat()]) == 2       # NÃO CONFORME
        assert main(["historico"]) == 0
    finally:
        for h in list(logging.getLogger().handlers):  # solta o arquivo de log (Windows)
            h.close()
            logging.getLogger().removeHandler(h)
    saida = capsys.readouterr().out
    assert "NÃO CONFORME" in saida and "NAO_CONFORME" in saida
