"""
Adaptador de navegación web: extrae texto/enlaces o captura pantalla de
una página real, vía Playwright (Chromium).

A diferencia de las herramientas dinámicas que el propio agente puede
proponer (tool_integration/registry.py), esta es una herramienta de
PRIMERA PARTE — código nuestro, no generado por el agente — y por eso
corre fuera del sandbox de Docker, igual que ya hacen los adaptadores
de imagen/audio/video (tampoco pasan por SandboxExecutor). El permiso
BROWSER sigue estando en UNSUPPORTED_RUNTIME_PERMISSIONS para código
sandboxeado (herramientas dinámicas, run_code) — eso no cambia: código
arbitrario generado por el agente nunca debe obtener un navegador real
sin confinamiento.

El confinamiento acá es un allowlist de dominios
(config.yaml: browser.allowed_domains), vacío por defecto — DENY BY
DEFAULT: la herramienta existe y se ofrece al LLM, pero rechaza
cualquier navegación hasta que se agreguen dominios explícitos.

Carga perezosa: instanciar BrowserTool() no importa playwright ni
lanza Chromium — eso solo pasa en el primer execute() que pase el
chequeo de dominio, igual criterio que diffusers/piper-tts/moviepy en
los otros adaptadores (registrar la tool es seguro aunque playwright o
el binario de Chromium no estén instalados todavía).

BUG REAL ENCONTRADO EN HARDENING (F5): el allowlist solo se chequeaba
contra la URL de ENTRADA. Playwright sigue automáticamente cualquier
redirect HTTP (`page.goto()`), así que un dominio permitido con un
endpoint de redirect abierto (analytics, `/out?url=`, login flows,
acortadores — muy común en la web real) podía llevar el navegador a
CUALQUIER otro dominio, nunca aprobado, y ese contenido sí llegaba al
agente como si viniera de un dominio confiable — la puerta de entrada
real para inyección de prompt indirecta vía contenido web no confiable.
Fix: PlaywrightBrowserDriver también devuelve la URL FINAL (`page.url`
tras seguir redirects), y BrowserTool.execute() vuelve a chequearla
contra el allowlist antes de devolver cualquier contenido — no se
bloquea el redirect en sí (eso es comportamiento normal de un
navegador), se bloquea que contenido de un destino no aprobado llegue
al agente.

De paso, _is_domain_allowed() pasó de usar urlparse().netloc a
.hostname: netloc incluye userinfo (user@host) y puerto (host:8443),
que rompían la comparación exacta contra allowed_domains — negando de
más URLs legítimas. hostname es lo semánticamente correcto (el host
real de destino) y no debilita nada: http://evil.com@allowed.com/
antes se negaba por accidente (comparaba contra "evil.com@allowed.com"
completo); con .hostname se permite correctamente, porque el destino
real de red SÍ es allowed.com (evil.com es solo un usuario de auth
básica, no otro host).

HALLAZGO DE SEGURIDAD (Fase E6, revisión eBPF del 2026-07-10): todo lo
anterior valida el HOSTNAME de destino (string), nunca la IP real a la
que efectivamente se conectó Chromium — un dominio permitido cuyo DNS
apunte (por rebinding, o por un registro mal configurado) a una IP
privada/loopback/reservada (127.0.0.1, 169.254.169.254, 10.0.0.0/8,
etc.) pasaba el chequeo de string sin problema y el contenido de esa
red interna llegaba igual al agente. Fix: `PlaywrightBrowserDriver`
ahora también devuelve la IP real de la conexión
(`Response.server_addr()` de Playwright — la IP que Chromium mismo
reporta haber usado, no una resolución DNS aparte hecha por nosotros,
así que no hay ventana de carrera entre "lo que resolvimos" y "a dónde
se conectó de verdad"), y `_reject_if_unsafe_destination()` la valida
con `ipaddress` antes de exponer cualquier contenido.

Límite conocido y aceptado (documentado, no escondido — mismo criterio
que code_analysis/denylist.py): esto valida la navegación principal
(el documento de nivel superior), no cada subrecurso que la propia
página cargue después (una imagen/fetch/XHR embebido apuntando a una
IP interna es una petición que hace el navegador, no algo que este
código intercepta hoy). Tampoco protege si Chromium sirve la respuesta
desde caché sin una conexión viva (`server_addr()` devuelve None en
ese caso) — se falla cerrado (se rechaza) en vez de asumir que es
segura, aunque esto pueda rechazar de más algún caso legítimo raro.
"""
from __future__ import annotations

import ipaddress
import uuid
from pathlib import Path
from urllib.parse import urlparse

