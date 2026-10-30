# robo-fechamento/src/fechamento/logs.py
"""Logging estruturado: uma linha JSON por evento.

Uso:  log.info("lancamentos_lidos", extra={"quantidade": 42})
A mensagem é um nome de evento curto; os detalhes viram campos do JSON.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Atributos que todo LogRecord já tem; o que não estiver aqui veio do `extra`.
_PADRAO = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class FormatadorJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        evento = {
            "quando": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="seconds"),
            "nivel": record.levelname,
            "modulo": record.name,
            "evento": record.getMessage(),
        }
        evento.update({k: v for k, v in vars(record).items() if k not in _PADRAO})
        if record.exc_info:
            evento["excecao"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_logs(pasta: Path, nivel: int = logging.INFO) -> None:
    """Console + arquivo rotativo (5 x 1 MB) em logs/fechamento.log."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for h in list(raiz.handlers):  # evita duplicar handlers se chamado de novo
        raiz.removeHandler(h)
    formatador = FormatadorJson()
    # Console do Windows costuma vir em cp1252 e estraga os acentos do JSON.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for handler in (
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(pasta / "fechamento.log", maxBytes=1_000_000,
                            backupCount=5, encoding="utf-8"),
    ):
        handler.setFormatter(formatador)
        raiz.addHandler(handler)
    for barulhento in ("apscheduler", "sqlalchemy", "fontTools"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)
