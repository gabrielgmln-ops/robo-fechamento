# robo-fechamento/src/fechamento/config.py
"""Configuração lida de variáveis de ambiente (com .env opcional).

Segredos (URL do banco com senha, senha do SMTP) nunca ficam no código.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv


def _lista(valor: str) -> list[str]:
    return [v.strip() for v in valor.split(",") if v.strip()]


@dataclass(frozen=True)
class Config:
    # Banco da Ledger API: o robô SÓ LÊ dele (use um usuário read-only em produção).
    ledger_database_url: str = field(default="sqlite:///dados/ledger_sintetica.db", repr=False)
    # Banco próprio do robô: histórico de fechamentos e saldos de cada dia.
    robo_database_url: str = field(default="sqlite:///dados/robo.db", repr=False)
    fuso: str = "America/Sao_Paulo"
    pasta_arquivo: Path = Path("dados/arquivo")
    pasta_logs: Path = Path("logs")
    # Transação acima deste valor vira alerta de ATENÇÃO (não torna não conforme).
    limite_valor_atipico: Decimal = Decimal("50000.00")
    smtp_host: str = "smtp.gmail.com"
    smtp_porta: int = 587
    smtp_usuario: str = ""
    smtp_senha: str = field(default="", repr=False)  # nunca aparece em logs/repr
    email_remetente: str = ""
    email_destinatarios: list[str] = field(default_factory=list)
    # Padrão: 23h30 todos os dias (o dia contábil fecha mesmo em fim de semana).
    cron_fechamento: str = "30 23 * * *"

    @property
    def email_configurado(self) -> bool:
        return bool(self.smtp_usuario and self.smtp_senha and self.email_destinatarios)


def carregar_config() -> Config:
    load_dotenv()  # não sobrescreve variáveis que já existem no ambiente
    e = os.environ.get
    return Config(
        ledger_database_url=e("LEDGER_DATABASE_URL", "sqlite:///dados/ledger_sintetica.db"),
        robo_database_url=e("ROBO_DATABASE_URL", "sqlite:///dados/robo.db"),
        fuso=e("FUSO", "America/Sao_Paulo"),
        pasta_arquivo=Path(e("PASTA_ARQUIVO", "dados/arquivo")),
        pasta_logs=Path(e("PASTA_LOGS", "logs")),
        limite_valor_atipico=Decimal(e("LIMITE_VALOR_ATIPICO", "50000.00")),
        smtp_host=e("SMTP_HOST", "smtp.gmail.com"),
        smtp_porta=int(e("SMTP_PORTA", "587")),
        smtp_usuario=e("SMTP_USUARIO", ""),
        smtp_senha=e("SMTP_SENHA", ""),
        email_remetente=e("EMAIL_REMETENTE", "") or e("SMTP_USUARIO", ""),
        email_destinatarios=_lista(e("EMAIL_DESTINATARIOS", "")),
        cron_fechamento=e("CRON_FECHAMENTO", "30 23 * * *"),
    )
