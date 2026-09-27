"""
Carga y valida la configuración del sistema desde config/config.yaml.

Usar SIEMPRE esta interfaz en vez de leer el YAML directamente en otros
módulos, para que la validación de esquema sea consistente en todo el
proyecto y los cambios de config no rompan silenciosamente algún módulo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Antes de leer nada de os.environ, asegura que .env ya se haya cargado
# al proceso — python-dotenv era dependencia declarada desde el inicio
# del proyecto pero nunca se llamaba a load_dotenv().
load_dotenv()


class ResourceBrokerConfig(BaseModel):
    """
    Cualquier consumidor del kernel (image/audio/STT en kal-in, u otro
    proceso pesado en un runtime distinto) puede cargar un modelo
    perezosamente vía kernel/broker/resource_broker.py sin nunca
    descargarlo por su cuenta — BUG REAL ENCONTRADO EN USO (en kal-in,
    antes del split): en una máquina sin GPU, un pipeline de varios GB
    se queda en RAM para siempre una vez usado, compitiendo con
    servicios chicos (Ollama) por la misma RAM del sistema.
    """
    idle_timeout_seconds: int = 300
    min_available_ram_mb: int = 2048
    # Timeout PROPIO (más largo) para un servicio liviano de uso muy
    # frecuente (p.ej. el modelo de chat de Ollama en kal-in) — se
    # descargaba tan seguido como los pipelines pesados (que sí conviene
    # liberar rápido) pese a ser mucho más chico y usarse más seguido.
    # NUNCA afecta el chequeo de RAM baja (ver
    # ResourceBroker.evict_idle_and_pressured): ante presión real de
    # memoria, se libera igual que cualquier otro recurso, sin
    # excepción — esto solo cambia CUÁNTO tiempo de inactividad
    # tolera antes de liberarse por reloj.
    ollama_idle_timeout_seconds: int = 1800
    # BUG REAL ENCONTRADO EN USO (2026-08-28, en kal-in): evict_idle_and_pressured()
    # solo se llamaba en dos momentos puntuales (antes de un pedido, antes
    # de cargar un pipeline pesado) — nunca por su cuenta. Dos caídas
    # reales pasaron sin ningún pedido nuevo disparando ese chequeo
    # mientras la RAM se agotaba por otra causa (una suite de tests
    # corriendo en paralelo) — nada evictaba nada hasta que el OOM
    # killer del sistema operativo actuó a ciegas. Este intervalo dispara
    # el MISMO chequeo (misma lógica, sin cambios) de forma periódica,
    # independiente del tráfico real.
    pressure_check_interval_seconds: int = 30


class SandboxConfig(BaseModel):
    network_mode: Literal["none", "bridge"] = "none"
    memory_limit_mb: int = 512
    cpu_limit: float = 1.0
    timeout_seconds: int = 30
    pids_limit: int = 64
    filesystem: str = "read_only_except_workspace"


class ToolIntegrationConfig(BaseModel):
    allow_dynamic_tool_creation: bool = True
    require_human_approval_for: list[str] = Field(default_factory=list)


class PermissionCascadeConfig(BaseModel):
    """
    Cascada de permisos de varios niveles (ver sdk/permissions.py::
    PermissionCascade) — "más restrictivo gana". Strings planos (no el enum
    Permission) para no acoplar utils/config.py a tool_integration, mismo
    criterio que ToolIntegrationConfig.require_human_approval_for de arriba.

    - globally_denied: techo del sistema entero. Nadie por debajo (ningún
      nivel de confianza, ninguna sesión) puede otorgar un permiso que esté
      acá, pase lo que pase.
    - trust_tier_caps: techo por CÓMO se registró la herramienta (nunca por
      lo que la propia herramienta se autodeclare — ver
      sdk/permissions.py::trust_tier_for(), que decide el tier
      por el tipo del wrapper en el registry, no por un campo leído del
      manifiesto). "agent" ya alineado con
      tool_integration.require_human_approval_for: no bloquea nada que hoy
      no pase igual por esa aprobación humana. "skill" es deliberadamente
      el techo más bajo — una skill de terceros parte sin red ni escritura
      por defecto, aunque su propio manifest declare requires_network=True;
      hace falta subir esto acá explícitamente para habilitarlo de verdad.
    """
    globally_denied: list[str] = Field(default_factory=list)
    trust_tier_caps: dict[str, list[str]] = Field(default_factory=lambda: {
        "system": ["filesystem_read", "filesystem_write", "network", "browser",
                   "gpu", "camera", "microphone", "clipboard", "docker"],
        "agent": ["filesystem_read", "filesystem_write", "network"],
        "skill": ["filesystem_read"],
    })


class FilesystemAccessConfig(BaseModel):
    """
    Política del Permission Manager de filesystem (ver
    kernel/permissions/filesystem_access_manager.py) — ORTOGONAL a
    PermissionCascadeConfig de arriba: aquella decide "¿esta herramienta
    puede pedir tocar el filesystem en absoluto?" (FILESYSTEM_READ/WRITE
    por nivel de confianza); esta decide "¿esta acción concreta, en este
    alcance concreto, se auto-permite o necesita un humano?".

    `auto_allow`: alcance -> acciones que se auto-permiten sin pedir
    aprobación (siempre que la propia PermissionCascade ya haya
    otorgado FILESYSTEM_WRITE). Fail-safe por diseño: cualquier
    combinación scope/acción que NO esté listada acá requiere
    aprobación humana explícita — nunca al revés. Default: crear/
    modificar dentro del workspace (el caso de menor riesgo, el único
    que ejercita hoy el agente IDE de VS Code) — todo lo demás (borrar/
    renombrar en el workspace, cualquier acción en home/external)
    requiere aprobación.
    """
    auto_allow: dict[str, list[str]] = Field(default_factory=lambda: {
        "workspace": ["create", "modify"],
    })


class AuditConfig(BaseModel):
    log_path: str = "logs/audit.log"
    immutable: bool = True


class SigningConfig(BaseModel):
    key_dir: str = "data/keys"


class BrowserConfig(BaseModel):
    headless: bool = True
    timeout_seconds: int = 30
    # Deny-by-default (mismo principio que sandbox.network_mode="none"):
    # vacío significa que NINGÚN dominio está permitido todavía. BrowserTool
    # existe y queda registrada, pero no navega a ningún lado hasta que se
    # agreguen dominios explícitos acá — nunca "abierto por default".
    allowed_domains: list[str] = Field(default_factory=list)
    artifact_dir: str = "data/artifacts/browser"
    user_agent: str = "kal-browser-agent/1.0"


class DownloadsConfig(BaseModel):
    """
    Política de descarga real de recursos externos (Artifact Service,
    ver kernel/permissions/network_access_manager.py). Deliberadamente
    SEPARADA de BrowserConfig aunque comparta el espíritu
    deny-by-default: semántica distinta (sin JS/cookies, con tope de
    tamaño real) — un dominio confiable para navegar interactivamente
    no implica confiar en descargar binarios de ahí, y viceversa.
    """
    allow_http: bool = False  # solo https por default — una respuesta http puede alterarse en tránsito
    allowed_domains: list[str] = Field(default_factory=list)  # deny-by-default, igual que browser.allowed_domains
    max_size_mb: int = 10
    # El consumidor real (una Skill aislada que recibe el archivo
    # descargado como artifact://) necesita un directorio propio para
    # persistirlo — mismo patrón que browser.artifact_dir arriba.
    artifact_dir: str = "data/artifacts/downloads"


class Settings(BaseModel):
    schema_version: int
    sandbox: SandboxConfig
    tool_integration: ToolIntegrationConfig
    permissions: PermissionCascadeConfig = PermissionCascadeConfig()
    filesystem_access: FilesystemAccessConfig = FilesystemAccessConfig()
    resource_broker: ResourceBrokerConfig = ResourceBrokerConfig()
    downloads: DownloadsConfig = DownloadsConfig()
    audit: AuditConfig
    signing: SigningConfig = SigningConfig()
    browser: BrowserConfig = BrowserConfig()


def load_settings(path: str | Path = "config/config.yaml") -> Settings:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings.model_validate(raw)


# Instancia global cargada una vez al arrancar el proceso.
# Otros módulos deben importar `settings` de aquí, no releer el YAML.
settings = load_settings()
