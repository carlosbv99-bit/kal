#!/usr/bin/env bash
# Fase E0/E1: mide el overhead REAL del prototipo bpftrace en esta
# máquina (no un benchmark público de un cluster de 400 nodos, que no
# representa el patrón de kal — ráfagas cortas en un solo host), y
# correlaciona lo que el prototipo ve contra los tests de resistencia a
# fuga que ya pasan sin eBPF.
#
# Corre tests/test_sandbox_escape_resistance.py dos veces: una sola
# (línea base) y una con kernel/lifecycle/ebpf/prototype_syscalls.bt activo en
# paralelo. Pide la contraseña de sudo UNA vez (bpftrace necesita
# privilegio para cargar los programas).
#
# Uso: bash kernel/lifecycle/ebpf/measure_overhead.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

TEST_FILE="tests/test_sandbox_escape_resistance.py"
LOG_DIR="$(mktemp -d)"
BT_SCRIPT="kernel/lifecycle/ebpf/prototype_syscalls.bt"

echo "== Corrida 1/2: SIN eBPF (línea base) =="
/usr/bin/time -v pytest "$TEST_FILE" -q > "$LOG_DIR/baseline.log" 2>&1 || true
grep -E "Elapsed|Maximum resident|Percent of CPU" "$LOG_DIR/baseline.log" || tail -20 "$LOG_DIR/baseline.log"

echo
echo "== Corrida 2/2: CON el prototipo bpftrace activo =="
echo "(puede pedir tu contraseña de sudo acá — bpftrace necesita privilegio para cargar los programas)"
sudo bpftrace "$BT_SCRIPT" > "$LOG_DIR/ebpf_events.log" 2>&1 &
BPFTRACE_PID=$!
sleep 2  # dar tiempo a que bpftrace compile y cargue los programas antes de arrancar los tests

/usr/bin/time -v pytest "$TEST_FILE" -q > "$LOG_DIR/with_ebpf.log" 2>&1 || true

sleep 1  # dejar que los últimos eventos lleguen al log antes de cortar
sudo kill -INT "$BPFTRACE_PID" 2>/dev/null || true
wait "$BPFTRACE_PID" 2>/dev/null || true

echo
echo "================= RESULTADO ================="
echo "-- tiempo/memoria SIN eBPF --"
grep -E "Elapsed|Maximum resident|Percent of CPU" "$LOG_DIR/baseline.log"
echo
echo "-- tiempo/memoria CON eBPF --"
grep -E "Elapsed|Maximum resident|Percent of CPU" "$LOG_DIR/with_ebpf.log"
echo
echo "-- tests: ambas corridas deberían decir lo mismo (mismo resultado, el prototipo solo observa) --"
grep -E "passed|failed|error" "$LOG_DIR/baseline.log" | tail -1
grep -E "passed|failed|error" "$LOG_DIR/with_ebpf.log" | tail -1
echo
echo "-- eventos capturados por el prototipo (cruzar contra qué test corrió en ese momento) --"
cat "$LOG_DIR/ebpf_events.log"
echo
echo "Logs completos en: $LOG_DIR"
