# robo-fechamento/src/fechamento/agendador.py
"""Agendamento do fechamento com APScheduler (Etapa 5).

Por padrão roda às 23h30 (America/Sao_Paulo) e fecha o próprio dia.
Uma falha numa execução é registrada no log e não derruba o agendador.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from fechamento.config import Config
from fechamento.ledger import criar_engine
from fechamento.pipeline import fechar_dia

log = logging.getLogger(__name__)


def executar_fechamento_agendado(config: Config) -> None:
    dia = datetime.now(ZoneInfo(config.fuso)).date()
    try:
        fechar_dia(config, criar_engine(config.ledger_database_url),
                   criar_engine(config.robo_database_url), dia)
    except Exception:  # noqa: BLE001 - o agendador precisa sobreviver a qualquer erro
        log.exception("fechamento_falhou", extra={"dia": dia.isoformat()})


def criar_agendador(config: Config) -> BlockingScheduler:
    agendador = BlockingScheduler(timezone=ZoneInfo(config.fuso))
    agendador.add_job(
        executar_fechamento_agendado, CronTrigger.from_crontab(config.cron_fechamento, timezone=ZoneInfo(config.fuso)),
        args=[config], id="fechamento_diario", replace_existing=True,
        max_instances=1,           # nunca dois fechamentos ao mesmo tempo
        coalesce=True,             # se o PC dormiu e perdeu várias, roda só uma
        misfire_grace_time=3600,   # aceita rodar até 1h atrasado
    )
    return agendador


def agendar(config: Config) -> None:
    agendador = criar_agendador(config)
    job = agendador.get_job("fechamento_diario")
    log.info("agendador_iniciado", extra={"cron": config.cron_fechamento, "fuso": config.fuso})
    print(f"Agendado: '{config.cron_fechamento}' ({config.fuso}). Ctrl+C para parar.")
    try:
        agendador.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("agendador_parado", extra={"job": job.id if job else None})
