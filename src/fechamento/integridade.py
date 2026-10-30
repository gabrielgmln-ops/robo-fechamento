# robo-fechamento/src/fechamento/integridade.py
"""Recálculo de saldos e verificação de integridade contábil (Etapa 1).

Três verificações, todas em Decimal exato:
  1. Partidas dobradas no banco inteiro: soma com sinal de TODOS os lançamentos = 0.
  2. Partidas dobradas no dia: soma com sinal dos lançamentos do dia = 0.
  3. Continuidade: para cada conta, saldo do fechamento anterior + movimento do dia
     = saldo recalculado agora. Se falhar, algum lançamento antigo foi alterado ou
     apagado (a Ledger é append-only, então isso nunca deveria acontecer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

ZERO = Decimal("0.00")


def somar(valores) -> Decimal:
    """Soma Decimal sem passar por float (pandas somaria object de forma imprevisível)."""
    return sum(valores, ZERO)


@dataclass
class Verificacao:
    nome: str
    ok: bool
    detalhe: str


@dataclass
class ResultadoIntegridade:
    saldos: pd.DataFrame  # uma linha por conta
    soma_global: Decimal
    soma_dia: Decimal
    total_creditos_dia: Decimal
    total_debitos_dia: Decimal
    qtd_lancamentos_dia: int
    qtd_transacoes_dia: int
    verificacoes: list[Verificacao] = field(default_factory=list)

    @property
    def integra(self) -> bool:
        return all(v.ok for v in self.verificacoes)


def _por_conta(df: pd.DataFrame, coluna: str = "valor_sinal") -> dict[str, Decimal]:
    if df.empty:
        return {}
    return {cid: somar(grupo[coluna]) for cid, grupo in df.groupby("conta_id")}


def calcular_saldos(contas: pd.DataFrame, df_dia: pd.DataFrame, df_acumulado: pd.DataFrame,
                    saldos_anteriores: dict[str, Decimal] | None) -> pd.DataFrame:
    """Monta a tabela de saldos por conta.

    `saldos_anteriores` vem do fechamento anterior gravado pelo robô. Se não houver
    (primeira execução), usa-se o acumulado da Ledger antes do dia.
    """
    final = _por_conta(df_acumulado)
    movimento = _por_conta(df_dia)
    creditos = _por_conta(df_dia[df_dia["tipo"] == "CREDITO"], "valor") if not df_dia.empty else {}
    debitos = _por_conta(df_dia[df_dia["tipo"] == "DEBITO"], "valor") if not df_dia.empty else {}

    linhas = []
    for c in contas.itertuples(index=False):
        saldo_final = final.get(c.id, ZERO)
        mov = movimento.get(c.id, ZERO)
        if saldos_anteriores is not None:
            anterior = saldos_anteriores.get(c.id, ZERO)
            origem = "fechamento anterior"
        else:
            anterior = saldo_final - mov
            origem = "ledger"
        linhas.append({
            "conta_id": c.id, "titular": c.titular, "tipo": c.tipo,
            "saldo_anterior": anterior, "creditos": creditos.get(c.id, ZERO),
            "debitos": debitos.get(c.id, ZERO), "movimento": mov,
            "saldo_final": saldo_final, "esperado": anterior + mov,
            "origem_anterior": origem,
        })
    saldos = pd.DataFrame(linhas)
    if not saldos.empty:
        saldos["confere"] = saldos["saldo_final"] == saldos["esperado"]
    return saldos


def verificar_integridade(contas: pd.DataFrame, df_dia: pd.DataFrame, df_acumulado: pd.DataFrame,
                          saldos_anteriores: dict[str, Decimal] | None = None) -> ResultadoIntegridade:
    saldos = calcular_saldos(contas, df_dia, df_acumulado, saldos_anteriores)
    soma_global = somar(df_acumulado["valor_sinal"]) if not df_acumulado.empty else ZERO
    soma_dia = somar(df_dia["valor_sinal"]) if not df_dia.empty else ZERO
    creditos = somar(df_dia.loc[df_dia["tipo"] == "CREDITO", "valor"]) if not df_dia.empty else ZERO
    debitos = somar(df_dia.loc[df_dia["tipo"] == "DEBITO", "valor"]) if not df_dia.empty else ZERO

    verificacoes = [
        Verificacao("Soma global dos lançamentos = 0", soma_global == ZERO,
                    f"soma com sinal de todos os lançamentos = {soma_global}"),
        Verificacao("Soma dos lançamentos do dia = 0", soma_dia == ZERO,
                    f"créditos {creditos} - débitos {debitos} = {soma_dia}"),
    ]
    divergentes = saldos[~saldos["confere"]] if not saldos.empty else saldos
    verificacoes.append(Verificacao(
        "Saldo anterior + movimento = saldo recalculado", divergentes.empty,
        "todas as contas conferem" if divergentes.empty
        else f"{len(divergentes)} conta(s) divergente(s): " + ", ".join(divergentes["titular"])))

    return ResultadoIntegridade(
        saldos=saldos, soma_global=soma_global, soma_dia=soma_dia,
        total_creditos_dia=creditos, total_debitos_dia=debitos,
        qtd_lancamentos_dia=len(df_dia),
        qtd_transacoes_dia=df_dia["transacao_id"].nunique() if not df_dia.empty else 0,
        verificacoes=verificacoes,
    )
