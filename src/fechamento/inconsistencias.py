# robo-fechamento/src/fechamento/inconsistencias.py
"""Detecção de inconsistências do dia (Etapa 2).

Cada achado vira um Alerta com severidade:
  GRAVE    -> torna o fechamento NÃO CONFORME;
  ATENCAO  -> vai para o relatório, mas não reprova o dia.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

import pandas as pd

from fechamento.integridade import ZERO, ResultadoIntegridade, somar


class Severidade(str, Enum):
    GRAVE = "GRAVE"
    ATENCAO = "ATENCAO"


@dataclass(frozen=True)
class Alerta:
    severidade: Severidade
    codigo: str
    descricao: str
    conta: str = ""
    transacao_id: str = ""
    valor: Decimal | None = None


def _alertas_integridade(res: ResultadoIntegridade) -> list[Alerta]:
    alertas = []
    if res.soma_global != ZERO:
        alertas.append(Alerta(Severidade.GRAVE, "SOMA_GLOBAL_DIFERENTE_DE_ZERO",
                              "A soma de todos os lançamentos da Ledger não fecha em zero.",
                              valor=res.soma_global))
    for linha in res.saldos.itertuples(index=False):
        if not linha.confere:
            alertas.append(Alerta(Severidade.GRAVE, "SALDO_DIVERGENTE",
                                  f"Saldo recalculado {linha.saldo_final} difere do esperado {linha.esperado} "
                                  "(fechamento anterior + movimento do dia).",
                                  conta=linha.titular, valor=linha.saldo_final - linha.esperado))
    return alertas


def _transacoes_orfas(df_dia: pd.DataFrame) -> list[Alerta]:
    """Transação cujas pernas não se anulam: falta contrapartida (ou sobra)."""
    alertas = []
    for tid, grupo in df_dia.groupby("transacao_id"):
        soma = somar(grupo["valor_sinal"])
        tipos = set(grupo["tipo"])
        if soma != ZERO or tipos != {"DEBITO", "CREDITO"}:
            faltando = {"DEBITO", "CREDITO"} - tipos
            motivo = (f"sem a perna de {', '.join(sorted(faltando)).lower()}" if faltando
                      else f"pernas não se anulam (soma {soma})")
            alertas.append(Alerta(Severidade.GRAVE, "LANCAMENTO_ORFAO",
                                  f"Lançamento sem contrapartida: {motivo}.",
                                  conta=", ".join(sorted(set(grupo["titular"]))),
                                  transacao_id=str(tid), valor=soma))
    return alertas


def _sem_transacao(df_dia: pd.DataFrame) -> list[Alerta]:
    """Lançamento cuja transação não existe na tabela `transacao`."""
    orfaos = df_dia[df_dia["valor_transacao"].isna()]
    return [Alerta(Severidade.GRAVE, "TRANSACAO_INEXISTENTE",
                   f"{len(g)} lançamento(s) apontam para transação que não existe.",
                   conta=", ".join(sorted(set(g["titular"]))), transacao_id=str(tid),
                   valor=max(g["valor"]))
            for tid, g in orfaos.groupby("transacao_id")]


def _valor_divergente(df_dia: pd.DataFrame) -> list[Alerta]:
    """Lançamento com valor diferente do valor registrado na transação."""
    com_tx = df_dia[df_dia["valor_transacao"].notna()]
    diverge = com_tx[com_tx["valor"] != com_tx["valor_transacao"]]
    return [Alerta(Severidade.GRAVE, "VALOR_DIVERGENTE_DA_TRANSACAO",
                   f"Lançamentos de {g['valor'].iloc[0]} numa transação de {g['valor_transacao'].iloc[0]}.",
                   conta=", ".join(sorted(set(g["titular"]))), transacao_id=str(tid),
                   valor=g["valor_transacao"].iloc[0])
            for tid, g in diverge.groupby("transacao_id")]


def _saldo_negativo(df_acumulado: pd.DataFrame, inicio_dia, fuso: str) -> list[Alerta]:
    """Conta de CLIENTE que ficou negativa em algum momento do dia.

    Percorre o saldo corrente lançamento a lançamento (ordem de id), em Decimal.
    A conta INTERNA (Tesouraria) pode ser negativa: é a contrapartida dos depósitos.
    """
    alertas = []
    clientes = df_acumulado[df_acumulado["tipo_conta"] == "CLIENTE"]
    for _, grupo in clientes.groupby("conta_id"):
        saldo, menor, quando = ZERO, None, None
        for valor, criado in zip(grupo["valor_sinal"], grupo["criado_em"]):
            saldo += valor
            if criado >= inicio_dia and (menor is None or saldo < menor):
                menor, quando = saldo, criado
        if menor is not None and menor < ZERO:
            alertas.append(Alerta(Severidade.GRAVE, "SALDO_NEGATIVO_INDEVIDO",
                                  f"Conta de cliente ficou negativa ({menor}) em "
                                  f"{quando.astimezone(ZoneInfo(fuso)):%d/%m/%Y %H:%M}; saldo final {saldo}.",
                                  conta=grupo["titular"].iloc[0], valor=menor))
    return alertas


def _valor_atipico(df_dia: pd.DataFrame, limite: Decimal) -> list[Alerta]:
    creditos = df_dia[(df_dia["tipo"] == "CREDITO") & (df_dia["valor"] > limite)]
    return [Alerta(Severidade.ATENCAO, "VALOR_ATIPICO",
                   f"Movimento acima do limite de {limite}.",
                   conta=l.titular, transacao_id=str(l.transacao_id), valor=l.valor)
            for l in creditos.itertuples(index=False)]


def detectar_inconsistencias(res: ResultadoIntegridade, df_dia: pd.DataFrame, df_acumulado: pd.DataFrame,
                             inicio_dia, limite_atipico: Decimal = Decimal("50000.00"),
                             fuso: str = "America/Sao_Paulo") -> list[Alerta]:
    alertas = _alertas_integridade(res)
    if not df_dia.empty:
        alertas += _transacoes_orfas(df_dia)
        alertas += _sem_transacao(df_dia)
        alertas += _valor_divergente(df_dia)
        alertas += _valor_atipico(df_dia, limite_atipico)
    if not df_acumulado.empty:
        alertas += _saldo_negativo(df_acumulado, inicio_dia, fuso)
    # GRAVE primeiro; dentro da severidade, por código.
    return sorted(alertas, key=lambda a: (a.severidade != Severidade.GRAVE, a.codigo))


def ha_grave(alertas: list[Alerta]) -> bool:
    return any(a.severidade == Severidade.GRAVE for a in alertas)
