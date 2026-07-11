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

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # evita handlers duplicados si se llama varias veces

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
