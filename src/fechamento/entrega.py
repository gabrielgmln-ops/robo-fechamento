# robo-fechamento/src/fechamento/entrega.py
"""Arquivamento do PDF por data e envio por e-mail (Etapa 4).

Arquivo: <pasta_arquivo>/AAAA/MM/fechamento-AAAA-MM-DD.pdf
E-mail: SMTP com STARTTLS; credenciais só por variável de ambiente.
Se o e-mail não estiver configurado, o envio é pulado com aviso (não derruba o fechamento).
"""

from __future__ import annotations

import logging
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from fechamento.config import Config
from fechamento.relatorio_pdf import rotulo

log = logging.getLogger(__name__)


def caminho_arquivo(pasta_arquivo: Path, dia: date) -> Path:
    return Path(pasta_arquivo) / f"{dia:%Y}" / f"{dia:%m}" / f"fechamento-{dia:%Y-%m-%d}.pdf"


def montar_mensagem(config: Config, dia: date, status: str, resumo: str, pdf: Path) -> EmailMessage:
    msg = EmailMessage()
    marcador = "OK" if status == "CONFORME" else "ATENÇÃO"
    msg["Subject"] = f"[Fechamento {dia:%d/%m/%Y}] {rotulo(status)} ({marcador})"
    msg["From"] = config.email_remetente
    msg["To"] = ", ".join(config.email_destinatarios)
    msg.set_content(
        f"Fechamento diário de {dia:%d/%m/%Y}: {rotulo(status)}.\n\n{resumo}\n\n"
        "O relatório completo segue em anexo (PDF).\n-- Robô de Fechamento (dados sintéticos)")
    msg.add_attachment(Path(pdf).read_bytes(), maintype="application", subtype="pdf", filename=Path(pdf).name)
    return msg


def enviar_email(config: Config, dia: date, status: str, resumo: str, pdf: Path) -> bool:
    """Envia e devolve True; devolve False (e registra) se não configurado ou se falhar."""
    if not config.email_configurado:
        log.warning("email_nao_configurado",
                    extra={"dica": "defina SMTP_USUARIO, SMTP_SENHA e EMAIL_DESTINATARIOS"})
        return False
    msg = montar_mensagem(config, dia, status, resumo, pdf)
    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_porta, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(config.smtp_usuario, config.smtp_senha)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as erro:
        log.error("email_falhou", extra={"erro": str(erro)})
        return False
    log.info("email_enviado", extra={"destinatarios": len(config.email_destinatarios)})
    return True
