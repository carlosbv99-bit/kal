"""
Extracción de un objeto JSON embebido en una respuesta de texto de un
LLM potencialmente ruidosa (sin fences, con fences ```json, o con texto
alrededor). Compartido por:
  - agent_loop.py: detecta un tool_call imitado como texto plano cuando
    el modelo no completa tool_calls nativo (ver nota real ahí).
  - planner.py: parsea la lista de pasos que el modelo debería devolver
    como {"steps": [...]}.

Mismo problema en ambos casos: un modelo sin soporte confiable de
salida estructurada. Probar, en orden: JSON dentro de un fence
```json, el contenido completo si empieza con '{', y cualquier objeto
JSON embebido en el texto — el primero que parsea como JSON válido gana.
"""
from __future__ import annotations

import json
import re

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"(\{.*\})", re.DOTALL)


def extract_json_object(content: str) -> dict | None:
    """Devuelve el primer objeto JSON parseable encontrado en `content`, o None."""
    if not content or not content.strip():
        return None

    candidates = []
    fence_match = _JSON_FENCE_RE.search(content)
    if fence_match:
        candidates.append(fence_match.group(1))
    stripped = content.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    bare_match = _BARE_JSON_RE.search(content)
    if bare_match:
        candidates.append(bare_match.group(1))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None
