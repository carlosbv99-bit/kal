#!/usr/bin/env bash
# Fase E4: modo solo-observación durante uso REAL de kal (no solo
# tests) — dejalo corriendo mientras usás kal normalmente (chat,
# generación de imágenes, skills), para conocer la tasa de falsos
# positivos antes de considerar enforcement (E5). Nunca bloquea nada,
# solo registra en la auditoría (logs/audit.log).
#
# Arranque manual por sesión (elegido explícitamente, ver README.md
# Fase E4) — sin cambios permanentes al sistema.
#
# Uso: bash kernel/lifecycle/ebpf/run_observer.sh
# (pide tu contraseña de sudo una vez, para bpftrace — el resto del
# pipeline corre SIN privilegios). Ctrl+C para terminar y ver el
# resumen de violaciones detectadas en esta sesión.
set -euo pipefail
cd "$(dirname "$0")/../.."

PYTHON_BIN=".venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

sudo bpftrace kernel/lifecycle/ebpf/syscall_events.bt | "$PYTHON_BIN" -m kernel.lifecycle.ebpf.observer
