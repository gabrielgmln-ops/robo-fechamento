# robo-fechamento/src/fechamento/__main__.py
"""Linha de comando do robô.

  python -m fechamento semear [--dia AAAA-MM-DD] [--sem-anomalias]   # Ledger sintética
  python -m fechamento ler    [--dia AAAA-MM-DD]                     # Etapa 0: só lê e resume
  python -m fechamento fechar [--dia AAAA-MM-DD] [--sem-email]       # fechamento completo
  python -m fechamento historico                                     # últimos fechamentos
  python -m fechamento agendar                                       # roda no horário do cron

Código de saída de `fechar`: 0 = CONFORME, 2 = NÃO CONFORME (útil para CI/monitoração).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fechamento import registro
from fechamento.agendador import agendar
from fechamento.config import carregar_config
from fechamento.integridade import somar
from fechamento.ledger import Periodo, criar_engine, ler_lancamentos_do_dia
from fechamento.logs import configurar_logs
from fechamento.pipeline import fechar_dia
from fechamento.relatorio_pdf import brl, rotulo
from fechamento.sintetico import semear


def _dia(texto: str | None, fuso: str) -> date:
    return date.fromisoformat(texto) if texto else datetime.now(ZoneInfo(fuso)).date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fechamento", description="Robô de Fechamento Diário da Ledger")
    sub = p.add_subparsers(dest="comando", required=True)
    s = sub.add_parser("semear", help="cria uma Ledger sintética com 3 dias de movimento")
    s.add_argument("--dia", help="último dia gerado (padrão: ontem)")
    s.add_argument("--sem-anomalias", action="store_true")
    for nome in ("ler", "fechar"):
        sp = sub.add_parser(nome)
        sp.add_argument("--dia", help="dia contábil AAAA-MM-DD (padrão: hoje)")
    sub.choices["fechar"].add_argument("--sem-email", action="store_true")
    sub.add_parser("historico")
    sub.add_parser("agendar")
    args = p.parse_args(argv)

    config = carregar_config()
    configurar_logs(config.pasta_logs)

    if args.comando == "semear":
        dia = date.fromisoformat(args.dia) if args.dia else datetime.now(ZoneInfo(config.fuso)).date() - timedelta(days=1)
        info = semear(criar_engine(config.ledger_database_url), dia, anomalias=not args.sem_anomalias,
                      fuso=config.fuso)
        print(f"Ledger sintética criada: {info}")
        return 0

    if args.comando == "ler":
        periodo = Periodo.do_dia(_dia(args.dia, config.fuso), config.fuso)
        df = ler_lancamentos_do_dia(criar_engine(config.ledger_database_url), periodo)
        print(f"Dia {periodo.dia:%d/%m/%Y}: {len(df)} lançamentos, "
              f"{df['transacao_id'].nunique() if not df.empty else 0} transações")
        if not df.empty:
            cred = somar(df.loc[df['tipo'] == 'CREDITO', 'valor'])
            deb = somar(df.loc[df['tipo'] == 'DEBITO', 'valor'])
            print(f"Créditos {brl(cred)} | Débitos {brl(deb)}")
            print(df[["id", "titular", "tipo", "valor", "criado_em"]].head(10).to_string(index=False))
        return 0

    if args.comando == "fechar":
        r = fechar_dia(config, criar_engine(config.ledger_database_url), criar_engine(config.robo_database_url),
                       _dia(args.dia, config.fuso), enviar=not args.sem_email)
        print(f"\nFechamento {r.dia:%d/%m/%Y}: {rotulo(r.status)}")
        for v in r.integridade.verificacoes:
            print(f"  [{'OK' if v.ok else 'FALHOU'}] {v.nome} - {v.detalhe}")
        for a in r.alertas:
            print(f"  ({a.severidade.value}) {a.codigo} | {a.conta} | {brl(a.valor)}")
        print(f"PDF: {r.pdf}\nE-mail enviado: {'sim' if r.email_enviado else 'não'}")
        return 0 if r.conforme else 2

    if args.comando == "historico":
        robo = criar_engine(config.robo_database_url)
        registro.preparar(robo)
        for h in registro.historico(robo):
            print(f"{h['dia']}  {h['status']:<13} transações={h['qtd_transacoes']:<4} "
                  f"graves={h['alertas_graves']} atenção={h['alertas_atencao']}  {h['arquivo_pdf']}")
        return 0

    agendar(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
