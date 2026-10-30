# robo-fechamento/src/fechamento/sintetico.py
"""Gera uma Ledger SINTÉTICA (mesmo schema da Ledger API) para testar o robô.

Nenhum dado real: titulares fictícios, valores aleatórios com semente fixa.
Com `anomalias=True`, o último dia recebe defeitos plantados de propósito,
para provar que o robô os encontra:
  - transação órfã (só a perna de crédito, sem contrapartida);
  - lançamento apontando para transação inexistente;
  - cliente com saldo negativo (transferência maior que o saldo);
  - lançamentos com valor diferente do valor da transação;
  - depósito de valor atípico (só alerta de atenção).
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, insert

from fechamento.ledger import Periodo, conta, lancamento, metadata, transacao

TESOURARIA = "00000000-0000-0000-0000-000000000001"  # mesmo id da migração V3
TITULARES = ["Ana Sintética", "Bruno Fictício", "Carla Exemplo", "Diego Teste",
             "Elisa Modelo", "Fábio Simulado"]


class _Gerador:
    def __init__(self, engine: Engine, semente: int):
        self.engine = engine
        self.rnd = random.Random(semente)
        self.uuid_rnd = random.Random(semente + 1)
        self.saldos: dict[str, Decimal] = {}

    def _uuid(self) -> str:
        return str(uuid.UUID(int=self.uuid_rnd.getrandbits(128), version=4))

    def _valor(self, minimo: int, maximo: int) -> Decimal:
        return Decimal(self.rnd.randint(minimo * 100, maximo * 100)) / 100

    def criar_contas(self, quando: datetime) -> list[str]:
        linhas = [{"id": TESOURARIA, "titular": "Tesouraria (conta interna)", "tipo": "INTERNA", "criada_em": quando}]
        clientes = []
        for nome in TITULARES:
            cid = self._uuid()
            clientes.append(cid)
            linhas.append({"id": cid, "titular": nome, "tipo": "CLIENTE", "criada_em": quando})
        with self.engine.begin() as cx:
            cx.execute(insert(conta), linhas)
        self.saldos = {c["id"]: Decimal("0.00") for c in linhas}
        return clientes

    def transacionar(self, tipo: str, origem: str, destino: str, valor: Decimal, quando: datetime,
                     *, valor_registrado: Decimal | None = None, pernas: str = "ambas",
                     transacao_existe: bool = True) -> str:
        """Grava a transação e seus lançamentos (débito na origem, crédito no destino)."""
        tid = self._uuid()
        with self.engine.begin() as cx:
            if transacao_existe:
                cx.execute(insert(transacao).values(
                    id=tid, tipo=tipo, conta_origem_id=origem, conta_destino_id=destino,
                    valor=valor_registrado if valor_registrado is not None else valor,
                    descricao=f"{tipo.lower()} sintético", criada_em=quando))
            if pernas in ("ambas", "debito"):
                cx.execute(insert(lancamento).values(transacao_id=tid, conta_id=origem, tipo="DEBITO",
                                                     valor=valor, criado_em=quando))
                self.saldos[origem] -= valor
            if pernas in ("ambas", "credito"):
                cx.execute(insert(lancamento).values(transacao_id=tid, conta_id=destino, tipo="CREDITO",
                                                     valor=valor, criado_em=quando))
                self.saldos[destino] += valor
        return tid

    def dia_normal(self, inicio: datetime, clientes: list[str], quantidade: int) -> None:
        # Horários espalhados entre 8h e 20h locais (inicio já é 00h local em UTC).
        horarios = sorted(self.rnd.randint(8 * 3600, 20 * 3600) for _ in range(quantidade))
        for seg in horarios:
            quando = inicio + timedelta(seconds=seg)
            if self.rnd.random() < 0.35:
                self.transacionar("DEPOSITO", TESOURARIA, self.rnd.choice(clientes), self._valor(50, 3000), quando)
            else:
                origem, destino = self.rnd.sample(clientes, 2)
                if self.saldos[origem] < Decimal("10.00"):
                    continue  # a Ledger real recusaria; aqui só pulamos
                teto = int(min(self.saldos[origem], Decimal("2000")))
                self.transacionar("TRANSFERENCIA", origem, destino, self._valor(1, max(teto, 1)), quando)

    def plantar_anomalias(self, inicio: datetime, clientes: list[str]) -> None:
        h = lambda horas: inicio + timedelta(hours=horas)  # noqa: E731
        # 1) Órfã: só o crédito foi gravado (o débito na Tesouraria "sumiu").
        self.transacionar("DEPOSITO", TESOURARIA, clientes[0], Decimal("150.00"), h(21), pernas="credito")
        # 2) Lançamentos apontando para transação que não existe (par balanceado).
        self.transacionar("TRANSFERENCIA", clientes[1], clientes[2], Decimal("75.50"), h(21.2),
                          transacao_existe=False)
        # 3) Saldo negativo: cliente transfere mais do que tem.
        alvo = clientes[3]
        excesso = self.saldos[alvo] + Decimal("320.00")
        self.transacionar("TRANSFERENCIA", alvo, clientes[4], excesso, h(21.5))
        # 4) Valor divergente: lançamentos de 100,00 numa transação registrada como 130,00.
        self.transacionar("TRANSFERENCIA", clientes[4], clientes[5], Decimal("100.00"), h(22),
                          valor_registrado=Decimal("130.00"))
        # 5) Valor atípico (acima do limite padrão de 50.000,00).
        self.transacionar("DEPOSITO", TESOURARIA, clientes[5], Decimal("82000.00"), h(22.5))


def semear(engine: Engine, ultimo_dia: date, dias: int = 3, *, anomalias: bool = True,
           semente: int = 42, fuso: str = "America/Sao_Paulo", por_dia: int = 25) -> dict:
    """Recria o schema e gera `dias` dias de movimento terminando em `ultimo_dia`."""
    metadata.drop_all(engine)
    metadata.create_all(engine)
    g = _Gerador(engine, semente)
    primeiro = Periodo.do_dia(ultimo_dia - timedelta(days=dias - 1), fuso)
    clientes = g.criar_contas(primeiro.inicio_utc)
    for i in range(dias):
        periodo = Periodo.do_dia(ultimo_dia - timedelta(days=dias - 1 - i), fuso)
        g.dia_normal(periodo.inicio_utc, clientes, por_dia)
        if anomalias and periodo.dia == ultimo_dia:
            g.plantar_anomalias(periodo.inicio_utc, clientes)
    return {"contas": len(clientes) + 1, "dias": dias, "anomalias": anomalias, "ultimo_dia": ultimo_dia.isoformat()}
