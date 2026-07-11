"""
Verifica el gate de token administrativo (ver utils/admin_token.py,
agent_core/orchestrator.py) sobre los endpoints que hacen de facto de
"aprobación humana": self-modification (propose/apply), aprobación y
rollback de herramientas, y autorreparación.

HALLAZGO REAL que motiva estos tests (revisión de seguridad,
2026-07-09): antes de esto, `approved_by` era un string que el propio
cliente HTTP elegía sin verificar identidad alguna — cualquiera que
alcanzara el puerto del agente podía aprobar/aplicar cambios. Estos
tests no vuelven a probar la lógica interna de self_modification/tools
(ya cubierta en sus propios archivos de test) — solo que el gate
bloquea sin token válido y deja pasar con uno correcto.

No se ejecuta el pipeline completo de self-modification (copiar el
proyecto + correr pytest en subproceso) a propósito: usar un
target_path/proposal_id/nombre de herramienta inexistente alcanza para
confirmar que la request llegó a la lógica real (un error 400/404 de
negocio, nunca 401) sin pagar el costo de una corrida real.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core.orchestrator import _ADMIN_TOKEN, app

client = TestClient(app)

_GATED_REQUESTS = [
    ("POST", "/tools/no-existe-esta-herramienta/approve", {"approved_by": "alguien"}),
    ("POST", "/tools/no-existe-esta-herramienta/rollback", {"to_version": 1, "approved_by": "alguien"}),
    (
        "POST",
        "/self-modification/propose",
        {"target_path": "no_existe.py", "proposed_source": "x = 1", "justification": "test"},
    ),
    ("POST", "/self-modification/apply", {"proposal_id": "no-existe", "approved_by": "alguien"}),
    ("POST", "/diagnostics/invariante_inexistente/self-repair", {}),
]


def test_gated_endpoints_reject_missing_token():
    for method, path, body in _GATED_REQUESTS:
        response = client.request(method, path, json=body)
        assert response.status_code == 401, f"{method} {path} debería rechazar sin token"


def test_gated_endpoints_reject_wrong_token():
    for method, path, body in _GATED_REQUESTS:
        response = client.request(method, path, json=body, headers={"X-Kal-Admin-Token": "token-incorrecto"})
        assert response.status_code == 401, f"{method} {path} debería rechazar con token incorrecto"


def test_gated_endpoints_accept_correct_token_and_reach_real_logic():
    headers = {"X-Kal-Admin-Token": _ADMIN_TOKEN}
    for method, path, body in _GATED_REQUESTS:
        response = client.request(method, path, json=body, headers=headers)
        assert response.status_code != 401, f"{method} {path} no debería rechazar con el token correcto"


def test_ungated_endpoint_still_works_without_any_token():
    """/health nunca debería exigir el token — no es una acción sensible."""
    response = client.get("/health")
    assert response.status_code == 200
