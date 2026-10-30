# robo-fechamento/src/fechamento/pipeline.py
"""Orquestra o fechamento de um dia, do SELECT ao e-mail (Etapas 0 a 5 juntas).

ler -> recalcular saldos -> verificar integridade -> detectar inconsistências
    -> decidir status -> gerar PDF -> arquivar -> gravar histórico -> e-mail
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from fechamento import entrega, registro
from fechamento.config import Config
from fechamento.inconsistencias import Alerta, Severidade, detectar_inconsistencias, ha_grave
from fechamento.integridade import ResultadoIntegridade, verificar_integridade
from fechamento.ledger import Periodo, ler_contas, ler_lancamentos_ate, ler_lancamentos_do_dia
from fechamento.relatorio_pdf import brl, gerar_pdf

log = logging.getLogger(__name__)

CONFORME = "CONFORME"
NAO_CONFORME = "NAO_CONFORME"


@dataclass
class ResultadoFechamento:
    dia: date
    status: str
    integridade: ResultadoIntegridade
    alertas: list[Alerta]
    pdf: Path
    email_enviado: bool

    @property
    def conforme(self) -> bool:
        return self.status == CONFORME


def decidir_status(res: ResultadoIntegridade, alertas: list[Alerta]) -> str:
    """NÃO CONFORME se qualquer verificação de integridade falhou ou houve alerta GRAVE."""
    return CONFORME if res.integra and not ha_grave(alertas) else NAO_CONFORME


def resumo_texto(res: ResultadoIntegridade, alertas: list[Alerta]) -> str:
    graves = [a for a in alertas if a.severidade == Severidade.GRAVE]
    linhas = [
        f"Transações: {res.qtd_transacoes_dia} | Lançamentos: {res.qtd_lancamentos_dia}",
        f"Créditos: {brl(res.total_creditos_dia)} | Débitos: {brl(res.total_debitos_dia)}",
        f"Alertas: {len(graves)} grave(s), {len(alertas) - len(graves)} de atenção",
    ]
    linhas += [f"  - [{a.severidade.value}] {a.codigo}: {a.conta}" for a in alertas]
    return "\n".join(linhas)


def fechar_dia(config: Config, ledger: Engine, robo: Engine, dia: date, *, enviar: bool = True,
               agora: datetime | None = None) -> ResultadoFechamento:
    agora = agora or datetime.now(ZoneInfo(config.fuso))
    periodo = Periodo.do_dia(dia, config.fuso)
    log.info("fechamento_iniciado", extra={"dia": dia.isoformat()})

    # Etapa 0: leitura (somente SELECT na Ledger)
    contas = ler_contas(ledger, periodo.fim_utc)
    df_dia = ler_lancamentos_do_dia(ledger, periodo)
    df_acumulado = ler_lancamentos_ate(ledger, periodo.fim_utc)

    # Etapa 1: saldos e integridade (anterior = fechamento gravado de D-1, se existir)
    registro.preparar(robo)
    anteriores = registro.saldos_do_dia(robo, dia - timedelta(days=1))
    res = verificar_integridade(contas, df_dia, df_acumulado, anteriores)

    # Etapa 2: inconsistências
    alertas = detectar_inconsistencias(res, df_dia, df_acumulado, periodo.inicio_utc,
                                       config.limite_valor_atipico, config.fuso)
    status = decidir_status(res, alertas)

    # Etapas 3 e 4: PDF arquivado por data
    pdf = gerar_pdf(entrega.caminho_arquivo(config.pasta_arquivo, dia), dia, status, res, alertas, agora)
    log.info("pdf_arquivado", extra={"arquivo": str(pdf)})

    email_ok = entrega.enviar_email(config, dia, status, resumo_texto(res, alertas), pdf) if enviar else False

    # Etapa 5: histórico e marcação de conformidade
    graves = sum(a.severidade == Severidade.GRAVE for a in alertas)
    saldos = dict(zip(res.saldos["conta_id"], res.saldos["saldo_final"])) if not res.saldos.empty else {}
    registro.gravar(robo, dia, {
        "status": status, "qtd_transacoes": res.qtd_transacoes_dia,
        "qtd_lancamentos": res.qtd_lancamentos_dia, "total_creditos": res.total_creditos_dia,
        "total_debitos": res.total_debitos_dia, "alertas_graves": graves,
        "alertas_atencao": len(alertas) - graves, "arquivo_pdf": str(pdf),
        "email_enviado": "sim" if email_ok else "nao",
    }, saldos, agora)

    nivel = logging.INFO if status == CONFORME else logging.ERROR
    log.log(nivel, "fechamento_concluido", extra={
        "dia": dia.isoformat(), "status": status, "transacoes": res.qtd_transacoes_dia,
        "lancamentos": res.qtd_lancamentos_dia, "alertas_graves": graves,
        "alertas_atencao": len(alertas) - graves, "codigos": sorted({a.codigo for a in alertas}),
        "email_enviado": email_ok})
    return ResultadoFechamento(dia, status, res, alertas, pdf, email_ok)
