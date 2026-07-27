"""
ToolRepeatLimiter: tope estructural a cuántas veces se puede llamar la
MISMA herramienta dentro de un único AgentLoop.run() — extraído de
agent_core/llm/agent_loop.py (2026-07-27) para bajar la densidad de ese
archivo, sin cambiar ningún comportamiento (mismo conteo, mismos topes,
misma excepción de "ya tuvo éxito una vez" para herramientas VS
Code-only).

BUG REAL ENCONTRADO EN USO que motivó este mecanismo (no un límite
teórico): "genera una raqueta de tenis" generó la imagen correcta una
vez y después, en el mismo turno, 3 imágenes más de paisajes sin
relación, sin llegar nunca a una respuesta final — el modelo nunca ve
el resultado visual de una generación (la observación es solo la ruta
del archivo), así que perdió el hilo de la tarea. La regla de
SYSTEM_PROMPT sola no alcanzó (ya estaba activa cuando pasó esto) —
este tope es la barrera estructural que no depende de que el modelo la
respete.

Deliberadamente NO sabe nada de self-check (analyze_image) — ese es un
tope MÁS ESTRICTO que se calcula aparte (ver
agent_core/llm/self_check_tracker.py::SelfCheckTracker) y se le pasa
acá como el parámetro `is_self_checked` de evaluate(), la única forma
en que estas dos clases se tocan.
"""
from __future__ import annotations

from agent_core.client_provider import _VSCODE_ONLY_TOOL_NAMES


class ToolRepeatLimiter:
    def __init__(self, max_tool_repeats: int):
        self.max_tool_repeats = max_tool_repeats
        self._counts: dict[str, int] = {}
        self._succeeded_vscode_only_tools: set[str] = set()

    def evaluate(self, name: str, is_self_checked: bool) -> tuple[bool, int]:
        """
        Incrementa el contador de `name` (la llamada ACTUAL ya cuenta)
        y devuelve (over_limit, effective_limit) para decidir si se
        ejecuta o se rechaza sin correrla.

        `is_self_checked`: True si `name` ya se autochequeó con
        analyze_image en este turno (ver SelfCheckTracker.is_checked())
        — aplica un tope más estricto (como mucho 2: la original + un
        solo reintento) en vez de max_tool_repeats.

        Herramientas de _VSCODE_ONLY_TOOL_NAMES (propose_project_files/
        import_resource/read_workspace_file) que YA tuvieron éxito una
        vez quedan sobre el límite sin importar el conteo — su revisión
        ocurre FUERA de este turno (del lado del usuario), así que una
        segunda propuesta ya exitosa nunca tiene información nueva que
        la justifique. BUG REAL ENCONTRADO EN USO: un intento FALLIDO
        (sin proponer nada) no debía contar contra este tope de 1 — si
        no, el modelo perdía su única chance real de corregir un error
        propio (una ruta inválida) y terminaba llamando a una
        herramienta totalmente distinta y equivocada en su lugar. Por
        eso el chequeo es `ya tuvo éxito`, no `ya se llamó`.
        """
        self._counts[name] = self._counts.get(name, 0) + 1
        count = self._counts[name]
        if is_self_checked:
            effective_limit = min(2, self.max_tool_repeats)
            over_limit = count > effective_limit
        elif name in _VSCODE_ONLY_TOOL_NAMES:
            effective_limit = self.max_tool_repeats
            over_limit = name in self._succeeded_vscode_only_tools or count > effective_limit
        else:
            effective_limit = self.max_tool_repeats
            over_limit = count > effective_limit
        return over_limit, effective_limit

    def record_outcome(self, name: str, observation: str) -> None:
        """Llamar solo tras una ejecución REAL (nunca tras un rechazo
        sin ejecutar) — marca herramientas VS Code-only como ya
        exitosas para la excepción de evaluate() de arriba."""
        if name in _VSCODE_ONLY_TOOL_NAMES and not observation.startswith("ERROR"):
            self._succeeded_vscode_only_tools.add(name)

    def already_succeeded(self, name: str) -> bool:
        """Para que run() elija el mensaje de rechazo correcto (ya tuvo
        éxito antes vs. todavía no logró nada) sin exponer el set interno."""
        return name in self._succeeded_vscode_only_tools
