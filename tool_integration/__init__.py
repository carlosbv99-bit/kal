"""
Herramientas de PRIMERA PARTE concretas (adaptadores multimodales,
descarga de recursos, escaneo de malware) — el mecanismo GENÉRICO del
que estas son consumidoras (registro, permisos, sandbox, bus de
servicios) vive en kernel/, y los tipos base que cualquier herramienta
(propia o de una Skill de terceros) usa viven en sdk/ (Tool,
ToolManifest, Artifact, Permission).

Reestructurado (2026-07-20): este paquete solía contener también esa
infraestructura genérica — ver kernel/__init__.py para el mapeo
completo de qué se movió a dónde.
"""
