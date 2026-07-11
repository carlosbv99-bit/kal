"""
Token compartido para las acciones administrativas más sensibles del
orquestador: aplicar/proponer self-modification, aprobar/revertir
herramientas, autorreparación (ver agent_core/orchestrator.py).

HALLAZGO REAL DE LA REVISIÓN DE SEGURIDAD (2026-07-09): la API HTTP del
agente no tenía ninguna autenticación, y docker-compose publicaba su
puerto a 0.0.0.0 del host (alcanzable desde toda la LAN, no solo esta
máquina) — `POST /self-modification/apply` aceptaba `approved_by` como
un string libre mandado por el cliente, sin verificar identidad
alguna: el modelo entero de "aprobación humana obligatoria" se reducía
a un campo de formulario. Este módulo, junto con el binding a
127.0.0.1 en docker-compose.yml, cierra esa brecha con dos capas
independientes en vez de depender solo de una.

Se genera una sola vez y se persiste en disco (mismo directorio que
las claves de firma, ver SigningConfig) — no requiere que el usuario
configure nada a mano para que el agente siga funcionando localmente.
"""
from __future__ import annotations

import secrets
from pathlib import Path

_TOKEN_PATH = Path("data/keys/admin_token")


def get_or_create_admin_token(token_path: Path = _TOKEN_PATH) -> str:
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()

    token = secrets.token_urlsafe(32)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token, encoding="utf-8")
    token_path.chmod(0o600)
    return token
