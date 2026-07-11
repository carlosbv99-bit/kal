"""
Estrategias de reparación automática por tipo de error.

Cada estrategia recibe el contexto del error y devuelve un RepairResult.
Ninguna estrategia ejecuta código directamente: todo lo que implique
correr código pasa por sandbox/, incluida la verificación de que la
reparación propuesta funciona.

Dos estilos de RepairResult, según si la estrategia ya ejecutó el
código reparado ella misma o no (ver campo `already_retried`):
  - ImportErrorStrategy instala el paquete Y reejecuta el código
    original en el MISMO contenedor efímero (una instalación en un
    contenedor no persiste a otro), así que el resultado final ya está
    disponible en `output` — el llamador no debe reintentar de nuevo.
  - RuntimeErrorStrategy no reintenta por sí misma: solo confirma que
    existe un checkpoint válido y delega el reintento al llamador
    (task_execution/executor.py), que sabe cómo re-ejecutar el código
    original.
"""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_core.memory.mid_term import MidTermMemory
from audit.audit_log import AuditEvent, audit_log
from sandbox.docker_runner import DockerSandboxRunner
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Imagen usada específicamente para instalar paquetes: necesita pip,
# a propósito distinta de SANDBOX_IMAGE (que puede ser la minimizada
# sin pip, ver sandbox/images/minimal/). Instalar es una operación
# deliberada y estrecha, no ejecución de código arbitrario del agente.
INSTALLER_IMAGE = os.environ.get("INSTALLER_IMAGE", "python:3.11-slim")

# Patrón de nombre de paquete (PEP 508, simplificado): solo
# alfanumérico, punto, guion y guion bajo. Aunque subprocess con lista
# de argumentos ya evita inyección de shell, esta validación es una
# capa adicional barata contra nombres absurdos o mal formados.
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_PACKAGE_NAME_LENGTH = 214  # límite real impuesto por PyPI


@dataclass
class RepairContext:
    error_type: str
    error_message: str
    source_code: str
    location: str
    traceback_str: str = ""


@dataclass
class RepairResult:
    success: bool
    fixed_code: str | None = None
    detail: str = ""
    # True si la propia estrategia ya ejecutó el código reparado y
    # `output` contiene el resultado final (ver ImportErrorStrategy).
    # False si el llamador debe reintentar por su cuenta con fixed_code
    # (o con el código original, si fixed_code es None) — ver
    # RuntimeErrorStrategy.
    already_retried: bool = False
    output: str | None = None


class RepairStrategy(ABC):
    @abstractmethod
    def repair(self, ctx: RepairContext) -> RepairResult:
        ...


class SyntaxErrorStrategy(RepairStrategy):
    """
    Corrección automática de código con SyntaxError.

    PENDIENTE: requiere una llamada a un modelo generador para proponer
    la corrección (no hay heurística determinista razonable para
    "arreglar sintaxis rota" en general). Se deja fuera de esta ronda
    de implementación a propósito — ImportError y RuntimeError no
    dependen de un modelo externo y por eso se implementaron primero.
    """

    def repair(self, ctx: RepairContext) -> RepairResult:
        # TODO: candidate = propose_fix_via_llm(ctx.source_code, ctx.error_message)
        # validar candidate con code_analysis.ast_validator.validate_code()
        # antes de aceptarlo, y solo entonces devolver fixed_code=candidate,
        # already_retried=False (el llamador se encarga de reejecutar).
        raise NotImplementedError("Implementar generación de corrección de sintaxis vía modelo")


