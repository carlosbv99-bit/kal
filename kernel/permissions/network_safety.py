"""
Chequeos de seguridad de red — infraestructura del kernel EXPUESTA
para que un consumidor externo (kal-in: tool_integration/adapters/
browser.py vía Playwright, tool_integration/download_manager.py vía
requests; ninguno de los dos existe en este repo, kernel puro) los use
antes de conectarse a un destino elegido por el usuario/modelo.

HALLAZGO REAL DE AUDITORÍA EXTERNA (M-6, 2026-09-27): is_unsafe_ip()
no tiene NINGÚN llamador dentro de este repo — kal en sí nunca hace
una conexión de red saliente por su cuenta (solo orquesta contenedores
Docker), así que no hay ningún punto propio donde aplicarlo. Confirmado
que sí tiene consumidores reales en kal-in (browser.py,
download_manager.py, llm_settings.py) — no es código muerto en un
sentido arquitectónico, es infraestructura de kernel para quien SÍ
hace conexiones de red reales, análogo a network_access_manager.py.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def is_unsafe_ip(remote_ip: str | None) -> bool:
    """
    True si `remote_ip` no es una dirección pública "normal" — privada,
    loopback, link-local, reservada, multicast, o no determinable. Fail
    closed: None (no se pudo saber a qué IP se conectó de verdad) se
    trata como inseguro, nunca como "asumimos que está bien".
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


def is_hostname_allowed(hostname: str, allowed_domains: list[str]) -> bool:
    """
    True si `hostname` está en `allowed_domains` (exacto o subdominio)
    — deny-by-default: una lista vacía nunca permite nada. Extraída de
    is_domain_allowed() para que quien ya tenga el hostname (p.ej.
    kernel/permissions/network_access_manager.py, que lo usa como
    resource_key) no tenga que reconstruir una URL fake solo para
    volver a parsearla.
    """
    if not allowed_domains:
        return False
    domain = (hostname or "").lower()
    return any(domain == d or domain.endswith(f".{d}") for d in (d.lower() for d in allowed_domains))


def is_domain_allowed(url: str, allowed_domains: list[str]) -> bool:
    """
    True si el host de `url` está en `allowed_domains` (exacto o
    subdominio) — deny-by-default: una lista vacía nunca permite nada.
    """
    return is_hostname_allowed(urlparse(url).hostname or "", allowed_domains)
