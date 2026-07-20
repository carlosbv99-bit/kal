"""
Registro de servicios del Kernel Service Bus + despacho por nombre de
método ("<servicio>.<acción>"). Puramente en memoria del proceso
principal — nunca sabe nada de sockets ni de contenedores (eso es
kernel/api/socket_server.py, que envuelve esto para exponerlo a una
skill aislada).
"""
from __future__ import annotations

from typing import Any


class ServiceNotFoundError(Exception):
    """El servicio nombrado en 'method' no está registrado."""


class ActionNotFoundError(Exception):
    """El servicio existe pero no tiene esa acción."""


class ArtifactNotFoundError(Exception):
    """Un parámetro 'artifact://...' no corresponde a ningún artefacto conocido."""


class KernelServiceBus:
    def __init__(self):
        self._services: dict[str, Any] = {}
        # Mapeo "artifact://..." -> ruta real de host. Una skill (dentro
        # del contenedor) solo conoce la referencia opaca — nunca la
        # ruta real del filesystem del host, que no significa nada
        # adentro y no debería exponerse a código de terceros sin
        # necesidad. SandboxedSkillTool._to_artifact() resuelve acá
        # cuando la skill devuelve el mismo "artifact://" que recibió
        # como resultado propio (ver kernel/services/services.py::ImageService.generate()).
        # Mecanismo deliberadamente mínimo — no un sistema de artefactos
        # completo (eso es la visión más grande de "Proyectos", no
        # construida todavía).
        self.artifact_paths: dict[str, str] = {}

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        service_name, _, action_name = method.partition(".")
        service = self._services.get(service_name)
        if service is None:
            raise ServiceNotFoundError(f"servicio desconocido: '{service_name}'")

        # Hallazgo de la revisión de seguridad 2026-07-09: antes esto
        # resolvía la acción con getattr genérico sobre CUALQUIER
        # atributo público del servicio — inofensivo mientras cada
        # servicio solo tuviera los métodos pensados como "acciones",
        # pero sin ninguna lista explícita, un método público agregado
        # a futuro para otro propósito (no pensado como acción del bus)
        # quedaría invocable igual, por accidente. ALLOWED_ACTIONS es la
        # lista explícita y con intención de cada servicio (ver
        # kernel/services/services.py) — dispatch() ya no confía en que
        # "es público" signifique "es una acción segura".
        allowed_actions = getattr(service, "ALLOWED_ACTIONS", frozenset())
        if action_name not in allowed_actions:
            raise ActionNotFoundError(f"acción desconocida: '{method}'")

        action = getattr(service, action_name, None)
        if action is None or not callable(action):
            raise ActionNotFoundError(f"acción desconocida: '{method}'")

        params = self._resolve_input_artifacts(params)
        result = action(**params)

        # "path" es un detalle de host — nunca cruza al otro lado del
        # socket (una skill no necesita ni debería ver rutas reales del
        # filesystem del host). Se registra acá para poder resolver el
        # "artifact://" de vuelta más tarde (ver resolve_artifact()).
        artifact_uri = result.get("artifact")
        real_path = result.pop("path", None)
        if artifact_uri and real_path:
            self.artifact_paths[artifact_uri] = real_path

        return result

    def resolve_artifact(self, uri: str) -> str | None:
        return self.artifact_paths.get(uri)

    def _resolve_input_artifacts(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Resolución de artefactos de ENTRADA — contraparte de la resolución
        de salida de arriba. `image.generate`/`audio.synthesize` nunca
        reciben un artefacto como parámetro (solo texto), pero
        `stt.transcribe`/`image.inpaint` sí necesitan uno ya existente
        (un audio/imagen generado por una llamada anterior EN LA MISMA
        ejecución de la skill). Cualquier valor de `params` que sea un
        `"artifact://..."` se reemplaza acá por la ruta real de host —
        la skill sigue sin ver nunca esa ruta, solo la referencia opaca
        que ya tenía de un resultado anterior.
        """
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("artifact://"):
                real_path = self.artifact_paths.get(value)
                if real_path is None:
                    raise ArtifactNotFoundError(f"artefacto desconocido: '{value}'")
                resolved[key] = real_path
            else:
                resolved[key] = value
        return resolved


def _build_default_bus() -> KernelServiceBus:
    from kernel.services.services import AudioService, ImageService, STTService

    bus = KernelServiceBus()
    bus.register("image", ImageService())
    bus.register("audio", AudioService())
    bus.register("stt", STTService())
    return bus


# Singleton, mismo patrón que tool_registry (kernel/registry/registry.py)
# / audit_log (audit/audit_log.py) / permission_cascade
# (kernel/permissions/permission_cascade.py). Nombrado `kernel_service_bus`,
# no `kernel` a secas — evita la colisión confusa con el nombre del
# propio paquete `kernel` que lo contiene.
kernel_service_bus = _build_default_bus()
