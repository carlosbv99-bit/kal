"""
Logging centralizado: archivo agent.log + consola, formato estructurado.

Este logger es para operación normal (debug, info, warnings de negocio).
NO confundir con audit/audit_log.py, que es el registro inmutable de
decisiones autónomas relevantes (reparaciones, herramientas creadas,
self-modification). Ambos existen porque tienen retención y garantías
distintas: este puede rotar/truncarse, el de auditoría no.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from utils.config import settings  # noqa: F401  (para futura config de nivel por yaml)
from utils.correlation import get_correlation_id

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


class _CorrelationFilter(logging.Filter):
    """
    Inyecta el correlation_id actual (ver utils/correlation.py) en cada
    LogRecord — "-" si ningún pedido lo seteó (arranque del proceso,
    jobs de fondo como el consolidado de memoria, etc.). Un solo filtro
    por logger nombrado alcanza para que TODOS los logger.info(...)/
    warning(...)/error(...) existentes lo muestren, sin tocar ninguno
    de esos call sites.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # evita handlers duplicados si se llama varias veces

    logger.setLevel(logging.INFO)
    logger.addFilter(_CorrelationFilter())

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(correlation_id)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
