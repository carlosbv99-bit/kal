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

# Antes de leer nada de os.environ (p.ej. IMAGE_GEN_API_KEY/AUDIO_GEN_API_KEY
# en los adaptadores multimodales, ver tool_integration/adapters/), asegura
# que .env ya se haya cargado al proceso — python-dotenv era dependencia
# declarada desde el inicio del proyecto pero nunca se llamaba a load_dotenv().
load_dotenv()


class LLMConfig(BaseModel):
    """
    Configuración del "cerebro" del agente. Por defecto un modelo local
    vía Ollama — nunca apunta a un servicio en la nube por defecto, hay
    que elegirlo explícitamente (`provider: openai_compatible`), para
    no romper el principio de "sin red inesperada" del resto del
    proyecto. kal se distribuye a usuarios con hardware muy distinto
    (ver docs/HISTORY.md, "Confirmación explícita: kal es para uso
    general, no personal") — alguien sin RAM/VRAM para un modelo local
    de 30B necesita poder apuntar a un proveedor en la nube (Qwen,
    Grok/xAI, OpenAI, OpenRouter, etc.) sin tocar código, solo config.
    """
    # "ollama": agent_core/llm/ollama_client.py (formato nativo /api/chat).
    # "openai_compatible": agent_core/llm/openai_compatible_client.py
    # (formato OpenAI, {base_url}/chat/completions) — sirve tanto para el
    # propio Ollama (F2, ya validado) como para cualquier proveedor real
    # que hable ese mismo formato: Qwen (DashScope, modo compatible),
    # Grok/xAI (api.x.ai/v1), OpenAI, OpenRouter, vLLM, etc. Requiere
    # LLM_API_KEY en el entorno (ver .env.example) — sin ella, kal falla
    # al arrancar con un error claro, nunca intenta sin autenticación.
    provider: Literal["ollama", "openai_compatible"] = "ollama"
    # Con provider: openai_compatible, tiene que ser la URL COMPLETA que
    # pide ese proveedor (incluido cualquier sufijo tipo "/v1" — p.ej.
    # "https://api.x.ai/v1", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    # nunca se le agrega nada por detrás. El default de acá abajo es
    # correcto tal cual solo para provider: ollama.
    base_url: str = "http://localhost:11434"
    default_model: str = "qwen3-coder:30b"
    timeout_seconds: int = 120
    max_agent_steps: int = 8  # tope de iteraciones del loop de razonamiento/herramientas
    # Descomponer el objetivo en subtareas (agent_core/llm/planner.py) antes
    # de ejecutar, en vez de improvisar un paso ReAct a la vez. Overrideable
    # por request (ChatRequest.use_planner) sin tocar config.
    planning_enabled: bool = True
    # BUG REAL ENCONTRADO EN USO: con generación de imagen/audio/video corriendo
    # en la misma máquina (SDXL-turbo, etc.), Ollama puede quedar momentáneamente
    # sin responder (recargando el modelo en VRAM/RAM tras competir por el mismo
    # hardware) y una sola llamada de un paso intermedio del agente rompía TODA
    # la tarea con un ConnectionError, aunque Ollama estuviera bien un segundo
    # antes y un segundo después. Reintentar un par de veces con una pausa corta
    # antes de rendirse cubre ese hueco transitorio real (ver ollama_client.py).
    connection_retries: int = 2
    retry_backoff_seconds: float = 2.0
    # BUG REAL ENCONTRADO EN USO: pedido "genera una raqueta de tenis" —
    # el modelo generó la imagen correcta UNA vez y después, en el mismo
    # turno, generó 3 imágenes más de paisajes sin relación, sin llegar
    # nunca a una respuesta final (agotó max_agent_steps). El modelo
    # nunca ve el resultado visual (la observación es solo la ruta del
    # archivo) — no está "reintentando por mala calidad", pierde el
    # hilo. Una instrucción de prompt sola no alcanzó (confirmado: la
    # regla ya estaba activa cuando pasó esto). Tope estructural en el
    # código (ver agent_core/llm/agent_loop.py): más allá de esta
    # cantidad de llamadas a la MISMA herramienta en un mismo turno, se
    # rechaza sin ejecutar (cada llamada de generación real cuesta
    # minutos de cómputo en esta máquina, no es gratis dejarlo correr).
    max_tool_repeats: int = 3


