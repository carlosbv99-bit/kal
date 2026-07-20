# Imagen de ejecución para código no confiable en sandbox/docker_runner.py.
#
# Diferencia con python:3.11-slim genérico (usado hasta ahora): esta
# imagen elimina herramientas que, aunque no dan una vía de escape del
# contenedor por sí mismas (el aislamiento real es Docker: sin red,
# fs read-only, cap_drop ALL, namespaces separados — ver
# tests/test_sandbox_escape_resistance.py), sí amplían innecesariamente
# lo que un adversario podría hacer SI llegara a ejecutar comandos de
# shell dentro del contenedor (instalar algo con pip, usar dpkg, etc.).
# Defensa en profundidad barata: no reemplaza el aislamiento, lo reduce
# como superficie adicional.
#
# Build:
#   docker build -t kal-sandbox-minimal:latest -f sandbox/images/minimal/Dockerfile .
# (o usar scripts/build_sandbox_image.sh)

FROM python:3.11-slim

# Mismo UID/GID que SANDBOX_UID/SANDBOX_GID en sandbox/docker_runner.py.
# Deben coincidir para que el bind mount de /workspace sea legible.
RUN groupadd -g 1000 sandboxuser && \
    useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin sandboxuser

# Elimina pip y el mecanismo de instalación de paquetes. Si en el
# futuro una herramienta necesita instalar algo (ver
# error_handling/strategies.py: ImportErrorStrategy), debe hacerse
# reinstalando pip vía una imagen derivada específica para esa
# operación puntual, con su propia excepción de red auditada — nunca
# teniendo pip disponible por defecto en la imagen de ejecución general.
RUN python3 -m pip uninstall pip setuptools wheel -y 2>/dev/null || true && \
    rm -rf /usr/local/lib/python3.11/ensurepip \
           /usr/local/lib/python3.11/site-packages/pip* \
           /usr/local/lib/python3.11/site-packages/setuptools* \
           /usr/local/lib/python3.11/site-packages/wheel* \
           /usr/local/bin/pip*

# Elimina apt/dpkg: sin esto, código con acceso a shell podría instalar
# paquetes del sistema (incluyendo herramientas de red o compiladores).
RUN rm -rf /usr/bin/apt* /usr/bin/dpkg* /usr/lib/apt /usr/lib/dpkg \
           /var/lib/dpkg /var/lib/apt /etc/apt /usr/sbin/dpkg*

# Quita el bit setuid/setgid de cualquier binario que lo tenga (su,
# mount, etc.). No debería importar dado cap_drop=ALL en el contenedor,
# pero es una capa adicional sin costo si algún día se relajan las
# capabilities por error de configuración.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} \; 2>/dev/null || true

WORKDIR /workspace
USER sandboxuser