class RuntimeErrorStrategy(RepairStrategy):
    """
    RuntimeError: confirma la existencia de un checkpoint previo en
    memoria de mediano plazo y delega el reintento al llamador.

    LIMITACIÓN CONOCIDA Y ACEPTADA: esto no es un rollback de estado
    real (no hay un sistema de versionado/diffing de estado). En la
    práctica es "reintentar con el mismo código de entrada", partiendo
    de que el checkpoint confirma que existió un punto de partida
    válido antes del fallo. Un rollback más fino requeriría un sistema
    de estado explícito que hoy no existe — se documenta como TODO
    futuro, no se finge una capacidad que no está implementada.
    """

    def __init__(self, mid_term: MidTermMemory | None = None):
        self.mid_term = mid_term or MidTermMemory()

    def repair(self, ctx: RepairContext) -> RepairResult:
        if not ctx.location.startswith("task:"):
            return RepairResult(
                success=False,
                detail="ubicación no asociada a una tarea con checkpoint (formato esperado: 'task:<id>')",
            )

        task_id = ctx.location.split(":", 1)[1]
        checkpoint = self.mid_term.get_by_id(f"checkpoint:{task_id}")
        if checkpoint is None:
            return RepairResult(
                success=False,
                detail="no se encontró checkpoint previo para esta tarea; no hay estado seguro al cual volver",
            )

        logger.info(f"Checkpoint encontrado para tarea {task_id}, se delega el reintento al llamador")
        return RepairResult(
            success=True,
            detail=f"checkpoint '{checkpoint.id}' encontrado; el llamador debe reintentar",
            already_retried=False,
            fixed_code=None,  # sin corrección de código: se reintenta el mismo
        )


class ValidationErrorStrategy(RepairStrategy):
    """
    Código rechazado por la validación estática (denylist de
    code_analysis) ANTES de llegar a ejecutarse en el sandbox — nunca
    corrió, así que no hay estado del cual recuperarse, y no tiene
    sentido reintentar el mismo código: la violación es determinista
    (p.ej. un import prohibido), reintentar produce exactamente el
    mismo rechazo cada vez.

    BUG REAL ENCONTRADO EN USO: antes de que existiera esta estrategia,
    este caso caía en el fallback genérico de classify_sandbox_error()
    (RuntimeError), y RuntimeErrorStrategy reintentaba ciegamente el
    mismo código rechazado — 3 intentos idénticos desperdiciados hasta
    abrir el circuit breaker, para un fallo que ya se sabía desde el
    primer intento que nunca iba a cambiar de resultado.

    Nunca reintenta: falla una sola vez, con un detalle que le dice al
    llamador (agente o humano) que hace falta escribir código distinto
    que evite la construcción prohibida, no volver a correr el mismo.
    """

    def repair(self, ctx: RepairContext) -> RepairResult:
        return RepairResult(
            success=False,
            detail=(
                "El código fue rechazado por el validador de seguridad antes de "
                "ejecutarse (nunca llegó a correr en el sandbox) — reintentar el "
                "mismo código no lo va a arreglar, hace falta escribir una versión "
                f"distinta que evite lo señalado: {ctx.error_message}"
            ),
        )


