# robo-fechamento/src/fechamento/relatorio_pdf.py
"""Relatório de fechamento em PDF com ReportLab (Etapa 3).

ReportLab foi escolhido no lugar do WeasyPrint porque é Python puro: o
WeasyPrint precisa das bibliotecas GTK/Pango, chatas de instalar no Windows.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from fechamento.inconsistencias import Alerta, Severidade
from fechamento.integridade import ResultadoIntegridade

VERDE = colors.HexColor("#1B7F3B")
VERMELHO = colors.HexColor("#B42318")
AMARELO = colors.HexColor("#B54708")
CINZA = colors.HexColor("#EAECF0")


def rotulo(status: str) -> str:
    """Texto legível do status: NAO_CONFORME -> NÃO CONFORME."""
    return {"NAO_CONFORME": "NÃO CONFORME"}.get(status, status)


def brl(valor: Decimal | None) -> str:
    """Formata Decimal no padrão brasileiro: 1.234,56 (sem passar por float)."""
    if valor is None:
        return "-"
    sinal = "-" if valor < 0 else ""
    inteiro, centavos = f"{abs(valor):.2f}".split(".")
    inteiro = f"{int(inteiro):,}".replace(",", ".")
    return f"{sinal}R$ {inteiro},{centavos}"


def _tabela(dados: list[list], larguras: list[float], cabecalho=CINZA) -> Table:
    t = Table(dados, colWidths=larguras, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), cabecalho),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
    ]))
    return t


def gerar_pdf(destino: Path, dia, status: str, res: ResultadoIntegridade, alertas: list[Alerta],
              gerado_em: datetime) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    estilos = getSampleStyleSheet()
    pequeno = ParagraphStyle("pequeno", parent=estilos["BodyText"], fontSize=8, leading=10)
    conforme = status == "CONFORME"

    doc = SimpleDocTemplate(str(destino), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"Fechamento diário {dia:%d/%m/%Y}", author="Robô de Fechamento")
    h: list = [
        Paragraph(f"Relatório de Fechamento Diário — {dia:%d/%m/%Y}", estilos["Title"]),
        Paragraph(f"Gerado em {gerado_em:%d/%m/%Y %H:%M:%S} · dados sintéticos", estilos["Italic"]),
        Spacer(1, 4 * mm),
    ]

    selo = Table([[f"STATUS: {rotulo(status)}"]], colWidths=[180 * mm])
    selo.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), VERDE if conforme else VERMELHO),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 14),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    graves = sum(a.severidade == Severidade.GRAVE for a in alertas)
    h += [selo, Spacer(1, 4 * mm), Paragraph("Totais do dia", estilos["Heading2"])]
    h.append(_tabela([
        ["Indicador", "Valor"],
        ["Transações", str(res.qtd_transacoes_dia)],
        ["Lançamentos", str(res.qtd_lancamentos_dia)],
        ["Total de créditos", brl(res.total_creditos_dia)],
        ["Total de débitos", brl(res.total_debitos_dia)],
        ["Soma do dia (créditos - débitos)", brl(res.soma_dia)],
        ["Soma global da Ledger", brl(res.soma_global)],
        ["Alertas graves / atenção", f"{graves} / {len(alertas) - graves}"],
    ], [90 * mm, 90 * mm]))

    h += [Spacer(1, 4 * mm), Paragraph("Verificações de integridade", estilos["Heading2"])]
    linhas: list[list] = [["Verificação", "Resultado", "Detalhe"]]
    for v in res.verificacoes:
        linhas.append([Paragraph(v.nome, pequeno), "OK" if v.ok else "FALHOU", Paragraph(v.detalhe, pequeno)])
    t = _tabela(linhas, [65 * mm, 20 * mm, 95 * mm])
    for i, v in enumerate(res.verificacoes, start=1):
        t.setStyle(TableStyle([("TEXTCOLOR", (1, i), (1, i), VERDE if v.ok else VERMELHO),
                               ("FONTNAME", (1, i), (1, i), "Helvetica-Bold")]))
    h.append(t)

    h += [Spacer(1, 4 * mm), Paragraph(f"Alertas ({len(alertas)})", estilos["Heading2"])]
    if alertas:
        linhas = [["Sev.", "Código", "Conta", "Valor", "Descrição"]]
        for a in alertas:
            linhas.append([a.severidade.value, Paragraph(a.codigo, pequeno), Paragraph(a.conta or "-", pequeno),
                           brl(a.valor), Paragraph(a.descricao + (f" Transação {a.transacao_id[:8]}…"
                                                                   if a.transacao_id else ""), pequeno)])
        t = _tabela(linhas, [19 * mm, 38 * mm, 31 * mm, 24 * mm, 68 * mm])
        for i, a in enumerate(alertas, start=1):
            t.setStyle(TableStyle([("TEXTCOLOR", (0, i), (0, i),
                                    VERMELHO if a.severidade == Severidade.GRAVE else AMARELO),
                                   ("FONTNAME", (0, i), (0, i), "Helvetica-Bold")]))
        h.append(t)
    else:
        h.append(Paragraph("Nenhuma inconsistência encontrada.", estilos["BodyText"]))

    h += [Spacer(1, 4 * mm), Paragraph("Saldos por conta", estilos["Heading2"])]
    linhas = [["Conta", "Tipo", "Saldo anterior", "Créditos", "Débitos", "Saldo final", "Confere"]]
    for s in res.saldos.itertuples(index=False):
        linhas.append([Paragraph(s.titular, pequeno), s.tipo, brl(s.saldo_anterior), brl(s.creditos),
                       brl(s.debitos), brl(s.saldo_final), "sim" if s.confere else "NÃO"])
    t = _tabela(linhas, [42 * mm, 18 * mm, 26 * mm, 24 * mm, 24 * mm, 28 * mm, 18 * mm])
    t.setStyle(TableStyle([("ALIGN", (2, 1), (5, -1), "RIGHT")]))
    h.append(t)

    doc.build(h)
    return destino