from audit.audit_log import AuditEvent, audit_log
from tool_integration.base_tool import Artifact, Tool, ToolManifest
from tool_integration.permissions import Permission
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def _is_unsafe_ip(remote_ip: str | None) -> bool:
    """
    True si `remote_ip` no es una dirección pública "normal" — privada,
    loopback, link-local, reservada, multicast, o no determinable. Fail
    closed: None (no se pudo saber a qué IP se conectó Chromium de
    verdad) se trata como inseguro, nunca como "asumimos que está bien".
    """
    if not remote_ip:
        return True
    try:
        addr = ipaddress.ip_address(remote_ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _server_addr_ip(response) -> str | None:
    """
    IP real a la que Chromium se conectó para `response` (la navegación
    principal), según el propio Playwright/CDP — None si no hay
    `response` (p.ej. navegación same-document) o si Chromium no puede
    reportarla (p.ej. respuesta servida desde caché sin conexión viva).
    """
    if response is None:
        return None
    try:
        addr = response.server_addr()
    except Exception:
        return None
    return addr["ipAddress"] if addr else None


class PlaywrightBrowserDriver:
    """
    Envoltorio real sobre Playwright (sync API). Un solo Chromium
    headless para toda la vida del proceso, una page nueva por
    navegación (evita contaminación de estado entre llamadas, mismo
    espíritu que "contenedor efímero por ejecución" del sandbox, aunque
    acá reutilizamos el browser en sí por costo de arranque).
    """

    def __init__(self, headless: bool = True, timeout_seconds: int = 30, user_agent: str = ""):
        self.headless = headless
        self.timeout_ms = timeout_seconds * 1000
        self.user_agent = user_agent
        self._playwright = None
        self._browser = None

    def _ensure_browser(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            logger.info("Lanzando Chromium headless vía Playwright (primera navegación de este proceso)")
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless)
        return self._browser

    def _new_page(self):
        browser = self._ensure_browser()
        page = browser.new_page(user_agent=self.user_agent or None)
        page.set_default_timeout(self.timeout_ms)
        return page

    def extract_text(self, url: str, selector: str | None = None) -> tuple[str, str, str | None]:
        page = self._new_page()
        try:
            response = page.goto(url)
            locator = page.locator(selector) if selector else page.locator("body")
            return locator.inner_text(), page.url, _server_addr_ip(response)
        finally:
            page.close()

    def extract_links(self, url: str) -> tuple[list[str], str, str | None]:
        page = self._new_page()
        try:
            response = page.goto(url)
            links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            return links, page.url, _server_addr_ip(response)
        finally:
            page.close()

    def screenshot(self, url: str, path: Path) -> tuple[str, str | None]:
        page = self._new_page()
        try:
            response = page.goto(url)
            page.screenshot(path=str(path), full_page=True)
            return page.url, _server_addr_ip(response)
        finally:
            page.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()


class BrowserTool(Tool):
    manifest = ToolManifest(
        name="browser",
        description=(
            "Navega una página web REAL (http/https) y extrae texto, enlaces, o una "
            "captura de pantalla. Solo funciona sobre dominios explícitamente "
            "permitidos en config.yaml (browser.allowed_domains) — si el dominio no "
            "está en la lista, la navegación se rechaza sin tocar la red. No sirve "
            "para 'ver' o inspeccionar archivos ya generados en disco (imágenes, "
            "audio, video) — esos artefactos ya quedaron guardados en la ruta que "
            "devolvió la herramienta que los generó, no hace falta navegarlos."
        ),
        requires_network=True,
        permissions=frozenset({Permission.BROWSER}),
        created_by="system",
        parameters_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completa a visitar"},
                "action": {
                    "type": "string",
                    "enum": ["text", "screenshot", "links"],
                    "default": "text",
                    "description": "Qué extraer: texto visible, captura de pantalla, o enlaces de la página",
                },
                "selector": {
                    "type": "string",
                    "description": "Selector CSS opcional para limitar la extracción de texto a una parte de la página",
                },
            },
            "required": ["url"],
        },
    )

    def __init__(self, driver: PlaywrightBrowserDriver | None = None):
        self.cfg = settings.browser
        self.driver = driver
        Path(self.cfg.artifact_dir).mkdir(parents=True, exist_ok=True)

    def _get_driver(self) -> PlaywrightBrowserDriver:
        if self.driver is None:
            self.driver = PlaywrightBrowserDriver(
                headless=self.cfg.headless, timeout_seconds=self.cfg.timeout_seconds, user_agent=self.cfg.user_agent
            )
        return self.driver

    def _is_domain_allowed(self, url: str) -> bool:
        allowed = self.cfg.allowed_domains
        if not allowed:
            return False  # deny-by-default: sin dominios configurados, nada permitido
        domain = (urlparse(url).hostname or "").lower()
        return any(domain == d or domain.endswith(f".{d}") for d in (d.lower() for d in allowed))

    def execute(self, url: str, action: str = "text", selector: str | None = None, **kwargs) -> Artifact:
        scheme = urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            reason = (
                f"'{url}' no es una URL http/https real — este navegador no sirve para "
                "abrir archivos locales (file://) ni otros esquemas. Si es un archivo que "
                "vos u otra herramienta ya generaron (imagen/audio/video), ya está guardado "
                "en esa ruta — no hace falta 'navegarlo' ni capturarlo de nuevo."
            )
            self._audit("failure", url, action, reason)
            return Artifact(modality="text", uri="", metadata={"status": "error", "stderr": reason})

        domain = urlparse(url).netloc or url
        if not self._is_domain_allowed(url):
            reason = (
                f"Dominio no permitido: '{domain}'. Agregarlo a config.yaml: "
                "browser.allowed_domains para habilitar la navegación."
            )
            self._audit("failure", url, action, reason)
            return Artifact(modality="text", uri="", metadata={"status": "error", "stderr": reason})

        try:
            driver = self._get_driver()
            if action == "screenshot":
                artifact_id = str(uuid.uuid4())
                path = Path(self.cfg.artifact_dir) / f"{artifact_id}.png"
                final_url, remote_ip = driver.screenshot(url, path)
                rejection = self._reject_if_unsafe_destination(url, action, final_url, remote_ip)
                if rejection is not None:
                    path.unlink(missing_ok=True)  # no dejar en disco una captura de un destino no aprobado
                    return rejection
                self._audit("success", url, action)
                return Artifact(modality="image", uri=str(path), metadata={"url": url})

            if action == "links":
                links, final_url, remote_ip = driver.extract_links(url)
                rejection = self._reject_if_unsafe_destination(url, action, final_url, remote_ip)
                if rejection is not None:
                    return rejection
                self._audit("success", url, action)
                summary = "\n".join(links) if links else "(sin enlaces encontrados)"
                return Artifact(modality="text", uri="", metadata={"summary": summary})

            text, final_url, remote_ip = driver.extract_text(url, selector=selector)
            rejection = self._reject_if_unsafe_destination(url, action, final_url, remote_ip)
            if rejection is not None:
                return rejection
            self._audit("success", url, action)
            return Artifact(modality="text", uri="", metadata={"summary": text})
        except Exception as e:
            logger.exception(f"Fallo navegando a {url!r} (action={action!r})")
            self._audit("failure", url, action, str(e))
            return Artifact(modality="text", uri="", metadata={"status": "error", "stderr": str(e)})

    def _reject_if_unsafe_destination(
        self, original_url: str, action: str, final_url: str, remote_ip: str | None
    ) -> Artifact | None:
        """
        Dos chequeos independientes contra el destino REAL de la
        navegación (tras seguir cualquier redirect):

        1. Allowlist de dominios contra la URL final — ver "BUG REAL
           ENCONTRADO EN HARDENING" en el docstring del módulo.
        2. La IP a la que Chromium efectivamente se conectó no es
           privada/loopback/reservada — ver "HALLAZGO DE SEGURIDAD
           (Fase E6)" en el docstring del módulo (DNS rebinding: un
           dominio permitido puede resolver a una IP interna).

        Devuelve None si ambos chequeos pasan; un Artifact de error si
        alguno falla — el contenido ya extraído nunca se expone en ese
        caso.
        """
        if not self._is_domain_allowed(final_url):
            reason = (
                f"Un redirect llevó de '{original_url}' a un dominio no permitido: "
                f"'{urlparse(final_url).hostname}'. El contenido de ese destino no se expone."
            )
            self._audit("failure", original_url, action, reason)
            return Artifact(modality="text", uri="", metadata={"status": "error", "stderr": reason})

        if _is_unsafe_ip(remote_ip):
            reason = (
                f"El dominio '{urlparse(final_url).hostname}' resolvió a una dirección IP "
                f"privada/reservada/no determinable ({remote_ip!r}) al conectar — posible DNS "
                "rebinding. El contenido de ese destino no se expone."
            )
            self._audit("failure", original_url, action, reason)
            return Artifact(modality="text", uri="", metadata={"status": "error", "stderr": reason})

        return None

    def _audit(self, outcome: str, url: str, action: str, detail: str = "") -> None:
        audit_log.record(
            AuditEvent(
                event_type="browser_navigation",
                summary=f"Navegación ({action}) a {url}: {detail or outcome}",
                context={"url": url, "action": action},
                outcome=outcome,
            )
        )
