"""
Tests de sandbox/ebpf/observer.py (Fase E4 del plan eBPF).

100% sin bpftrace ni sudo reales — `run()`/`main()` reciben un stream
de líneas ya armado (una lista, o un generador que simula una
interrupción a mitad de camino), nunca un pipe real. El filtro de
cgroup real (sandbox/ebpf/event_consumer.py::is_sandboxed_container_process)
se fuerza a True vía monkeypatch — ya tiene sus propios tests
dedicados en tests/test_ebpf_event_consumer.py; acá solo importa la
lógica de conteo/consumo de observer.py.
"""
from __future__ import annotations

import pytest

from audit.audit_log import audit_log
from sandbox.ebpf import event_consumer
from sandbox.ebpf.observer import main, run


@pytest.fixture(autouse=True)
def assume_sandboxed_container(monkeypatch):
    monkeypatch.setattr(event_consumer, "is_sandboxed_container_process", lambda pid: True)


def test_run_processes_a_realistic_mixed_stream_and_counts_correctly():
    stream = [
        '{"syscall":"execve","pid":1,"filename":"/usr/bin/docker"}\n',
        '{"syscall":"setuid","pid":2,"comm":"python","requested_uid":0}\n',
        "ruido que no es json\n",
        '{"syscall":"connect","pid":2,"comm":"python","family":2,"ip":"8.8.8.8","port":53}\n',
    ]

    processed, recorded = run(stream)

    assert processed == 4  # las 4 líneas, incluida la inválida y el execve descartado
    assert recorded == 2  # setuid + connect


def test_run_on_empty_stream_returns_zero_zero():
    assert run([]) == (0, 0)


def test_run_stops_gracefully_on_keyboard_interrupt_without_losing_the_count():
    def stream_that_gets_interrupted():
        yield '{"syscall":"setuid","pid":1,"comm":"python","requested_uid":0}\n'
        yield '{"syscall":"ptrace","pid":1,"comm":"python","request":0,"target_pid":2}\n'
        raise KeyboardInterrupt()

    processed, recorded = run(stream_that_gets_interrupted())

    # Se procesaron los 2 eventos que llegaron ANTES de la interrupción,
    # no se pierde el conteo ni se propaga la excepción.
    assert processed == 2
    assert recorded == 2


def test_run_writes_to_the_single_audit_log_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_log, "path", tmp_path / "audit.log")

    run(['{"syscall":"connect","pid":5,"comm":"python","family":2,"ip":"127.0.0.1","port":80}\n'])

    entries = audit_log.tail(5)
    assert entries[0]["event_type"] == "syscall_policy_violation"
    assert entries[0]["context"]["pid"] == 5


def test_main_does_not_raise_and_reads_from_the_given_stream(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_log, "path", tmp_path / "audit.log")

    main(stream=['{"syscall":"setuid","pid":9,"comm":"python","requested_uid":0}\n'])

    entries = audit_log.tail(5)
    assert entries[0]["context"]["pid"] == 9
