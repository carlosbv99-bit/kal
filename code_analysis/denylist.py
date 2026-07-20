"""
Denylist de nodos/llamadas AST prohibidos en código no confiable.

Esto es un filtro barato de primera línea, NO la garantía de seguridad
(esa la da el aislamiento real en sandbox/). Ver kernel/lifecycle/docker_runner.py
para la capa que realmente contiene el daño si esta lista falla en
detectar algo (código ofuscado, por ejemplo).

HUECO CONOCIDO Y ACEPTADO: acceso por subíndice a __builtins__ dentro de
un script ejecutado como __main__ (p.ej. `__builtins__['eval']`, aunque
`__builtins__` como módulo no es subscriptable en ese contexto — pero
`getattr(__builtins__, 'e'+'val')` sí funcionaría si getattr no estuviera
bloqueado, y variantes futuras de ofuscación seguirán apareciendo). Esta
lista NO puede ser exhaustiva contra un adversario que construye el AST
para evadirla a propósito — es un filtro heurístico, no una prueba
formal. Por eso tests/test_sandbox_escape_resistance.py valida que,
incluso cuando el código llega a ejecutarse sin pasar por esta
validación, el aislamiento de Docker (sin red, fs read-only, cap_drop
ALL, usuario no-root, namespaces separados) sigue conteniendo el daño.
"""

# Nombres de funciones/builtins prohibidos en cualquier contexto
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",          # se permite solo vía wrapper controlado, no builtin directo
    "input",
    # Estas cuatro son el vector típico para saltarse el chequeo de
    # FORBIDDEN_ATTRIBUTES: getattr(x, '__subclasses__'+'') no es un
    # nodo ast.Attribute, así que el visitor de atributos no lo ve.
    # Bloquearlas aquí cierra ese hueco a nivel de llamada.
    "getattr",
    "setattr",
    "vars",
    "globals",
    "locals",
}

# Módulos cuya importación está prohibida por defecto (requieren
# aprobación humana explícita en el manifiesto de la herramienta,
# ver kernel/registry/registry.py)
FORBIDDEN_IMPORTS = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "ctypes",
    "shutil",
    "pickle",     # deserialización insegura
    "marshal",
    "importlib",  # permite importar cualquier módulo (incluidos os/subprocess)
                  # por nombre en runtime, evitando el chequeo de import literal
}

# Atributos peligrosos (p.ej. acceso a __globals__, __subclasses__ para
# sandbox escapes clásicos de Python)
FORBIDDEN_ATTRIBUTES = {
    "__globals__",
    "__subclasses__",
    "__bases__",
    "__mro__",
    "__builtins__",
}
