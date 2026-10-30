# robo-fechamento/tests/test_pdf_entrega.py
"""Etapas 3 e 4: PDF, arquivamento por data e e-mail (SMTP simulado)."""

import smtplib
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fechamento import entrega
from fechamento.integridade import verificar_integridade
from fechamento.ledger import Periodo, ler_contas, ler_lancamentos_ate, ler_lancamentos_do_dia
from fechamento.relatorio_pdf import brl, gerar_pdf, rotulo
from tests.conftest import ULTIMO_DIA


def test_brl_formata_padrao_brasileiro():
    assert brl(Decimal("1234567.8")) == "R$ 1.234.567,80"
    assert brl(Decimal("-0.05")) == "-R$ 0,05"
    assert brl(None) == "-"
    assert rotulo("NAO_CONFORME") == "NÃO CONFORME" and rotulo("CONFORME") == "CONFORME"


def test_caminho_arquivo_por_data(tmp_path):
    esperado = tmp_path / "2026" / "03" / "fechamento-2026-03-07.pdf"
    assert entrega.caminho_arquivo(tmp_path, date(2026, 3, 7)) == esperado


def test_gera_pdf_valido(ledger_suja, tmp_path):
    p = Periodo.do_dia(ULTIMO_DIA)
    res = verificar_integridade(ler_contas(ledger_suja, p.fim_utc), ler_lancamentos_do_dia(ledger_suja, p),
                                ler_lancamentos_ate(ledger_suja, p.fim_utc))
    pdf = gerar_pdf(tmp_path / "x" / "f.pdf", ULTIMO_DIA, "NAO_CONFORME", res, [], datetime(2026, 10, 30))
    assert pdf.read_bytes().startswith(b"%PDF") and pdf.stat().st_size > 2000


def _config_email(config):
    return replace(config, smtp_usuario="robo@exemplo.com", smtp_senha="senha-de-teste",
                   email_remetente="robo@exemplo.com", email_destinatarios=["backoffice@exemplo.com"])


def _pdf(tmp_path):
    pdf = tmp_path / "f.pdf"
    pdf.write_bytes(b"%PDF-1.4 teste")
    return pdf


def test_mensagem_tem_pdf_anexo(config, tmp_path):
    msg = entrega.montar_mensagem(_config_email(config), ULTIMO_DIA, "NAO_CONFORME", "resumo", _pdf(tmp_path))
    assert "NÃO CONFORME" in msg["Subject"]
    anexo = next(msg.iter_attachments())
    assert anexo.get_content_type() == "application/pdf" and anexo.get_filename() == "f.pdf"


def test_email_nao_configurado_pula(config, tmp_path):
    assert entrega.enviar_email(config, ULTIMO_DIA, "CONFORME", "r", tmp_path / "f.pdf") is False


def test_email_enviado_com_starttls(config, tmp_path):
    with patch("fechamento.entrega.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        assert entrega.enviar_email(_config_email(config), ULTIMO_DIA, "CONFORME", "r", _pdf(tmp_path)) is True
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("robo@exemplo.com", "senha-de-teste")
    smtp.send_message.assert_called_once()


def test_falha_de_smtp_nao_derruba(config, tmp_path):
    with patch("fechamento.entrega.smtplib.SMTP", side_effect=smtplib.SMTPConnectError(421, "fora")):
        assert entrega.enviar_email(_config_email(config), ULTIMO_DIA, "CONFORME", "r", _pdf(tmp_path)) is False


def test_senha_nao_aparece_no_repr(config):
    assert "senha-de-teste" not in repr(_config_email(config))
