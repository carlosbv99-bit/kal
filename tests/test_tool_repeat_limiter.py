"""
Tests de agent_core/llm/tool_repeat_limiter.py::ToolRepeatLimiter —
extraído de agent_core/llm/agent_loop.py (2026-07-27) para bajar la
densidad de ese archivo. Estos tests cubren la clase de forma aislada;
tests/test_agent_loop.py sigue cubriendo el comportamiento end-to-end
vía AgentLoop.run().
"""
from __future__ import annotations

from agent_core.llm.tool_repeat_limiter import ToolRepeatLimiter


def test_stays_under_limit_while_below_max_tool_repeats():
    limiter = ToolRepeatLimiter(max_tool_repeats=3)

    for _ in range(3):
        over_limit, effective_limit = limiter.evaluate("image_generation", is_self_checked=False)
        assert over_limit is False
        assert effective_limit == 3


def test_goes_over_limit_past_max_tool_repeats():
    limiter = ToolRepeatLimiter(max_tool_repeats=3)
    for _ in range(3):
        limiter.evaluate("image_generation", is_self_checked=False)

    over_limit, effective_limit = limiter.evaluate("image_generation", is_self_checked=False)

    assert over_limit is True
    assert effective_limit == 3


def test_self_checked_tools_get_a_stricter_cap_of_2_even_with_a_higher_max_tool_repeats():
    limiter = ToolRepeatLimiter(max_tool_repeats=5)

    first, _ = limiter.evaluate("image_generation", is_self_checked=True)
    second, _ = limiter.evaluate("image_generation", is_self_checked=True)
    third, effective_limit = limiter.evaluate("image_generation", is_self_checked=True)

    assert (first, second, third) == (False, False, True)
    assert effective_limit == 2


def test_self_checked_cap_never_exceeds_a_lower_max_tool_repeats():
    limiter = ToolRepeatLimiter(max_tool_repeats=1)

    over_limit, effective_limit = limiter.evaluate("image_generation", is_self_checked=True)

    assert over_limit is False
    assert effective_limit == 1


def test_vscode_only_tool_that_already_succeeded_is_over_limit_even_on_its_second_call():
    """
    BUG REAL ENCONTRADO EN USO (2026-07-24, VS Code): un intento FALLIDO
    de propose_project_files/import_resource no debe contar contra el
    tope de 1 (el modelo debe poder corregir su propio error) — pero
    una vez que YA tuvo éxito, cualquier llamada más está sobre el
    límite sin importar cuántas veces se llamó en total.
    """
    limiter = ToolRepeatLimiter(max_tool_repeats=5)
    limiter.evaluate("propose_project_files", is_self_checked=False)
    limiter.record_outcome("propose_project_files", observation="Se prepararon 2 archivo(s)")

    over_limit, _ = limiter.evaluate("propose_project_files", is_self_checked=False)

    assert over_limit is True
    assert limiter.already_succeeded("propose_project_files") is True


def test_vscode_only_tool_that_only_failed_so_far_can_still_retry():
    limiter = ToolRepeatLimiter(max_tool_repeats=5)
    limiter.evaluate("propose_project_files", is_self_checked=False)
    limiter.record_outcome("propose_project_files", observation="ERROR: ruta inválida")

    over_limit, _ = limiter.evaluate("propose_project_files", is_self_checked=False)

    assert over_limit is False
    assert limiter.already_succeeded("propose_project_files") is False


def test_record_outcome_ignores_tools_outside_vscode_only_names():
    limiter = ToolRepeatLimiter(max_tool_repeats=5)
    limiter.record_outcome("image_generation", observation="ruta/a/la/imagen.png")

    assert limiter.already_succeeded("image_generation") is False


def test_counts_are_independent_per_tool_name():
    limiter = ToolRepeatLimiter(max_tool_repeats=1)
    limiter.evaluate("image_generation", is_self_checked=False)

    over_limit, _ = limiter.evaluate("image_editing", is_self_checked=False)

    assert over_limit is False


def test_is_blocked_is_false_before_reaching_the_limit():
    limiter = ToolRepeatLimiter(max_tool_repeats=3)
    limiter.evaluate("image_generation", is_self_checked=False)

    assert limiter.is_blocked("image_generation", is_self_checked=False) is False


def test_is_blocked_is_true_once_the_limit_is_reached():
    limiter = ToolRepeatLimiter(max_tool_repeats=3)
    for _ in range(3):
        limiter.evaluate("image_generation", is_self_checked=False)

    assert limiter.is_blocked("image_generation", is_self_checked=False) is True


def test_is_blocked_never_a_tool_never_called():
    limiter = ToolRepeatLimiter(max_tool_repeats=1)

    assert limiter.is_blocked("image_generation", is_self_checked=False) is False


def test_is_blocked_does_not_mutate_counts_as_a_side_effect():
    """Consultar is_blocked() no debe contar como un intento — a
    diferencia de evaluate(), que sí incrementa el contador."""
    limiter = ToolRepeatLimiter(max_tool_repeats=3)
    limiter.evaluate("image_generation", is_self_checked=False)

    for _ in range(10):
        limiter.is_blocked("image_generation", is_self_checked=False)

    over_limit, _ = limiter.evaluate("image_generation", is_self_checked=False)
    assert over_limit is False  # segunda llamada real, todavía bajo el tope de 3


def test_is_blocked_true_for_a_vscode_only_tool_that_already_succeeded():
    limiter = ToolRepeatLimiter(max_tool_repeats=5)
    limiter.evaluate("propose_project_files", is_self_checked=False)
    limiter.record_outcome("propose_project_files", observation="Se prepararon 2 archivo(s)")

    assert limiter.is_blocked("propose_project_files", is_self_checked=False) is True


def test_is_blocked_false_for_a_vscode_only_tool_that_only_failed_so_far():
    limiter = ToolRepeatLimiter(max_tool_repeats=5)
    limiter.evaluate("propose_project_files", is_self_checked=False)
    limiter.record_outcome("propose_project_files", observation="ERROR: ruta inválida")

    assert limiter.is_blocked("propose_project_files", is_self_checked=False) is False


def test_is_blocked_uses_the_stricter_cap_of_2_for_self_checked_tools():
    limiter = ToolRepeatLimiter(max_tool_repeats=5)
    limiter.evaluate("image_generation", is_self_checked=True)
    limiter.evaluate("image_generation", is_self_checked=True)

    assert limiter.is_blocked("image_generation", is_self_checked=True) is True
    # Bajo el tope general (5), el mismo conteo sin autochequeo no está bloqueado.
    assert limiter.is_blocked("image_generation", is_self_checked=False) is False
