"""
Chequeos de seguridad de red compartidos entre cualquier código que
haga que kal se conecte a un destino elegido por el usuario/modelo
(hoy: tool_integration/adapters/browser.py vía Playwright,
tool_integration/download_manager.py vía requests). Extraído de
browser.py — el download manager necesita EXACTAMENTE la misma
protección (allowlist de dominios + rechazo de IPs privadas/reservadas
por DNS rebinding), duplicarla en dos lugares hubiera sido el mismo
bug esperando pasar dos veces en vez de una.
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
