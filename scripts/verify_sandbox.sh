#!/usr/bin/env bash
# Script de verificación manual del stack completo vía docker-compose.
#
# Uso:
#   chmod +x scripts/verify_sandbox.sh
#   ./scripts/verify_sandbox.sh
#
# Requiere: docker, docker compose, curl, jq (opcional, para pretty-print).
# Levanta el stack, espera a que sandbox_runner responda, ejecuta una
# batería mínima de pruebas contra la API HTTP real (no contra la clase
# Python directamente, para probar también sandbox_api.py y la red
# interna de docker-compose).

set -euo pipefail

SANDBOX_URL="http://localhost:9000"
COMPOSE_CMD="docker compose"

echo "== Levantando stack (sandbox_runner) =="
$COMPOSE_CMD up -d --build sandbox_runner

echo "== Esperando a que sandbox_runner responda en /health =="
for i in $(seq 1 30); do
  if curl -sf "${SANDBOX_URL}/health" > /dev/null 2>&1; then
    echo "sandbox_runner disponible tras ${i}s"
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo "ERROR: sandbox_runner no respondió tras 30s"
    $COMPOSE_CMD logs sandbox_runner
    exit 1
  fi
done

pass=0
fail=0

check() {
  local name="$1"
  local expected_status="$2"
  local payload="$3"

  echo -n "-- ${name}: "
  actual_status=$(curl -s -X POST "${SANDBOX_URL}/execute" \
    -H "Content-Type: application/json" \
    -d "${payload}" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")

  if [ "$actual_status" == "$expected_status" ]; then
    echo "OK (status=${actual_status})"
    pass=$((pass + 1))
  else
    echo "FALLO (esperado=${expected_status}, obtenido=${actual_status})"
    fail=$((fail + 1))
  fi
}

check "código seguro ejecuta correctamente" "success" \
  '{"source_code": "print(1 + 1)"}'

check "SyntaxError se rechaza en validación estática" "error" \
  '{"source_code": "def broken(:\n  pass"}'

check "eval() prohibido se rechaza en validación estática" "error" \
  '{"source_code": "eval(\"1+1\")"}'

check "import os prohibido se rechaza en validación estática" "error" \
  '{"source_code": "import os\nos.system(\"ls\")"}'

check "excepción en runtime se captura como error" "error" \
  '{"source_code": "raise ValueError(\"boom\")"}'

check "bucle infinito corta por timeout" "timeout" \
  '{"source_code": "while True: pass"}'

echo ""
echo "== Resultado: ${pass} OK, ${fail} FALLOS =="

if [ "$fail" -gt 0 ]; then
  exit 1
fi