class ImportErrorStrategy(RepairStrategy):
    """
    ImportError: instala el módulo faltante y reejecuta el código
    original, ambos en el MISMO contenedor efímero (una instalación en
    un contenedor no persiste a otro — por eso van juntos en un solo
    script, no en dos pasos separados).

    SEGURIDAD: esta es la única estrategia que requiere una excepción
    de red (network_mode distinto de "none"). Por diseño, si
    "network" está en config.yaml:
    tool_integration.require_human_approval_for (está por defecto),
    esta estrategia NO ejecuta nada automáticamente — solo registra la
    necesidad de aprobación humana y devuelve success=False. Esto es
    deliberado: instalar código de terceros con acceso a red es
    exactamente el tipo de acción que este proyecto trata como
    sensible en todos los demás contextos (ver tool_integration/registry.py).
    """

    def __init__(self, runner: DockerSandboxRunner | None = None):
        self.runner = runner or DockerSandboxRunner()

    def repair(self, ctx: RepairContext) -> RepairResult:
        raw_module = self._extract_module_name(ctx.error_message)
        if raw_module is None:
            return RepairResult(success=False, detail="no se pudo determinar el módulo faltante desde el mensaje de error")

        # Solo el paquete de nivel superior es un candidato razonable de
        # nombre de paquete PyPI (p.ej. "a.b.c" -> "a"). No hay garantía
        # de que el nombre de import coincida con el nombre del paquete
        # en PyPI (p.ej. "sklearn" vs "scikit-learn") — limitación
        # conocida, no resuelta en esta versión.
        package_name = raw_module.split(".")[0]

        if not self._is_valid_package_name(package_name):
            return RepairResult(success=False, detail=f"nombre de paquete con formato inválido: {package_name!r}")

        if self._requires_human_approval():
            audit_log.record(
                AuditEvent(
                    event_type="human_escalation",
                    summary=f"Instalación de '{package_name}' requiere aprobación humana (excepción de red)",
                    context={"package": package_name, "location": ctx.location},
                    outcome="escalated",
                )
            )
            return RepairResult(success=False, detail="requiere_aprobacion_humana_para_acceso_de_red")

        script = self._build_install_and_retry_script(package_name, ctx.source_code)
        result = self.runner.run(script, image=INSTALLER_IMAGE, network_mode="bridge")

        audit_log.record(
            AuditEvent(
                event_type="error_repair",
                summary=f"Instalación automática de módulo '{package_name}'",
                context={
                    "package": package_name,
                    "network_exception": True,
                    "exit_code": result.exit_code,
                    "location": ctx.location,
                },
                outcome="success" if result.status == "success" else "failure",
            )
        )

        if result.status == "success":
            return RepairResult(
                success=True,
                fixed_code=ctx.source_code,
                detail=f"módulo '{package_name}' instalado y código original reejecutado correctamente",
                already_retried=True,
                output=result.stdout,
            )
        return RepairResult(
            success=False,
            detail=result.stderr or f"fallo al instalar '{package_name}' o al reejecutar el código",
        )

    @staticmethod
    def _is_valid_package_name(name: str) -> bool:
        return bool(_PACKAGE_NAME_RE.match(name)) and len(name) <= _MAX_PACKAGE_NAME_LENGTH

    @staticmethod
    def _requires_human_approval() -> bool:
        return "network" in settings.tool_integration.require_human_approval_for

    @staticmethod
    def _build_install_and_retry_script(package_name: str, original_code: str) -> str:
        # package_name ya fue validado estrictamente arriba (solo
        # alfanumérico, punto, guion, guion bajo) — repr() además evita
        # cualquier ambigüedad de comillas al insertarlo en el script.
        #
        # IMPORTANTE: se instala con --target /workspace/.deps, NO en el
        # site-packages del sistema. El contenedor corre con
        # read_only=True en todo el filesystem salvo /workspace y /tmp
        # (ver sandbox/docker_runner.py) — esa garantía de seguridad no
        # se relaja para esto. Un intento inicial de instalar sin
        # --target falló exactamente por esto: "Read-only file system"
        # al escribir en site-packages, confirmado en pruebas reales.
        return (
            "import subprocess, sys\n"
            "subprocess.check_call(\n"
            "    [sys.executable, '-m', 'pip', 'install', '--no-deps', '--quiet',\n"
            f"     '--target', '/workspace/.deps', {package_name!r}]\n"
            ")\n"
            "sys.path.insert(0, '/workspace/.deps')\n"
            "\n"
            "# --- código original que había fallado por ImportError ---\n"
            f"{original_code}\n"
        )

    @staticmethod
    def _extract_module_name(error_message: str) -> str | None:
        # Cubre tanto "ImportError: No module named 'x'" (Python 2 y
        # algunos casos de Python 3) como el mensaje real y más común
        # en Python 3, "ModuleNotFoundError: No module named 'x'".
        match = re.search(r"No module named '([\w\.]+)'", error_message)
        return match.group(1) if match else None


STRATEGY_REGISTRY: dict[str, type[RepairStrategy]] = {
    "SyntaxError": SyntaxErrorStrategy,
    "RuntimeError": RuntimeErrorStrategy,
    "ImportError": ImportErrorStrategy,
    "ModuleNotFoundError": ImportErrorStrategy,  # subclase real de ImportError en Python 3
    "ValidationError": ValidationErrorStrategy,
}