class ShortTermConfig(BaseModel):
    max_tokens: int = 8000
    ttl_seconds: int | None = None


class MidTermConfig(BaseModel):
    backend: Literal["sqlite", "postgres"] = "sqlite"
    ttl_days: int = 30
    consolidation_interval_hours: int = 6


class PromotionConfig(BaseModel):
    min_repetitions: int = 3
    min_relevance_score: float = 0.75


class LongTermConfig(BaseModel):
    backend: Literal["chroma", "qdrant"] = "chroma"
    # embedded: chromadb corre embebido en el propio proceso, persistido
    # en disco local (data/long_term/chroma_persist). Sin red, sin
    # servicio aparte. http: usa el servicio `vector_store` de
    # docker-compose vía red interna — útil si varios procesos/workers
    # necesitan compartir el mismo índice.
    mode: Literal["embedded", "http"] = "embedded"
    persist_path: str = "data/long_term/chroma_persist"
    http_host: str = "vector_store"
    http_port: int = 8000
    # Modelo local de sentence-transformers. Se descarga una única vez
    # desde HuggingFace Hub la primera vez que se usa (requiere red esa
    # vez), luego queda cacheado en disco (~/.cache/huggingface) y no
    # vuelve a tocar la red. Sin llamadas a APIs externas por diseño.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    promotion: PromotionConfig = PromotionConfig()


class MemoryConfig(BaseModel):
    short_term: ShortTermConfig = ShortTermConfig()
    mid_term: MidTermConfig = MidTermConfig()
    long_term: LongTermConfig = LongTermConfig()


class ErrorHandlingConfig(BaseModel):
    max_repair_attempts: int = 3
    strategies: dict[str, str] = Field(default_factory=dict)


class ImageGenConfig(BaseModel):
    backend: Literal["local", "api"] = "local"
    # SDXL-Turbo: mismo criterio de distilación que sd-turbo (1-4 pasos,
    # guidance_scale=0), pero arquitectura SDXL — mejor calidad y nativo a
    # 1024x1024 (a diferencia de sd-turbo/SD1.5, que degrada notablemente
    # fuera de 512x512). Sustancialmente más pesado: ~14GB de descarga
    # (fp32 — float16 no es fiable en CPU, mismo motivo que ya regía para
    # sd-turbo) y bastante más lento por imagen en CPU.
    model: str = "stabilityai/sdxl-turbo"
    num_inference_steps: int = 2
    guidance_scale: float = 0.0
    height: int = 1024
    width: int = 1024
    artifact_dir: str = "data/artifacts/images"
    # backend="api": OpenAI Images. Requiere IMAGE_GEN_API_KEY en el entorno
    # (ver .env.example) — sin ella, la herramienta devuelve un error claro,
    # nunca cae silenciosamente al backend local.
    api_model: str = "dall-e-3"
    api_size: str = "1024x1024"


class AudioGenConfig(BaseModel):
    backend: Literal["local", "api"] = "local"
    voice_model: str = "es_ES-davefx-medium"
    artifact_dir: str = "data/artifacts/audio"
    # backend="api": OpenAI TTS. Requiere AUDIO_GEN_API_KEY en el entorno.
    api_model: str = "tts-1-hd"
    api_voice: str = "alloy"


class VideoGenConfig(BaseModel):
    fps: int = 24
    seconds_per_scene: int = 4
    artifact_dir: str = "data/artifacts/video"


class STTConfig(BaseModel):
    backend: Literal["local"] = "local"
    # "tiny" por defecto: ~75MB, corre rápido en CPU. Modelos más grandes
    # (base/small/medium/large) son más precisos pero más pesados/lentos.
    model_size: str = "tiny"
    language: str | None = None  # None = auto-detección


class ImageEditingConfig(BaseModel):
    artifact_dir: str = "data/artifacts/images_edited"
    # Inpainting real con IA (operación "inpaint"): modelo de difusión
    # COMPLETO (no distilado como sd-turbo) — mucho más lento en CPU,
    # del orden de minutos por edición, no segundos. guidance_scale=7.5
    # es el CFG estándar de SD (a diferencia de sd-turbo, que corre con 0).
    inpaint_model: str = "runwayml/stable-diffusion-inpainting"
    inpaint_num_inference_steps: int = 25
    inpaint_guidance_scale: float = 7.5


