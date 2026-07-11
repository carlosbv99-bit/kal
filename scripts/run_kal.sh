#!/usr/bin/env bash
# Arranca kal (API + frontend en el mismo proceso, puerto 8000).
#
# Requisitos que deben estar YA corriendo antes de este script (la
# conexión es inmediata al arrancar, no perezosa):
#   - Docker daemon (TaskExecutor lo necesita para el sandbox)
#   - Ollama (para el chat; si no está, /status lo marcará pero kal
#     igual arranca — solo /chat fallará hasta que Ollama esté arriba)
#
# Uso:
#   chmod +x scripts/run_kal.sh
#   ./scripts/run_kal.sh

set -euo pipefail

echo "== Verificando Docker =="
if ! docker info > /dev/null 2>&1; then
  echo "ERROR: Docker no está corriendo. kal lo necesita para arrancar (TaskExecutor se conecta al iniciar, no de forma perezosa)."
  exit 1
fi

echo "== Verificando Ollama (opcional, solo afecta /chat) =="
if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "Ollama disponible."
else
  echo "AVISO: Ollama no responde en localhost:11434 — kal arrancará igual, pero /chat fallará hasta que esté arriba."
fi

echo "== Arrancando kal en http://localhost:8000 =="
uvicorn agent_core.orchestrator:app --host 0.0.0.0 --port 8000 --reload