class ImageCompositionConfig(BaseModel):
    artifact_dir: str = "data/artifacts/images_composed"


class UploadsConfig(BaseModel):
    artifact_dir: str = "data/artifacts/uploads"
    max_size_mb: int = 20


class MultimodalConfig(BaseModel):
    image: ImageGenConfig = ImageGenConfig()
    audio: AudioGenConfig = AudioGenConfig()
    video: VideoGenConfig = VideoGenConfig()
    stt: STTConfig = STTConfig()
    image_editing: ImageEditingConfig = ImageEditingConfig()
    composition: ImageCompositionConfig = ImageCompositionConfig()
    uploads: UploadsConfig = UploadsConfig()


class ResourceBrokerConfig(BaseModel):
    """
    ImageService/AudioService/STTService (kernel_bus/services.py) cargan
    su modelo perezosamente pero nunca lo descargaban — BUG REAL
    ENCONTRADO EN USO: en una máquina sin GPU (todo corre en CPU), un
    pipeline de varios GB se queda en RAM para siempre una vez usado,
    compitiendo con Ollama por la misma RAM del sistema — confirmado en
    logs/agent.log: Ollama quedaba con "Connection refused" 1-2 minutos
    justo después de generar una imagen. Ver kernel_bus/resource_broker.py.
    """
    idle_timeout_seconds: int = 300
    min_available_ram_mb: int = 2048


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
    Cascada de permisos de varios niveles (ver tool_integration/permissions.py::
    PermissionCascade) — "más restrictivo gana". Strings planos (no el enum
    Permission) para no acoplar utils/config.py a tool_integration, mismo
    criterio que ToolIntegrationConfig.require_human_approval_for de arriba.

    - globally_denied: techo del sistema entero. Nadie por debajo (ningún
      nivel de confianza, ninguna sesión) puede otorgar un permiso que esté
      acá, pase lo que pase.
    - trust_tier_caps: techo por CÓMO se registró la herramienta (nunca por
      lo que la propia herramienta se autodeclare — ver
      tool_integration/permissions.py::trust_tier_for(), que decide el tier
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
    tool_integration/filesystem_access_manager.py) — ORTOGONAL a
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


class SelfModificationConfig(BaseModel):
    # Opt-in explícito, leído por SelfModificationManager.propose()
    # (agent_core/self_modification.py) como el primer chequeo, antes de
    # cualquier otra validación: en false, rechaza cualquier propuesta
    # sin tocar disco ni correr un solo test.
    enabled: bool = False
    scope: Literal["peripheral_only", "none"] = "peripheral_only"
    requires_human_review: list[str] = Field(default_factory=list)
    auto_rollback_on_regression: bool = True

    def is_core_path(self, path: str) -> bool:
        """
        Determina si una ruta pertenece al núcleo protegido.
        Usado por agent_core/orchestrator.py para bloquear self-modification
        autónoma sobre estos módulos, sin excepción.
        """
        return any(path.startswith(p.rstrip("*")) for p in self.requires_human_review)


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


class AgentConfig(BaseModel):
    name: str = "kal"
    max_concurrent_tasks: int = 4


class ContextConfig(BaseModel):
    # Cuántos turnos previos de la sesión se mandan al LLM en cada
    # llamada — ver agent_core/context_service.py. Antes no había
    # ningún límite (se mandaba TODO el historial de la sesión);
    # alcance mecánico, sin resumen todavía.
    max_recent_turns: int = 8


class Settings(BaseModel):
    schema_version: int
    agent: AgentConfig
    llm: LLMConfig = LLMConfig()
    memory: MemoryConfig
    error_handling: ErrorHandlingConfig
    multimodal: MultimodalConfig = MultimodalConfig()
    resource_broker: ResourceBrokerConfig = ResourceBrokerConfig()
    context: ContextConfig = ContextConfig()
    sandbox: SandboxConfig
    tool_integration: ToolIntegrationConfig
    permissions: PermissionCascadeConfig = PermissionCascadeConfig()
    filesystem_access: FilesystemAccessConfig = FilesystemAccessConfig()
    self_modification: SelfModificationConfig
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
